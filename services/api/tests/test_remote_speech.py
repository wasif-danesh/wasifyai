"""The web's speech from engine workers (ADR-0087): the API's `RemoteSpeechEngine` and the worker's
handlers on one wire, with a fake queue that runs each job on the worker's own code at once."""

from pathlib import Path

import pytest
from wasifyai_api.desktop_models import load_catalogue
from wasifyai_api.remote_speech import RemoteSpeechEngine
from wasifyai_engine_worker.handlers import run_job
from wasifyai_platform_sdk import (
    ConvertRequest,
    EngineJob,
    EngineWorkerInfo,
    MusicEditRequest,
    MusicRequest,
    MusicResult,
    RunContext,
    SeparateRequest,
    SeparateResult,
    SpeechResult,
    Stem,
    TranscriptResult,
    TranscriptSegment,
    VoiceEngineError,
    memory_storage,
    reset_context,
    set_context,
    speech_wire,
)

PRODUCTS = Path(__file__).resolve().parents[3] / "products"
CATALOGUE = {
    e.id: e.voice for e in load_catalogue(PRODUCTS, ["wasifyai-voice"]) if e.voice is not None
}


class WorkerEngine:
    """What the worker's engine does, minimal: the real runtime needs models."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve(self, task, model_id):
        return CATALOGUE[model_id]

    async def speak(self, model, text, voice, options, *, beside=False):
        self.calls.append("speak")
        return SpeechResult(b"RIFF" + text.encode(), 24000, 1.0, model.id, voice, 0.1, 0.5)

    async def convert(self, model, request, source: Path, reference: Path):
        self.calls.append("convert")
        data = source.read_bytes() + b"+" + reference.read_bytes()  # noqa: ASYNC240
        return SpeechResult(data, 16000, 2.0, model.id, None, 0.0, 1.0)

    async def music(self, model, request: MusicRequest):
        self.calls.append("music")
        return MusicResult(b"song", 44100, request.duration, model.id, request.seed, 0.0, 3.0)

    async def music_edit(self, model, request: MusicEditRequest, source: Path):
        self.calls.append(f"edit:{request.ranges}")
        return MusicResult(b"edited", 44100, 5.0, model.id, None, 0.0, 1.0)

    async def transcribe(self, model, wav, options, *, beside=False):
        seg = (TranscriptSegment(0.0, 1.0, wav.decode()),)
        return TranscriptResult(wav.decode(), seg, 1.0, model.id, 0.2)

    async def separate(self, model, request: SeparateRequest, source: Path):
        return SeparateResult(
            (Stem("a", b"1", 44100, 1.0), Stem("b", b"2", 44100, 1.0)), model.id, 0.0, 1.0
        )


class InlineQueue:
    """The queue and the worker in one: a submitted job is run by the worker's code on the spot."""

    def __init__(self, storage, engine, workers: list[EngineWorkerInfo]):
        self.storage, self.engine, self._workers = storage, engine, workers
        self.jobs: list[EngineJob] = []
        self.done: dict[str, object] = {}

    async def submit(self, job):
        self.jobs.append(job)
        self.done[job.id] = await run_job(self.engine, self.storage, job, "w1")

    async def wait(self, job_id, timeout_s, on_progress=None):
        return self.done.pop(job_id)

    async def workers(self):
        return self._workers


def worker_listing(*models: tuple[str, str]) -> EngineWorkerInfo:
    rows = []
    for model_id, state in models:
        m = CATALOGUE[model_id]
        rows.append({**m.public(), "state": state})
    return EngineWorkerInfo(id="w1", kinds=speech_wire.KINDS, models=rows)


@pytest.fixture
def ctx():
    token = set_context(RunContext("t1", "wasifyai-voice", "u1"))
    yield
    reset_context(token)


async def make(*models: tuple[str, str]):
    storage = memory_storage()
    engine = WorkerEngine()
    queue = InlineQueue(storage, engine, [worker_listing(*models)])
    remote = RemoteSpeechEngine(queue, storage, CATALOGUE)  # type: ignore[arg-type]
    remote._workers = await queue.workers()  # noqa: SLF001
    return remote, queue, storage, engine


