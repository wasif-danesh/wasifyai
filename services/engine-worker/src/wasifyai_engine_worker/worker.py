"""The worker loop: say it is here and what it lists, take one job at a time, run it, answer."""

import asyncio
import logging
from typing import Any

from wasifyai_platform_sdk import (
    EngineError,
    EngineOutcome,
    EngineQueue,
    EngineWorkerInfo,
    speech_wire,
)
from wasifyai_platform_sdk.engine_jobs import sleep_or_stop

from wasifyai_engine_worker.handlers import run_job

log = logging.getLogger("wasifyai_engine_worker")


class Worker:
    def __init__(
        self,
        queue: EngineQueue,
        engine: Any,
        storage: Any,
        name: str,
        job_timeout_s: float = 3600,
        heartbeat_s: float = 10,
    ):
        self._queue = queue
        self._engine = engine
        self._storage = storage
        self.name = name
        self._timeout = job_timeout_s
        self._beat = heartbeat_s
        self._busy = False
        self.stop = asyncio.Event()

    def info(self) -> EngineWorkerInfo:
        try:
            models = self._engine.models(None)
        except Exception:
            log.exception("the engine could not list its models")
            models = []
        return EngineWorkerInfo(
            id=self.name, kinds=speech_wire.KINDS, models=models, busy=self._busy
        )

    async def _heartbeat(self) -> None:
        while not self.stop.is_set():
            try:
                await self._queue.register(self.info())
            except Exception:
                log.exception("could not tell the API this worker is here")
            if await sleep_or_stop(self.stop, self._beat):
                return

    async def run_once(self, block_ms: int = 5000) -> bool:
        """Take and run one job. False when there was none."""
        claimed = await self._queue.claim(self.name, block_ms=block_ms)
        if claimed is None:
            return False
        stream_id, job = claimed
        log.info("job %s (%s) for %s", job.id, job.kind, job.tenant_id)
        self._busy = True
        try:
            await self._queue.register(self.info())  # the API sees it is busy now
            outcome = await asyncio.wait_for(
                run_job(self._engine, self._storage, job, self.name), timeout=self._timeout
            )
        except TimeoutError:
            outcome = EngineOutcome(
                id=job.id, ok=False, worker=self.name,
                error=EngineError(code="timeout", message="That took too long and was stopped."),
            )  # fmt: skip
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
