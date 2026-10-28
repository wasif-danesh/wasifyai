"""Speech for the web from engine workers (ADR-0087): a `SpeechEngine` run on another machine.

The voice product calls it as it calls the desktop's runtime or the hosted models. Each call
becomes an engine job (`wasifyai_platform_sdk.engine_jobs`): the inputs are put in the person's
own part of object storage, a worker (the desktop engine without the window) runs the job, and
the outputs are read back. What the web offers is what the live workers list as ready, so a
screen appears when a worker can do it."""

import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.config import get_stream_writer
from wasifyai_platform_sdk import (
    ConvertRequest,
    EngineJob,
    EngineQueue,
    EngineUnavailable,
    EngineWorkerInfo,
    LipSyncRequest,
    MusicEditRequest,
    MusicRequest,
    SeparateRequest,
    SpeechEditRequest,
    VoiceEngineError,
    VoiceModel,
    require_context,
    speech_wire,
)
from wasifyai_platform_sdk.engine_jobs import PLACE_LIMIT
from wasifyai_platform_sdk.storage import object_key

from wasifyai_api.engine_workers import WorkerDirectory, record_engine_seconds

log = logging.getLogger("wasifyai_api.remote_speech")

# how good a state is, when two workers list the same model
_RANK = {"ready": 0, "needs_runtime": 1, "can_install": 2, "not_available": 3}


PLACE_POLL_S = 2.0  # how often a waiting job's place in the queue is read


def waiting_words(place: int) -> str:
    """The step a screen shows while a speech waits for a worker."""
    if place <= 1:
        return "Next in line"
    ahead = place - 1
    return f"Waiting: {ahead} ahead of you" if ahead < PLACE_LIMIT else "Waiting in a long line"


def _rank(model: dict[str, Any]) -> int:
    return _RANK.get(str(model.get("state")), 9)


class RemoteLipSync:
    """What `/lipsync-engine` reports: whoever runs the worker sets it up, so nothing to install."""

    def __init__(self, engine: "RemoteSpeechEngine"):
        self._engine = engine

    def state(self) -> dict[str, Any]:
        ready = any(
            m.get("engine") == "sidecar" and m.get("state") == "ready"
            for m in self._engine.models(None)
        )
        return {
            "installed": ready, "source": "managed", "running": ready,
            "plan": {"supported": True, "platform": "worker", "commit": "", "bytes": 0, "uv": True},
            "install": {"state": "ready", "step": None, "message": "", "done_bytes": 0,
                        "total_bytes": 0},
        }  # fmt: skip


