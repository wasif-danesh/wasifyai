"""The speech to text graph end to end with fake capabilities and an in-memory queue: no server, no
network. The "worker" is the test itself, resuming the graph with a job result."""

import json
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from stt_rig import make_rig
from wasifyai_platform_sdk import (
    JobError,
    JobFailed,
    JobOutput,
    JobResult,
    RunError,
    ScopedStorage,
    object_key,
)
from wasifyai_stt.graphs.transcribe import build_transcribe_graph
from wasifyai_stt.languages import load_languages
from wasifyai_stt.transcripts import FixedQuota, InMemoryTranscriptStore, TranscriptRecord

CONFIG: Any = {"configurable": {"thread_id": "th-1"}}
SAID = {
    "text": "Hello there, how are you today?",
    "language": "en",
    "segments": [
        {"start": 0.0, "end": 1.5, "text": "Hello there,"},
        {"start": 1.5, "end": 3.0, "text": " how are you today?"},
    ],
}


class Story:
    def __init__(self, rig, quota=None):
        self.rig = rig
        self.transcripts = InMemoryTranscriptStore()
        self.graph = build_transcribe_graph(
            rig.caps, InMemorySaver(), self.transcripts, rig.uploads, quota or FixedQuota(0),
            load_languages(),
        )  # fmt: skip
        self.state: dict = {}

    async def start(self, input: Any):
        self.state = await self.graph.ainvoke(input, CONFIG)
        return self

    @property
    def waiting(self) -> dict:
        intr = self.state.get("__interrupt__")
        return intr[0].value if intr else {}

    async def finish_job(self, status="completed", said: dict | None = None):
        """What the media worker does: store the result file, report the result."""
        job = self.rig.sink.submitted[-1]
        assert self.waiting == {"kind": "job", "job_id": job.job_id}
        if status == "completed":
            rel = f"jobs/{job.job_id}/transcript.json"
            body = json.dumps(SAID if said is None else said).encode()
            await self.rig.raw.put(object_key("t1", "wasifyai-stt", "u1", rel), body)
            result = JobResult(
                job_id=job.job_id,
                status="completed",
                outputs={"transcript": JobOutput(key=rel, content_type="application/json", size=4)},
            )
        else:
            result = JobResult(
                job_id=job.job_id,
                status="failed",
                error=JobError(code="job_failed", message="The speech failed."),
            )
        self.state = await self.graph.ainvoke(Command(resume=result.model_dump()), CONFIG)
        return self


async def exists(rig, rel: str) -> bool:
    return await rig.raw.exists(object_key("t1", "wasifyai-stt", "u1", rel))


def sent(job) -> dict:
    return job.inputs or job.prompt


async def test_a_recording_becomes_a_saved_transcript_and_the_audio_is_deleted(tmp_path, ctx):
    rig = make_rig(tmp_path)
    recorded: list = []

    class Indexer:
        async def index(self, kind, item_id, text):
            recorded.append((kind, item_id, text))

    rig.caps.indexer = Indexer()
    key = await rig.add_recording(seconds=90)
    s = await Story(rig).start({"audio_key": key, "language": "auto"})
    job = rig.sink.submitted[0]
    assert job.capability == "speech.transcribe"
    assert sent(job)["audio_key"] == key and sent(job)["language"] == ""  # detect
    assert sent(job)["engine"] == "whisper" and sent(job)["seconds"] == 90
    assert sent(job)["model"] == load_languages().engine.model
    assert sent(job)["detect_model"] == load_languages().engine.detect_model
    assert sent(job)["indic_languages"] == list(
        load_languages().indic
    )  # where the worker may route
    (row,) = s.transcripts.transcripts
    assert row.status == "working" and row.seconds == 90 and s.waiting["kind"] == "job"

    await s.finish_job()
    assert s.state["status"] == "done" and "__interrupt__" not in s.state
    (row,) = s.transcripts.transcripts
    assert (row.status, row.language, row.engine) == ("done", "en", "whisper")
    assert row.text == SAID["text"] and row.title == SAID["text"]
    assert [x["text"] for x in row.segments] == ["Hello there,", "how are you today?"]
    assert not await exists(rig, key) and not await exists(
        rig, f"jobs/{job.job_id}/transcript.json"
    )
    assert await rig.uploads.find("t1", "wasifyai-stt", "u1", key) is None  # the recording is gone
    assert recorded == [("transcript", row.id, f"{row.title}. English. {row.text}")]
    (event,) = [e for e in rig.usage.events if e.kind == "transcript.created"]
    assert event.quantity == 1.5 and event.unit == "minutes" and event.meta["language"] == "en"


async def test_a_chosen_language_is_given_to_the_job_and_kept(tmp_path, ctx):
    rig = make_rig(tmp_path)
    key = await rig.add_recording()
    s = await Story(rig).start({"audio_key": key, "language": "bn"})
    assert sent(rig.sink.submitted[0])["language"] == "bn"
    await s.finish_job(said={**SAID, "language": "bn", "text": "আমাদের দোকান"})
    assert s.transcripts.transcripts[0].language == "bn"
    assert s.transcripts.transcripts[0].title == "আমাদের দোকান"


