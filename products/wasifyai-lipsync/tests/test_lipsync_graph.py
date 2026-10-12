"""The lip sync graph end to end with scripted fake models and an in-memory queue: no GPU, no
network. The "worker" is the test itself, resuming the graph with a job result."""

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from lipsync_rig import (
    make_rig,
    mp4,
    put_image,
    put_voice,
    transcript,
    verdict,
    wav,
)
from wasifyai_lipsync.graphs.lipsync import build_lipsync_graph
from wasifyai_lipsync.lipsyncs import FixedQuota, InMemoryLipSyncStore
from wasifyai_platform_sdk import JobError, JobFailed, JobOutput, JobResult, RunError, object_key

CONFIG: Any = {"configurable": {"thread_id": "th-1"}}
SCRIPT = {
    "source": "script",
    "script": "Hello there, how are you?",
    "language": "en-US",
    "gender": "female",
}


class Story:
    """Drives a run: start it, play the media worker."""

    def __init__(self, rig, quota=None):
        self.rig = rig
        self.rows = InMemoryLipSyncStore()
        self.graph = build_lipsync_graph(
            rig.caps, InMemorySaver(), self.rows, rig.uploads, quota or FixedQuota(0)
        )
        self.state: dict = {}

    async def start(self, input: Any):
        self.state = await self.graph.ainvoke(input, CONFIG)
        return self

    @property
    def waiting(self) -> dict:
        intr = self.state.get("__interrupt__")
        return intr[0].value if intr else {}

    async def finish_job(self, name: str, ctype: str, data: bytes, ext: str, status="completed"):
        """What the media worker does: store the file, report the result."""
        job = self.rig.sink.submitted[-1]
        assert self.waiting == {"kind": "job", "job_id": job.job_id}
        if status == "completed":
            rel = f"jobs/{job.job_id}/{name}.{ext}"
            await self.rig.raw.put(object_key("t1", "wasifyai-lipsync", "u1", rel), data)
            result = JobResult(
                job_id=job.job_id,
                status="completed",
                outputs={name: JobOutput(key=rel, content_type=ctype, size=4)},
            )
        else:
            result = JobResult(
                job_id=job.job_id,
                status="failed",
                error=JobError(code="job_failed", message="The generation failed on the GPU."),
            )
        self.state = await self.graph.ainvoke(Command(resume=result.model_dump()), CONFIG)
        return self

    async def speech(self, seconds=3.0, status="completed"):
        return await self.finish_job("audio", "audio/wav", wav(seconds, 24000), "wav", status)

    async def words(self, text: str):
        return await self.finish_job("transcript", "application/json", transcript(text), "json")

    async def clip(self, status="completed", data: bytes | None = None):
        return await self.finish_job("video", "video/mp4", data or mp4(), "mp4", status)


async def exists(rig, rel: str) -> bool:
    return await rig.raw.exists(object_key("t1", "wasifyai-lipsync", "u1", rel))


# ---- a script ------------------------------------------------------------------------------


async def test_a_script_is_spoken_then_lip_synced_and_saved(tmp_path, ctx):
    rig = make_rig(tmp_path)
    image = await put_image(rig)
    s = await Story(rig).start({**SCRIPT, "image_key": image.key, "style": "calm, smiling"})
    # the words and the picture were checked, then the voice is made first
    assert len(rig.word_checks()) == 1 and len(rig.picture_checks()) == 1
    speech = rig.sink.submitted[0]
    assert speech.capability == "speech.synthesize"
    assert speech.prompt["text"] == SCRIPT["script"]
    (row,) = s.rows.videos
    assert (row.status, row.source, row.script, row.style) == (
        "working", "script", SCRIPT["script"], "calm, smiling",
    )  # fmt: skip

    await s.speech(3.0)
    job = rig.sink.submitted[1]
    lipsync_id = row.id
    assert job.capability == "video.lipsync"
    assert job.prompt["image_key"] == image.key
    assert job.prompt["audio_key"] == f"uploads/lipsync-{lipsync_id}.wav"  # where the worker reads
    assert (
        job.prompt["length"] == 75 and job.prompt["prompt"] == "a person is talking, calm, smiling"
    )

    await s.clip()
    final = s.state
    assert final["status"] == "done" and "__interrupt__" not in final
    assert final["video_key"] == f"{lipsync_id}/video.mp4"
    assert await exists(rig, f"{lipsync_id}/video.mp4") and await exists(
        rig, f"{lipsync_id}/poster.jpg"
    )
    # the user's picture and the made voice are not kept
    assert not await exists(rig, image.key) and not await exists(
        rig, f"uploads/lipsync-{lipsync_id}.wav"
    )
    (done,) = s.rows.videos
    assert (done.status, done.width, done.height, done.seconds) == ("done", 128, 96, 3.0)
    created = [e for e in rig.usage.events if e.kind == "lipsync.created"]
    assert len(created) == 1 and created[0].quantity == 1 and created[0].meta["seconds"] == 3.0