async def test_it_offers_what_a_live_worker_lists_and_nothing_when_none_is_running():
    remote, *_ = await make(("kokoro-82m", "ready"), ("ace-step-1.5-turbo", "can_install"))
    offered = {m["id"]: m["state"] for m in remote.models()}
    assert offered == {"kokoro-82m": "ready", "ace-step-1.5-turbo": "can_install"}
    assert [m["id"] for m in remote.models("speak")] == ["kokoro-82m"]
    remote._workers = []  # noqa: SLF001
    assert remote.models() == []


def test_resolve_names_the_problem_in_words():
    storage = memory_storage()
    remote = RemoteSpeechEngine(InlineQueue(storage, WorkerEngine(), []), storage, CATALOGUE)  # type: ignore[arg-type]
    with pytest.raises(VoiceEngineError) as e:
        remote.resolve("speak", None)
    assert e.value.code == "no_model"


async def test_resolve_picks_the_ready_recommended_model_and_refuses_one_that_is_not_ready():
    remote, *_ = await make(("kokoro-82m", "ready"), ("ace-step-1.5-turbo", "can_install"))
    assert remote.resolve("speak", None).id == "kokoro-82m"
    with pytest.raises(VoiceEngineError) as e:
        remote.resolve("music", "ace-step-1.5-turbo")
    assert e.value.code == "model_missing"
    with pytest.raises(VoiceEngineError) as e:
        remote.resolve("speak", "no-such-model")
    assert e.value.code == "unknown_model"


async def test_speaking_goes_through_the_worker_and_back_and_leaves_no_files(ctx):
    remote, queue, storage, engine = await make(("kokoro-82m", "ready"))
    model = remote.resolve("speak", None)
    result = await remote.speak(model, "hello", "nova", {"speed": 1.0})
    assert result.wav == b"RIFFhello" and result.voice == "nova" and result.sample_rate == 24000
    assert engine.calls == ["speak"]
    job = queue.jobs[0]
    assert job.prefix.startswith("t1/wasifyai-voice/u1/")  # the person's own folder
    assert await storage.list(job.prefix) == []  # inputs and outputs are removed


async def test_inputs_are_staged_and_outputs_decoded(ctx, tmp_path):
    remote, _, _, _ = await make(("tone-color-vc", "ready"))
    src, ref = tmp_path / "s.wav", tmp_path / "r.wav"
    src.write_bytes(b"SRC")
    ref.write_bytes(b"REF")
    model = CATALOGUE["tone-color-vc"]
    req = ConvertRequest(options={}, seed=None, source_seconds=2.0)
    out = await remote.convert(model, req, src, ref)
    assert out.wav == b"SRC+REF" and out.sample_rate == 16000


async def test_tuples_survive_the_json_trip_and_stems_come_back_named(ctx, tmp_path):
    remote, _, _, engine = await make(("ace-step-1.5-turbo", "ready"), ("htdemucs", "ready"))
    src = tmp_path / "s.wav"
    src.write_bytes(b"S")
    edit = MusicEditRequest(
        action="repaint", description="d", source_seconds=10.0, ranges=((1.0, 2.0),),
        strength=None, extend_s=None, options={}, seed=None,
    )  # fmt: skip
    await remote.music_edit(CATALOGUE["ace-step-1.5-turbo"], edit, src)
    assert engine.calls == ["edit:((1.0, 2.0),)"]
    stems = await remote.separate(
        CATALOGUE["htdemucs"], SeparateRequest(options={}, source_seconds=1.0), src
    )
    assert [(s.name, s.wav) for s in stems.stems] == [("a", b"1"), ("b", b"2")]


async def test_a_refusal_keeps_its_code_and_an_empty_worker_list_is_a_clear_error(ctx):
    remote, *_ = await make(("kokoro-82m", "ready"))
    with pytest.raises(VoiceEngineError) as e:  # the fake worker has no `design`
        await remote.design(CATALOGUE["kokoro-82m"], "x", "a calm voice", {})
    assert e.value.code == "engine_failed"
    remote._workers = []  # noqa: SLF001
    with pytest.raises(VoiceEngineError) as e:
        await remote.speak(CATALOGUE["kokoro-82m"], "x", None, {})
    assert e.value.code == "engine_unavailable"


async def test_the_lip_sync_state_says_installed_only_when_a_worker_has_it_ready():
    remote, *_ = await make(("kokoro-82m", "ready"))
    assert remote.lipsync_sidecar.state()["installed"] is False