@pytest.mark.parametrize(
    ("request_", "code"),
    [
        ({"audio_key": "uploads/none.wav", "language": "auto"}, "invalid_request"),
        ({"audio_key": "", "language": "auto"}, "invalid_request"),
        ({"language": "auto"}, "invalid_request"),
    ],
)
async def test_a_recording_that_is_not_the_users_is_refused(tmp_path, ctx, request_, code):
    rig = make_rig(tmp_path)
    s = await Story(rig).start(request_)
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == code
    assert rig.sink.submitted == [] and s.transcripts.transcripts == []


async def test_an_unknown_language_is_refused_and_the_recording_is_kept_for_a_retry(tmp_path, ctx):
    rig = make_rig(tmp_path)
    key = await rig.add_recording()
    s = await Story(rig).start({"audio_key": key, "language": "klingon"})
    assert s.state["refusal"]["code"] == "invalid_request"
    assert rig.sink.submitted == []
    assert await exists(rig, key)


async def test_a_picture_upload_is_not_a_recording(tmp_path, ctx):
    rig = make_rig(tmp_path)
    key = await rig.add_recording(kind="image")
    s = await Story(rig).start({"audio_key": key, "language": "auto"})
    assert s.state["refusal"]["code"] == "invalid_request"


async def test_over_the_daily_minutes_is_refused_and_the_recording_deleted(tmp_path, ctx):
    rig = make_rig(tmp_path)
    key = await rig.add_recording(seconds=600)  # 10 minutes
    s = await Story(rig, quota=FixedQuota(115)).start({"audio_key": key, "language": "auto"})
    assert (
        s.state["refusal"]["code"] == "quota_exceeded"
        and "120 minutes" in s.state["refusal"]["message"]
    )
    assert rig.sink.submitted == [] and not await exists(rig, key)


async def test_a_recording_that_just_fits_is_accepted(tmp_path, ctx):
    rig = make_rig(tmp_path)
    key = await rig.add_recording(seconds=300)  # 5 minutes: 115 + 5 = 120
    s = await Story(rig, quota=FixedQuota(115)).start({"audio_key": key, "language": "auto"})
    assert s.state.get("status") != "refused" and len(rig.sink.submitted) == 1


async def test_one_recording_at_a_time(tmp_path, ctx):
    rig = make_rig(tmp_path)
    first = await Story(rig).start({"audio_key": await rig.add_recording(), "language": "auto"})
    second_key = await rig.add_recording()
    s2 = Story(rig)
    s2.transcripts = first.transcripts  # the same database
    s2.graph = build_transcribe_graph(
        rig.caps, InMemorySaver(), first.transcripts, rig.uploads, FixedQuota(0), load_languages()
    )
    out = await s2.graph.ainvoke(
        {"audio_key": second_key, "language": "auto"}, {"configurable": {"thread_id": "th-2"}}
    )
    assert out["refusal"]["code"] == "busy" and not await exists(rig, second_key)


async def test_a_failed_job_marks_the_row_and_deletes_the_recording(tmp_path, ctx):
    rig = make_rig(tmp_path)
    key = await rig.add_recording()
    s = await Story(rig).start({"audio_key": key, "language": "auto"})
    with pytest.raises(JobFailed):
        await s.finish_job("failed")
    (row,) = s.transcripts.transcripts
    assert row.status == "failed" and row.error == "The speech failed."
    assert not await exists(rig, key)


async def test_silence_is_a_plain_error_not_an_empty_transcript(tmp_path, ctx):
    rig = make_rig(tmp_path)
    key = await rig.add_recording()
    s = await Story(rig).start({"audio_key": key, "language": "auto"})
    with pytest.raises(RunError) as e:
        await s.finish_job(said={"text": "  ", "language": "en", "segments": []})
    assert e.value.code == "no_speech"
    assert s.transcripts.transcripts[0].status == "failed"
    assert not await exists(rig, key)
    assert not [e for e in rig.usage.events if e.kind == "transcript.created"]


async def test_an_unreadable_result_is_a_retryable_error(tmp_path, ctx):
    rig = make_rig(tmp_path)
    key = await rig.add_recording()
    s = await Story(rig).start({"audio_key": key, "language": "auto"})
    job = rig.sink.submitted[-1]
    rel = f"jobs/{job.job_id}/transcript.json"
    await rig.raw.put(object_key("t1", "wasifyai-stt", "u1", rel), b"not json")
    result = JobResult(
        job_id=job.job_id,
        status="completed",
        outputs={"transcript": JobOutput(key=rel, content_type="application/json", size=8)},
    )
    with pytest.raises(RunError) as e:
        await s.graph.ainvoke(Command(resume=result.model_dump()), CONFIG)
    assert e.value.code == "transcript_failed" and e.value.retryable
    assert s.transcripts.transcripts[0].status == "failed"


async def test_a_stale_working_row_is_marked_failed_when_read(tmp_path):
    from datetime import UTC, datetime, timedelta

    store = InMemoryTranscriptStore()
    old = datetime.now(UTC) - timedelta(hours=2)
    await store.add(
        TranscriptRecord("a", "t1", "wasifyai-stt", "u1", None, None, "working", 10, created_at=old)
    )
    got = await store.get("t1", "u1", "a")
    assert got is not None and got.status == "failed" and "took too long" in (got.error or "")
    assert await store.working_count("t1", "u1") == 0


_ = ScopedStorage  # imported for the rig's types