async def test_a_script_that_speaks_for_too_long_is_refused_and_nothing_is_kept(tmp_path, ctx):
    rig = make_rig(tmp_path)
    image = await put_image(rig)
    s = await Story(rig).start({**SCRIPT, "image_key": image.key})
    await s.speech(400.0)
    assert s.state["refusal"]["code"] == "too_long"
    assert [r.status for r in s.rows.videos] == ["failed"]
    assert len(rig.sink.submitted) == 1 and not await exists(rig, image.key)


# ---- a voice -------------------------------------------------------------------------------


async def test_an_uploaded_voice_is_transcribed_and_checked_while_the_safeguards_are_on(
    tmp_path, ctx
):
    rig = make_rig(tmp_path)
    image, voice = await put_image(rig), await put_voice(rig, 4.0)
    s = await Start(rig, image, voice)
    assert rig.sink.submitted[0].capability == "speech.transcribe"
    assert rig.sink.submitted[0].prompt["audio_key"] == voice.key
    await s.words("Good morning everyone")
    assert len(rig.word_checks()) == 1  # the transcript went to the moderator
    job = rig.sink.submitted[1]
    assert job.capability == "video.lipsync" and job.prompt["audio_key"] == voice.key
    assert job.prompt["length"] == 100
    await s.clip()
    assert s.state["status"] == "done"
    (row,) = s.rows.videos
    assert row.transcript == "Good morning everyone" and row.source == "audio"
    assert not await exists(rig, voice.key) and not await exists(rig, image.key)


async def Start(rig, image, voice, **extra):
    return await Story(rig).start(
        {"source": "audio", "image_key": image.key, "audio_key": voice.key, **extra}
    )


async def test_a_voice_that_says_something_not_allowed_is_refused_after_it_is_heard(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=[verdict(), verdict(False, "hate")])
    image, voice = await put_image(rig), await put_voice(rig)
    s = await Start(rig, image, voice, style="calm")
    await s.words("something hateful")
    assert s.state["refusal"]["code"] == "hate"
    assert [r.status for r in s.rows.videos] == ["failed"]
    assert len(rig.sink.submitted) == 1  # no clip was made
    assert not await exists(rig, voice.key) and not await exists(rig, image.key)


async def test_a_voice_longer_than_the_limit_is_refused_up_front(tmp_path, ctx):
    rig = make_rig(tmp_path)
    image, voice = await put_image(rig), await put_voice(rig, 301.0)
    s = await Start(rig, image, voice)
    assert s.state["refusal"]["code"] == "too_long"
    assert rig.sink.submitted == [] and s.rows.videos == []
    assert not await exists(rig, image.key) and not await exists(rig, voice.key)


# ---- the guardrails ------------------------------------------------------------------------


async def test_a_photograph_of_a_real_person_is_refused(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate_image=[verdict(False, "real_person_photo")])
    image = await put_image(rig)
    s = await Story(rig).start({**SCRIPT, "image_key": image.key})
    assert s.state["refusal"]["code"] == "real_person_photo"
    assert "photograph of a real person" in s.state["refusal"]["message"]
    assert rig.sink.submitted == [] and s.rows.videos == []
    assert not await exists(rig, image.key)  # the picture is not kept


async def test_a_script_the_moderator_refuses_stops_before_any_work(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=[verdict(False, "fraud_or_impersonation")])
    image = await put_image(rig)
    s = await Story(rig).start({**SCRIPT, "image_key": image.key})
    assert s.state["refusal"]["code"] == "fraud_or_impersonation"
    assert rig.picture_checks() == [] and rig.sink.submitted == []


