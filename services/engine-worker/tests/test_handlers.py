"""The engine worker's job handlers, with a fake engine and memory storage."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from wasifyai_engine_worker.admin import AdminComponent
from wasifyai_engine_worker.handlers import run_job
from wasifyai_platform_sdk import (
    EngineJob,
    LipSyncResult,
    MusicResult,
    SeparateResult,
    SpeechResult,
    Stem,
    TranscriptResult,
    TranscriptSegment,
    VoiceEngineError,
    admin_wire,
    memory_storage,
    speech_wire,
)

PREFIX = "t1/wasifyai-voice/u1/engine/j1"


class FakeEngine:
    def __init__(self) -> None:
        self.seen: dict[str, Any] = {}

    def resolve(self, task: str, model_id: str | None) -> str:
        if model_id == "missing":
            raise VoiceEngineError("model_missing", "That model is not on this computer yet.")
        return f"{task}:{model_id}"

    async def speak(self, model, text, voice, options, *, beside=False):
        self.seen["speak"] = (model, text, voice, options, beside)
        return SpeechResult(b"RIFFspeech", 24000, 1.5, "m", voice, 0.5, 1.0)

    async def convert(self, model, request, source: Path, reference: Path):
        self.seen["convert"] = (request, source.read_bytes(), reference.read_bytes())  # noqa: ASYNC240
        return SpeechResult(b"RIFFconv", 24000, 2.0, "m", None, 0.0, 1.0)

    async def music(self, model, request):
        self.seen["music"] = request
        return MusicResult(b"RIFFsong", 44100, 30.0, "m", 7, 1.0, 20.0)

    async def transcribe(self, model, wav, options, *, beside=False):
        self.seen["transcribe"] = wav
        seg = (TranscriptSegment(0.0, 1.0, "hello"),)
        return TranscriptResult("hello", seg, 1.0, "m", 0.4)

    async def separate(self, model, request, source: Path):
        return SeparateResult(
            (Stem("vocals", b"v", 44100, 3.0), Stem("drums", b"d", 44100, 3.0)), "m", 0.0, 2.0
        )

    async def lipsync(self, model, request, picture: Path, voice: Path):
        return LipSyncResult(b"mp4", 3.0, 25, 512, 512, "m", 1.0, 9.0)


def job(kind: str, params: dict[str, Any] | None = None, files: dict[str, str] | None = None):
    return EngineJob(
        id="j1", kind=kind, tenant_id="t1", product_id="wasifyai-voice", user_id="u1",
        prefix=PREFIX, params={"model_id": "m", **(params or {})}, files=files or {},
    )  # fmt: skip


async def test_speak_puts_the_audio_in_the_persons_folder_and_returns_the_numbers():
    storage, engine = memory_storage(), FakeEngine()
    out = await run_job(
        engine, storage, job(speech_wire.SPEAK, {"text": "hi", "voice": "nova", "options": {}}), "w"
    )
    assert out.ok and out.outputs == {"audio": f"{PREFIX}/out/audio"}
    assert await storage.get(out.outputs["audio"]) == b"RIFFspeech"
    assert out.meta["sample_rate"] == 24000 and "wav" not in out.meta
    assert engine.seen["speak"][:3] == ("speak:m", "hi", "nova")


async def test_files_arrive_as_paths_and_stems_come_back_in_order():
    storage, engine = memory_storage(), FakeEngine()
    await storage.put(f"{PREFIX}/in/source", b"SRC")
    await storage.put(f"{PREFIX}/in/reference", b"REF")
    req = {"options": {}, "seed": None, "source_seconds": 2.0}
    out = await run_job(
        engine, storage,
        job(speech_wire.CONVERT, {"request": req},
            {"source": f"{PREFIX}/in/source", "reference": f"{PREFIX}/in/reference"}),
        "w",
    )  # fmt: skip
    assert out.ok and engine.seen["convert"][1:] == (b"SRC", b"REF")
    sep = await run_job(
        engine, storage,
        job(speech_wire.SEPARATE, {"request": {"options": {}, "source_seconds": 3.0}},
            {"source": f"{PREFIX}/in/source"}),
        "w",
    )  # fmt: skip
    assert sep.ok and set(sep.outputs) == {"stem_0", "stem_1"}
    assert [s["name"] for s in sep.meta["stems"]] == ["vocals", "drums"]


async def test_music_and_transcript_and_lipsync_results_round_trip():
    storage, engine = memory_storage(), FakeEngine()
    req = {"mode": "song", "description": "d", "lyrics": "", "instrumental": True, "duration": 30.0,
           "options": {}, "seed": 7}  # fmt: skip
    song = await run_job(engine, storage, job(speech_wire.MUSIC, {"request": req}), "w")
    assert song.ok and song.meta["seed"] == 7
    await storage.put(f"{PREFIX}/in/audio", b"WAV")
    text = await run_job(
        engine, storage, job(speech_wire.TRANSCRIBE, {}, {"audio": f"{PREFIX}/in/audio"}), "w"
    )
    assert text.ok and speech_wire.transcript_result(text.meta).segments[0].text == "hello"
    await storage.put(f"{PREFIX}/in/picture", b"P")
    await storage.put(f"{PREFIX}/in/voice", b"V")
    lips = {
        "consent": {"picture": "own", "voice": "own"},
        "fps": 25,
        "voice_seconds": 3.0,
        "mark": "m",
    }
    clip = await run_job(
        engine, storage,
        job(speech_wire.LIPSYNC, {"request": lips},
            {"picture": f"{PREFIX}/in/picture", "voice": f"{PREFIX}/in/voice"}),
        "w",
    )  # fmt: skip
    assert clip.ok and await storage.get(clip.outputs["video"]) == b"mp4"


async def test_an_engine_refusal_is_an_outcome_with_its_own_code_and_words():
    out = await run_job(
        FakeEngine(),
        memory_storage(),
        job(speech_wire.SPEAK, {"text": "x", "model_id": "missing"}),
        "w",
    )
    assert not out.ok and out.error and out.error.code == "model_missing"
    assert "not on this computer" in out.error.message


@pytest.mark.parametrize("key", ["other-tenant/secret", f"{PREFIX}/../x"])
async def test_a_key_outside_the_jobs_own_prefix_is_refused(key):
    storage = memory_storage()
    await storage.put("other-tenant/secret", b"S")
    out = await run_job(
        FakeEngine(), storage,
        job(speech_wire.TRANSCRIBE, {}, {"audio": key}), "w",
    )  # fmt: skip
    assert not out.ok and out.error and out.error.code == "refused"


async def test_an_unknown_kind_and_a_crash_do_not_leak_details():
    unknown = await run_job(FakeEngine(), memory_storage(), job("speech.nope"), "w")
    assert unknown.error and unknown.error.code == "unknown_job"

    class Broken(FakeEngine):
        async def speak(self, *a, **k):
            raise RuntimeError("/Users/someone/secret/path exploded")

    out = await run_job(Broken(), memory_storage(), job(speech_wire.SPEAK, {"text": "x"}), "w")
    assert out.error and out.error.code == "engine_failed" and "secret" not in out.error.message


# ---- admin jobs: getting a model onto the worker (ADR-0087, P5) -------------------------------


class _Downloads:
    def __init__(self, ends: str) -> None:
        self.ends = ends
        self.started: list[tuple[str, list[str]]] = []
        self.cancelled: list[str] = []

    def start(self, entry, files, models_dir):
        d = SimpleNamespace(
            id="d1", status="running", bytes_done=0, bytes_total=10, current="m.bin", error=""
        )
        self.started.append((entry.id, [f.name for f in files]))

        async def finish() -> None:
            await asyncio.sleep(0.01)
            d.bytes_done, d.status = 10, self.ends
            d.error = "No space left." if self.ends == "failed" else ""

        asyncio.get_running_loop().create_task(finish())
        return d

    def cancel(self, download_id: str) -> bool:
        self.cancelled.append(download_id)
        return True


class _Catalogue:
    def __init__(self, entries: dict[str, Any]) -> None:
        self._entries = entries

    def get(self, key: str) -> Any:
        return self._entries.get(key)


class _Speech:
    """The speech engine's model service, as far as the admin component uses it."""

    def __init__(self, ends: str = "done", have: bool = False) -> None:
        file = SimpleNamespace(name="m.bin", size=10)
        entry = SimpleNamespace(
            id="voxcpm2", files=[file], source="huggingface.co/x", voice=object()
        )
        self.downloads = _Downloads(ends)
        self.models_dir = Path("/nowhere")
        self.catalogue = _Catalogue(
            {"voxcpm2": entry, "ocr": SimpleNamespace(id="ocr", files=[], voice=None)}
        )
        self.models_service = self
        self.lipsync_sidecar = None
        self._have = have

    def locate(self, file):
        return Path("/here") if self._have else None


