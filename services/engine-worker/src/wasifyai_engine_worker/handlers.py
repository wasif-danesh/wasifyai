"""What each job kind does: fetch the inputs from storage, call the engine, put the outputs back.

A job never names a path on the worker: the engine's calls that take a `Path` get a file in a
temporary folder that is removed on every exit path. Every key a job names must be under the job's
own prefix (the person's), or the job is refused."""

import asyncio
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import (
    EngineError,
    EngineJob,
    EngineOutcome,
    VoiceEngineError,
    VoiceRequestError,
    speech_wire,
)

Storage = Any  # wasifyai_platform_sdk.Storage: get(key) / put(key, data, content_type)
Report = Callable[[float, str], Awaitable[None]]


class Refused(Exception):
    pass


class Work:
    """One job's inputs and outputs."""

    def __init__(self, job: EngineJob, storage: Storage, folder: Path):
        self.job = job
        self._storage = storage
        self._folder = folder
        self.outputs: dict[str, str] = {}

    def _checked(self, key: str) -> str:
        if not key.startswith(self.job.prefix) or ".." in key:
            raise Refused("That file is not part of this job.")
        return key

    async def file(self, name: str) -> Path:
        """An input as a file on this machine."""
        key = self.job.files.get(name)
        if key is None:
            raise Refused(f"The job has no {name}.")
        path = self._folder / name
        data = await self._storage.get(self._checked(key))
        await asyncio.to_thread(path.write_bytes, data)
        return path

    async def read(self, name: str) -> bytes:
        return await asyncio.to_thread((await self.file(name)).read_bytes)

    async def put(self, name: str, data: bytes, content_type: str) -> None:
        key = self._checked(f"{self.job.prefix}/out/{name}")
        await self._storage.put(key, data, content_type)
        self.outputs[name] = key


Handler = Callable[[Any, Work], Awaitable[dict[str, Any]]]


def _model(engine: Any, kind: str, p: dict[str, Any]) -> Any:
    return engine.resolve(speech_wire.TASK[kind], p.get("model_id"))


async def _speak(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.speak(
        _model(engine, speech_wire.SPEAK, p), p["text"], p.get("voice"), p.get("options") or {},
        beside=bool(p.get("beside")),
    )  # fmt: skip
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.speech_meta(r)


async def _design(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.design(
        _model(engine, speech_wire.DESIGN, p), p["text"], p["description"], p.get("options") or {}
    )
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.speech_meta(r)


async def _clone(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.clone(
        _model(engine, speech_wire.CLONE, p), p["text"], await w.file("reference"),
        p.get("reference_text"), p.get("options") or {},
    )  # fmt: skip
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.speech_meta(r)


async def _music(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.music(
        _model(engine, speech_wire.MUSIC, p), speech_wire.music_request(p["request"])
    )
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.music_meta(r)


async def _music_edit(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.music_edit(
        _model(engine, speech_wire.MUSIC_EDIT, p),
        speech_wire.music_edit_request(p["request"]),
        await w.file("source"),
    )
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.music_meta(r)


async def _transcribe(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.transcribe(
        _model(engine, speech_wire.TRANSCRIBE, p), await w.read("audio"), p.get("options") or {},
        beside=bool(p.get("beside")),
    )  # fmt: skip
    return speech_wire.transcript_meta(r)


async def _separate(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.separate(
        _model(engine, speech_wire.SEPARATE, p),
        speech_wire.separate_request(p["request"]),
        await w.file("source"),
    )
    for i, stem in enumerate(r.stems):
        await w.put(f"stem_{i}", stem.wav, "audio/wav")
    return speech_wire.separate_meta(r)


async def _convert(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.convert(
        _model(engine, speech_wire.CONVERT, p),
        speech_wire.convert_request(p["request"]),
        await w.file("source"),
        await w.file("reference"),
    )
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.speech_meta(r)


async def _speech_edit(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.speech_edit(
        _model(engine, speech_wire.SPEECH_EDIT, p),
        speech_wire.speech_edit_request(p["request"]),
        await w.file("source"),
    )
    await w.put("audio", r.wav, "audio/wav")
    return speech_wire.speech_meta(r)


async def _lipsync(engine: Any, w: Work) -> dict[str, Any]:
    p = w.job.params
    r = await engine.lipsync(
        _model(engine, speech_wire.LIPSYNC, p),
        speech_wire.lipsync_request(p["request"]),
        await w.file("picture"),
        await w.file("voice"),
    )
    await w.put("video", r.mp4, "video/mp4")
    return speech_wire.lipsync_meta(r)


HANDLERS: dict[str, Handler] = {
    speech_wire.SPEAK: _speak,
    speech_wire.DESIGN: _design,
    speech_wire.CLONE: _clone,
    speech_wire.MUSIC: _music,
    speech_wire.MUSIC_EDIT: _music_edit,
    speech_wire.TRANSCRIBE: _transcribe,
    speech_wire.SEPARATE: _separate,
    speech_wire.CONVERT: _convert,
    speech_wire.SPEECH_EDIT: _speech_edit,
    speech_wire.LIPSYNC: _lipsync,
}


async def run_job(engine: Any, storage: Storage, job: EngineJob, worker: str) -> EngineOutcome:
    """Run one job to an outcome. Nothing escapes: a failure is an outcome with a safe message."""
    import logging
    import time

    log = logging.getLogger("wasifyai_engine_worker")
    t0 = time.monotonic()
    handler = HANDLERS.get(job.kind)
    if handler is None:
        return EngineOutcome(
            id=job.id, ok=False, worker=worker,
            error=EngineError(code="unknown_job", message="This worker cannot do that."),
        )  # fmt: skip
    try:
        with tempfile.TemporaryDirectory(prefix="wasifyai-engine-") as tmp:
            work = Work(job, storage, Path(tmp))
            meta = await handler(engine, work)
            return EngineOutcome(
                id=job.id, ok=True, outputs=work.outputs, meta=meta, worker=worker,
                seconds=time.monotonic() - t0,
            )  # fmt: skip
    except (VoiceEngineError, VoiceRequestError) as e:
        return EngineOutcome(
            id=job.id, ok=False, worker=worker, seconds=time.monotonic() - t0,
            error=EngineError(code=e.code, message=str(e)),
        )  # fmt: skip
    except Refused as e:
        return EngineOutcome(
            id=job.id, ok=False, worker=worker,
            error=EngineError(code="refused", message=str(e)),
        )  # fmt: skip
    except Exception:
        log.exception("job %s (%s) failed", job.id, job.kind)
        return EngineOutcome(
            id=job.id, ok=False, worker=worker, seconds=time.monotonic() - t0,
            error=EngineError(code="engine_failed", message="The speech worker could not do that."),
        )  # fmt: skip
