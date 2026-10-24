"""The worker loop: say it is here and what it lists, take one job at a time, run it, answer."""

import asyncio
import logging
from typing import Any

from wasifyai_platform_sdk import (
    EngineError,
    EngineJob,
    EngineOutcome,
    EngineQueue,
    EngineWorkerInfo,
    admin_wire,
    builder_wire,
    model3d_wire,
    speech_wire,
)
from wasifyai_platform_sdk.engine_jobs import sleep_or_stop

from wasifyai_engine_worker.handlers import run_job

log = logging.getLogger("wasifyai_engine_worker")

CANCEL_POLL_S = 2.0


class Worker:
    def __init__(
        self,
        queue: EngineQueue,
        engines: Any,
        storage: Any,
        name: str,
        job_timeout_s: float = 3600,
        heartbeat_s: float = 10,
    ):
        """`engines`: the speech engine, or a mapping of what this worker runs: `speech` (the speech
        engine) and `model3d` (the 3D service)."""
        self._queue = queue
        self._engines = engines
        self._storage = storage
        self.name = name
        self._timeout = job_timeout_s
        self._beat = heartbeat_s
        self._busy = False
        self.stop = asyncio.Event()

    @property
    def _speech(self) -> Any:
        return self._engines["speech"] if isinstance(self._engines, dict) else self._engines

    @property
    def _model3d(self) -> Any:
        return self._engines.get("model3d") if isinstance(self._engines, dict) else None

    @property
    def _builder(self) -> Any:
        return self._engines.get("builder") if isinstance(self._engines, dict) else None

    def info(self) -> EngineWorkerInfo:
        try:
            models = self._speech.models(None)
        except Exception:
            log.exception("the engine could not list its models")
            models = []
        kinds = list(speech_wire.KINDS)
        if isinstance(self._engines, dict) and "admin" in self._engines:
            kinds += admin_wire.KINDS
        components: dict[str, Any] = {}
        sidecar = getattr(self._speech, "lipsync_sidecar", None)
        if sidecar is not None:  # the lip sync engine is set up from the web like a model
            try:
                plan = sidecar.installer.plan()
                components[admin_wire.LIPSYNC_COMPONENT] = {
                    "installed": bool(sidecar.installed),
                    "supported": bool(plan["supported"]),
                    "bytes": int(plan["bytes"]),
                }
            except Exception:
                log.exception("the lip sync engine could not report its state")
        if (service := self._model3d) is not None:
            kinds += model3d_wire.KINDS
            try:
                ready = service.ready()
                components[model3d_wire.COMPONENT] = {
                    "ready": ready,
                    "problem": service.problem(),
                    "fit": service.fit() if ready else None,
                    "state": service.state(),
                }
            except Exception:
                log.exception("the 3D component could not report its state")
        if (builder := self._builder) is not None:
            kinds += builder_wire.KINDS
            try:
                ready = builder.ready()
                components[builder_wire.COMPONENT] = {
                    "ready": ready,
                    "problem": builder.problem(),
                    "fit": builder.fit() if ready else None,
                    "state": builder.state(),
                }
            except Exception:
                log.exception("Motion graphics could not report its state")
        return EngineWorkerInfo(
            id=self.name, kinds=kinds, models=models, components=components, busy=self._busy
        )

    async def _heartbeat(self) -> None:
        while not self.stop.is_set():
            try:
                await self._queue.register(self.info())
            except Exception:
                log.exception("could not tell the API this worker is here")
            if await sleep_or_stop(self.stop, self._beat):
                return

    async def _stop_component(self, job: EngineJob) -> None:
        """A cancelled job: give its process back (a 3D run is a program of its own)."""
        if job.kind.startswith("model3d.") and (service := self._model3d) is not None:
            await service.stop()
        # a Motion graphics render is a browser the sandbox ends itself when its task is cancelled

    async def _run(self, job: EngineJob) -> EngineOutcome:
        async def report(fraction: float, label: str) -> None:
            await self._queue.report(job.id, fraction, label)

        task = asyncio.ensure_future(
            asyncio.wait_for(
                run_job(self._engines, self._storage, job, self.name, report),
                timeout=self._timeout,
            )
        )
        while not task.done():
            await asyncio.wait({task}, timeout=CANCEL_POLL_S)
            if not task.done() and await self._queue.cancelled(job.id):
                task.cancel()
                await self._stop_component(job)
                await asyncio.gather(task, return_exceptions=True)
                return EngineOutcome(
                    id=job.id, ok=False, worker=self.name,
                    error=EngineError(code="cancelled", message="Stopped."),
                )  # fmt: skip
        try:
            return task.result()
        except TimeoutError:
            await self._stop_component(job)
            return EngineOutcome(
                id=job.id, ok=False, worker=self.name,
                error=EngineError(code="timeout", message="That took too long and was stopped."),
            )  # fmt: skip

    async def run_once(self, block_ms: int = 5000) -> bool:
        """Take and run one job. False when there was none."""
        claimed = await self._queue.claim(self.name, block_ms=block_ms)
        if claimed is None:
            return False
        stream_id, job = claimed
        log.info("job %s (%s) for %s", job.id, job.kind, job.tenant_id)
        if await self._queue.cancelled(job.id):  # stopped while it waited
            outcome = EngineOutcome(
                id=job.id, ok=False, worker=self.name,
                error=EngineError(code="cancelled", message="Stopped."),
            )  # fmt: skip
            await self._queue.finish(stream_id, outcome)
            return True
        self._busy = True
        try:
            await self._queue.register(self.info())  # the API sees it is busy now
            outcome = await self._run(job)
        finally:
            self._busy = False
        await self._queue.finish(stream_id, outcome)
        log.info("job %s %s in %.1fs", job.id, "done" if outcome.ok else "failed", outcome.seconds)
        return True

    async def run(self) -> None:
        beat = asyncio.create_task(self._heartbeat())
        try:
            while not self.stop.is_set():
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("the worker loop failed; trying again")
                    await sleep_or_stop(self.stop, 2)
        finally:
            beat.cancel()
            await asyncio.gather(beat, return_exceptions=True)
            await self._queue.leave(self.name)
