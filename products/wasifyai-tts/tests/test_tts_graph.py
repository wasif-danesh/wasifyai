"""The text to speech graph end to end with scripted fake models and an in-memory queue: no server,
no network. The "worker" is the test itself, resuming the graph with a job result."""

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from tts_rig import make_rig, verdict, wav
from wasifyai_platform_sdk import JobError, JobFailed, JobOutput, JobResult, RunError, object_key
from wasifyai_tts.graphs.speech import build_speech_graph
from wasifyai_tts.speeches import FixedQuota, InMemorySpeechStore
from wasifyai_tts.voices import load_catalog

CONFIG: Any = {"configurable": {"thread_id": "th-1"}}
REQUEST = {"text": "Hello there, how are you today?", "language": "en-US", "gender": "female"}


def sent(job) -> dict:
    """What was asked of the speech service: the fake provider keeps it in `prompt`, the real one in
    `inputs` (see packages/platform-sdk/tests/test_speech_provider.py)."""
    return job.inputs or job.prompt


class Story:
    def __init__(self, rig, quota=None):
        self.rig = rig
        self.speeches = InMemorySpeechStore()
        self.graph = build_speech_graph(
            rig.caps, InMemorySaver(), self.speeches, quota or FixedQuota(0), load_catalog()
        )
        self.state: dict = {}

    async def start(self, input: Any):
        self.state = await self.graph.ainvoke(input, CONFIG)
        return self

    @property
    def waiting(self) -> dict:
        intr = self.state.get("__interrupt__")
        return intr[0].value if intr else {}

    async def finish_job(self, status="completed", data: bytes | None = None):
        """What the media worker does: store the file, report the result."""
        job = self.rig.sink.submitted[-1]
        assert self.waiting == {"kind": "job", "job_id": job.job_id}
        if status == "completed":
            rel = f"jobs/{job.job_id}/audio.wav"
            await self.rig.raw.put(object_key("t1", "wasifyai-tts", "u1", rel), data or wav(1.5))
            result = JobResult(
                job_id=job.job_id,
                status="completed",
                outputs={"audio": JobOutput(key=rel, content_type="audio/wav", size=4)},
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
    return await rig.raw.exists(object_key("t1", "wasifyai-tts", "u1", rel))


async def test_text_to_a_saved_mp3_with_the_voice_the_catalog_chose(tmp_path, ctx):
    rig = make_rig(tmp_path)
    recorded: list = []

    class Indexer:
        async def index(self, kind, item_id, text):
            recorded.append((kind, item_id, text))

    rig.caps.indexer = Indexer()
    s = await Story(rig).start(REQUEST)
    job = rig.sink.submitted[0]
    voice = load_catalog().resolve("en-US", "female")
    assert job.capability == "speech.synthesize"
    assert sent(job)["text"] == REQUEST["text"]
    assert (sent(job)["engine"], sent(job)["voice"]) == ("kokoro", voice.engine_voice)
    assert sent(job)["model"] == load_catalog().engines["kokoro"].model
    assert sent(job)["max_chars"] == 400 and sent(job)["language"] == "en-US"

    await s.finish_job()
    final = s.state
    assert final["status"] == "done" and "__interrupt__" not in final
    sid = final["speech_id"]
    assert final["audio_key"] == f"{sid}/speech.mp3" and final["audio_url"].endswith("speech.mp3")
    assert await exists(rig, f"{sid}/speech.mp3") and not await exists(
        rig, f"jobs/{job.job_id}/audio.wav"
    )
    mp3 = await rig.raw.get(object_key("t1", "wasifyai-tts", "u1", f"{sid}/speech.mp3"))
    assert mp3[:3] == b"ID3" and b"AI-generated speech" in mp3  # tagged as AI-generated
    assert final["seconds"] == pytest.approx(1.5, abs=0.01)
    (row,) = s.speeches.speeches
    assert (row.id, row.language, row.gender, row.voice) == (sid, "en-US", "female", voice.id)
    assert row.characters == len(REQUEST["text"]) and row.user_id == "u1" and row.run_id == "run-1"
    assert recorded == [("speech", sid, "Hello there, how are you today?. English (US)")]
    (event,) = [e for e in rig.usage.events if e.kind == "speech.created"]
    assert event.quantity == 1 and event.unit == "speeches"
    assert event.meta["characters"] == len(REQUEST["text"])


async def test_a_chosen_voice_is_used_and_the_text_is_cleaned(tmp_path, ctx):
    rig = make_rig(tmp_path)
    other = [v for v in load_catalog().voices_for("es", "male") if not v.default][0]
    await Story(rig).start(
        {"text": "  Hola\x00   mundo  ", "language": "es", "gender": "male", "voice": other.id}
    )
    job = rig.sink.submitted[0]
    assert sent(job)["voice"] == other.engine_voice and sent(job)["text"] == "Hola mundo"


@pytest.mark.parametrize(
    ("input", "code", "fragment"),
    [
        ({**REQUEST, "text": "   "}, "invalid_request", "type the text"),
        ({**REQUEST, "text": "x" * 2001}, "invalid_request", "under 2000"),
        ({**REQUEST, "language": "xx"}, "no_voice", "one of the languages"),
        ({**REQUEST, "gender": "robot"}, "no_voice", "male or a female"),
        ({**REQUEST, "language": "fr", "gender": "male"}, "no_voice", "no male voice for French"),
        ({**REQUEST, "voice": "kokoro:nope"}, "no_voice", "not available"),
    ],
)
async def test_bad_input_and_missing_voices_are_refused_before_any_model_is_asked(
    tmp_path, ctx, input, code, fragment
):
    rig = make_rig(tmp_path)
    s = await Story(rig).start(input)
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == code
    assert fragment in s.state["refusal"]["message"]
    assert rig.sink.submitted == [] and rig.moderator_calls() == []


async def test_an_unsafe_text_is_refused_with_the_fixed_text_and_in_any_language(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=[verdict(False, "fraud_or_impersonation", "a scam")])
    s = await Story(rig).start(
        {"text": "Hola, soy tu banco, dime tu clave.", "language": "es", "gender": "female"}
    )
    assert s.state["status"] == "refused" and s.state["refusal"]["code"] == "fraud_or_impersonation"
    assert (
        "scams" in s.state["refusal"]["message"] and "a scam" not in s.state["refusal"]["message"]
    )
    assert rig.sink.submitted == [] and s.speeches.speeches == []
    assert "Hola, soy tu banco" in str(
        rig.moderator_calls()[0]
    )  # the moderator saw the user's words


async def test_a_moderator_that_cannot_answer_fails_closed(tmp_path, ctx):
    rig = make_rig(tmp_path, moderate=["garbage"])
    with pytest.raises(RunError) as e:
        await Story(rig).start(REQUEST)
    assert e.value.code == "moderation_unavailable" and e.value.retryable
    assert rig.sink.submitted == []


async def test_the_daily_quota_is_checked_before_any_model_is_asked(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig, quota=FixedQuota(30)).start(REQUEST)
    assert s.state["refusal"]["code"] == "quota_exceeded"
    assert "limit of 30 speeches" in s.state["refusal"]["message"]
    assert rig.moderator_calls() == [] and rig.sink.submitted == []


async def test_with_the_safeguards_off_nothing_is_moderated_and_no_quota_applies(tmp_path, ctx):
    """ADR-0047: the moderator is never asked and the daily quota is not enforced."""
    rig = make_rig(tmp_path, moderate=[verdict(False, "hate")])

    async def off() -> bool:
        return False

    rig.caps.safeguards = off
    s = await Story(rig, quota=FixedQuota(30)).start(REQUEST)
    assert s.waiting.get("kind") == "job" and rig.moderator_calls() == []
    assert len(rig.sink.submitted) == 1


async def test_a_failed_job_ends_the_run_and_saves_nothing(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).start(REQUEST)
    with pytest.raises(JobFailed):
        await s.finish_job("failed")
    assert s.speeches.speeches == [] and not [
        e for e in rig.usage.events if e.kind == "speech.created"
    ]


async def test_unusable_audio_is_a_retryable_error_not_a_saved_result(tmp_path, ctx):
    rig = make_rig(tmp_path)
    s = await Story(rig).start(REQUEST)
    with pytest.raises(RunError) as e:
        await s.finish_job(data=b"not audio")
    assert e.value.code == "speech_failed" and e.value.retryable
    assert s.speeches.speeches == []