def _job(kind: str, **params: Any) -> EngineJob:
    return EngineJob(
        kind=kind, tenant_id="t1", product_id="wasifyai-voice", user_id="u1", prefix=PREFIX,
        params=params,
    )  # fmt: skip


def _engines(speech: _Speech) -> dict[str, Any]:
    return {"speech": speech, "admin": AdminComponent(speech, poll_s=0.005)}


@pytest.mark.asyncio
async def test_a_model_is_fetched_by_a_job_and_its_progress_is_told():
    speech = _Speech()
    told: list[tuple[float, str]] = []

    async def report(f: float, label: str) -> None:
        told.append((f, label))

    job = _job(admin_wire.FETCH_MODEL, model_id="voxcpm2")
    out = await run_job(_engines(speech), memory_storage(), job, "w1", report)
    assert out.ok and out.meta["bytes"] == 10 and out.meta["already"] is False
    assert speech.downloads.started == [("voxcpm2", ["m.bin"])]
    assert told and told[0][1] == "Downloading m.bin"


@pytest.mark.asyncio
async def test_a_failed_download_comes_back_as_words():
    job = _job(admin_wire.FETCH_MODEL, model_id="voxcpm2")
    out = await run_job(_engines(_Speech("failed")), memory_storage(), job, "w1")
    assert not out.ok and out.error and out.error.message == "No space left."


@pytest.mark.asyncio
async def test_what_is_here_is_not_fetched_again_and_what_is_not_a_model_is_refused():
    here = _Speech(have=True)
    job = _job(admin_wire.FETCH_MODEL, model_id="voxcpm2")
    again = await run_job(_engines(here), memory_storage(), job, "w1")
    assert again.ok and again.meta["already"] is True and here.downloads.started == []
    other = _job(admin_wire.FETCH_MODEL, model_id="ocr")
    unknown = await run_job(_engines(here), memory_storage(), other, "w1")
    assert not unknown.ok and unknown.error and unknown.error.code == "unknown_model"
    engine = _job(admin_wire.FETCH_ENGINE, name="rm-rf")
    refused = await run_job(_engines(here), memory_storage(), engine, "w1")
    assert not refused.ok and refused.error and refused.error.code == "unknown_engine"