class RemoteSpeechEngine:
    def __init__(
        self,
        queue: EngineQueue,
        storage: Any,
        catalogue: dict[str, VoiceModel],
        timeout_s: float = 3600,
        directory: WorkerDirectory | None = None,
        usage: Any = None,
    ):
        self._usage = usage
        self._queue = queue
        self._storage = storage  # the raw `Storage` (keys carry the tenant prefix)
        self._catalogue = catalogue
        self._timeout = timeout_s
        self._directory = directory or WorkerDirectory(queue)
        self._owns_directory = directory is None
        self.lipsync_sidecar = RemoteLipSync(self)

    # ---- which workers are here and what they list ----------------------------------------

    @property
    def _workers(self) -> list[EngineWorkerInfo]:
        return self._directory.workers

    @_workers.setter
    def _workers(self, workers: list[EngineWorkerInfo]) -> None:
        self._directory.workers = workers

    async def refresh(self) -> None:
        await self._directory.refresh()

    def start(self) -> None:
        if self._owns_directory:  # a shared directory is started by whoever made it
            self._directory.start()

    async def close(self) -> None:
        if self._owns_directory:
            await self._directory.close()

    async def stop(self) -> bool:
        return True  # the workers hold the memory; they give it back themselves

    def state(self) -> dict[str, Any]:
        return {"hosted": True}  # nothing to set up from the web page

    # ---- what is offered ---------------------------------------------------------------------

    def models(self, task: str | None = None) -> list[dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for w in self._workers:
            for m in w.models:
                if m.get("id") not in self._catalogue:
                    continue  # a model this API has no descriptor for is not offered
                cur = best.get(m["id"])
                if cur is None or _rank(m) < _rank(cur):
                    best[m["id"]] = m
        out = [m for m in best.values() if not task or task in (m.get("tasks") or [])]
        return sorted(out, key=lambda m: str(m["id"]))

    def resolve(self, task: str, model_id: str | None) -> VoiceModel:
        listed = {m["id"]: m for m in self.models(task)}
        if model_id:
            m = listed.get(model_id)
            if m is None:
                raise VoiceEngineError(
                    "unknown_model", "That model is not one this service knows for this."
                )
        else:
            ready = [m for m in listed.values() if m.get("state") == "ready"]
            wanted = [m for m in ready if task in (m.get("recommended") or [])]
            m = (wanted or ready or [None])[0]  # type: ignore[assignment]
            if m is None:
                raise VoiceEngineError("no_model", "There is no model for this yet.")
        if m.get("state") != "ready":
            raise VoiceEngineError(
                "model_missing",
                f"{m.get('title', 'That model')} is not ready on the speech worker yet.",
            )
        return self._catalogue[m["id"]]

    # ---- the work ---------------------------------------------------------------------------

    async def _tell_place(self, job_id: str, kind: str) -> None:
        """While no worker has taken the job, tell the run how many are ahead (stage J3): the
        screens show it as the step, the assistant and agents read the `job_progress` event."""
        try:
            write = get_stream_writer()
        except Exception:
            return  # not inside a run: nobody to tell
        told: int | None = None
        while True:
            try:
                place = await self._queue.place(job_id)
            except Exception:
                return  # the place is a courtesy: the wait goes on without it
            if place is None:
                return
            if place != told:
                told = place
                write({"type": "node", "node": "queue", "status": "started",
                       "label": waiting_words(place)})  # fmt: skip
                write({"type": "job_progress", "data": {
                    "job_id": job_id, "capability": f"speech.{kind}", "status": "queued",
                    "queue_position": place,
                }})  # fmt: skip
            await asyncio.sleep(PLACE_POLL_S)

    async def _run(
        self,
        kind: str,
        model: VoiceModel,
        params: dict[str, Any],
        files: dict[str, bytes | Path] | None = None,
    ) -> tuple[dict[str, bytes], dict[str, Any]]:
        """Queue a job and wait for it: (the output files by name, the numbers and words)."""
        if not self._workers:
            raise VoiceEngineError(
                "engine_unavailable", "The speech worker is not running. Try again in a moment."
            )
        ctx = require_context()
        job_id = str(uuid4())
        prefix = object_key(ctx.tenant_id, ctx.product_id, ctx.user_id, "engine", job_id)
        keys: dict[str, str] = {}
        staged: list[str] = []
        try:
            for name, data in (files or {}).items():
                blob = data if isinstance(data, bytes) else await asyncio.to_thread(data.read_bytes)
                key = f"{prefix}/in/{name}"
                await self._storage.put(key, blob, "application/octet-stream")
                staged.append(key)
                keys[name] = key
            job = EngineJob(
                id=job_id, kind=kind, tenant_id=ctx.tenant_id, product_id=ctx.product_id,
                user_id=ctx.user_id, prefix=prefix, params={**params, "model_id": model.id},
                files=keys,
            )  # fmt: skip
            await self._queue.submit(job, timeout_s=self._timeout)
            watch = asyncio.create_task(self._tell_place(job_id, kind))
            try:
                outcome = await self._queue.wait(job_id, self._timeout)
            except asyncio.CancelledError:
                # Stop was pressed (or the run ended): tell the worker, so the work stops too. A
                # speech waits inside its run, so nothing would pick this job up again (stage J3).
                await asyncio.shield(self._queue.cancel(job_id))
                raise
            except EngineUnavailable:
                raise VoiceEngineError(
                    "engine_unavailable", "The speech worker took too long. Try again."
                ) from None
            finally:
                watch.cancel()
            await record_engine_seconds(self._usage, ctx, kind, outcome)
            if not outcome.ok:
                err = outcome.error
                raise VoiceEngineError(
                    err.code if err else "engine_failed",
                    err.message if err else "The speech worker could not do that.",
                )
            staged.extend(outcome.outputs.values())
            outputs = {name: await self._storage.get(key) for name, key in outcome.outputs.items()}
            return outputs, outcome.meta
        finally:
            for key in staged:
                try:
                    await self._storage.delete(key)
                except Exception:
                    log.warning("could not remove %s", key)

    async def speak(
        self, model: VoiceModel, text: str, voice: str | None, options: dict[str, Any],
        *, beside: bool = False,
    ):  # fmt: skip
        out, meta = await self._run(
            speech_wire.SPEAK, model,
            {"text": text, "voice": voice, "options": options, "beside": beside},
        )  # fmt: skip
        return speech_wire.speech_result(out["audio"], meta)

    async def design(self, model: VoiceModel, text: str, description: str, options: dict[str, Any]):
        out, meta = await self._run(
            speech_wire.DESIGN,
            model,
            {"text": text, "description": description, "options": options},
        )
        return speech_wire.speech_result(out["audio"], meta)

    async def clone(
        self, model: VoiceModel, text: str, reference: Path, reference_text: str | None,
        options: dict[str, Any],
    ):  # fmt: skip
        out, meta = await self._run(
            speech_wire.CLONE, model,
            {"text": text, "reference_text": reference_text, "options": options},
            {"reference": reference},
        )  # fmt: skip
        return speech_wire.speech_result(out["audio"], meta)

    async def music(self, model: VoiceModel, request: MusicRequest):
        out, meta = await self._run(
            speech_wire.MUSIC, model, {"request": speech_wire.request_json(request)}
        )
        return speech_wire.music_result(out["audio"], meta)

    async def music_edit(self, model: VoiceModel, request: MusicEditRequest, source: Path):
        out, meta = await self._run(
            speech_wire.MUSIC_EDIT, model, {"request": speech_wire.request_json(request)},
            {"source": source},
        )  # fmt: skip
        return speech_wire.music_result(out["audio"], meta)

    async def transcribe(
        self, model: VoiceModel, wav: bytes, options: dict[str, Any], *, beside: bool = False
    ):
        _, meta = await self._run(
            speech_wire.TRANSCRIBE, model, {"options": options, "beside": beside}, {"audio": wav}
        )
        return speech_wire.transcript_result(meta)

    async def separate(self, model: VoiceModel, request: SeparateRequest, source: Path):
        out, meta = await self._run(
            speech_wire.SEPARATE, model, {"request": speech_wire.request_json(request)},
            {"source": source},
        )  # fmt: skip
        wavs = [out[f"stem_{i}"] for i in range(len(meta["stems"]))]
        return speech_wire.separate_result(wavs, meta)

    async def convert(
        self, model: VoiceModel, request: ConvertRequest, source: Path, reference: Path
    ):
        out, meta = await self._run(
            speech_wire.CONVERT, model, {"request": speech_wire.request_json(request)},
            {"source": source, "reference": reference},
        )  # fmt: skip
        return speech_wire.speech_result(out["audio"], meta)

    async def speech_edit(self, model: VoiceModel, request: SpeechEditRequest, source: Path):
        out, meta = await self._run(
            speech_wire.SPEECH_EDIT, model, {"request": speech_wire.request_json(request)},
            {"source": source},
        )  # fmt: skip
        return speech_wire.speech_result(out["audio"], meta)

    async def lipsync(self, model: VoiceModel, request: LipSyncRequest, picture: Path, voice: Path):
        out, meta = await self._run(
            speech_wire.LIPSYNC, model, {"request": speech_wire.request_json(request)},
            {"picture": picture, "voice": voice},
        )  # fmt: skip
        return speech_wire.lipsync_result(out["video"], meta)