async def test_with_the_safeguards_off_nothing_is_checked_or_limited_and_no_voice_is_transcribed(
    tmp_path, ctx
):
    """ADR-0047: no moderation, no transcript of an uploaded voice, no daily limit."""
    rig = make_rig(
        tmp_path,
        moderate=[verdict(False, "hate")],
        moderate_image=[verdict(False, "real_person_photo")],
    )
    rig.switch(False)
    image, voice = await put_image(rig), await put_voice(rig)
    s = await Story(rig, quota=FixedQuota(3)).start(
        {"source": "audio", "image_key": image.key, "audio_key": voice.key}
    )
    assert rig.asked() == []
    assert [j.capability for j in rig.sink.submitted] == ["video.lipsync"]
    await s.clip()
    assert s.state["status"] == "done"


# ---- limits --------------------------------------------------------------------------------


async def test_the_daily_limit_is_checked_before_any_model_is_asked(tmp_path, ctx):
    rig = make_rig(tmp_path)
    image = await put_image(rig)
    s = await Story(rig, quota=FixedQuota(3)).start({**SCRIPT, "image_key": image.key})
    assert s.state["refusal"]["code"] == "quota_exceeded"
    assert "limit of 3 lip syncs" in s.state["refusal"]["message"]
    assert rig.asked() == [] and rig.sink.submitted == [] and not await exists(rig, image.key)


async def test_only_one_lip_sync_is_made_at_a_time(tmp_path, ctx):
    rig = make_rig(tmp_path)
    image = await put_image(rig)
    first = await Story(rig).start({**SCRIPT, "image_key": image.key})
    second_image = await put_image(rig)
    second = Story(rig)
    second.rows = first.rows
    second.graph = build_lipsync_graph(
        rig.caps, InMemorySaver(), first.rows, rig.uploads, FixedQuota(0)
    )
    other: Any = {"configurable": {"thread_id": "th-2"}}
    request: Any = {**SCRIPT, "image_key": second_image.key}
    s = await second.graph.ainvoke(request, other)
    assert s["refusal"]["code"] == "busy"


@pytest.mark.parametrize(
    "bad",
    [
        {"source": "video"},
        {"source": "script", "script": "  "},
        {"source": "script", "script": "x" * 1001, "language": "en-US", "gender": "female"},
        {"source": "script", "script": "Hi", "language": "xx", "gender": "female"},
        {"source": "audio", "audio_key": "uploads/missing.wav"},
    ],
)
async def test_bad_requests_are_refused_without_work(tmp_path, ctx, bad):
    rig = make_rig(tmp_path)
    image = await put_image(rig)
    s = await Story(rig).start({"image_key": image.key, **bad})
    assert s.state["status"] == "refused" and rig.sink.submitted == [] and s.rows.videos == []


async def test_a_missing_picture_is_asked_for_again(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).start({**SCRIPT, "image_key": "uploads/gone.png"})
    assert "upload your picture again" in s.state["refusal"]["message"]


# ---- failures ------------------------------------------------------------------------------


async def test_a_failed_clip_marks_the_row_and_keeps_nothing(tmp_path, ctx):
    rig = make_rig(tmp_path)
    image, voice = await put_image(rig), await put_voice(rig)
    rig.switch(False)
    s = await Story(rig).start({"source": "audio", "image_key": image.key, "audio_key": voice.key})
    with pytest.raises(JobFailed):
        await s.clip(status="failed")
    assert [(r.status, r.error) for r in s.rows.videos] == [
        ("failed", "The generation failed on the GPU.")
    ]
    assert not await exists(rig, image.key) and not await exists(rig, voice.key)


async def test_an_unreadable_clip_fails_the_run_so_it_can_be_retried(tmp_path, ctx):
    rig = make_rig(tmp_path)
    rig.switch(False)
    image, voice = await put_image(rig), await put_voice(rig)
    s = await Story(rig).start({"source": "audio", "image_key": image.key, "audio_key": voice.key})
    with pytest.raises(RunError) as e:
        await s.clip(data=b"not a video")
    assert e.value.code == "lipsync_failed" and e.value.retryable
    assert [r.status for r in s.rows.videos] == ["failed"]
