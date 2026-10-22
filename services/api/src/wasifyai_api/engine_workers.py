"""Which engine workers are running and what each has (ADR-0087): read from Redis every few
seconds and kept, so the engines that call workers (speech, 3D) can say what is offered at once."""

import asyncio
import logging
from typing import Any

from wasifyai_platform_sdk import EngineQueue, EngineWorkerInfo

log = logging.getLogger("wasifyai_api.engine_workers")

REFRESH_S = 3.0


class WorkerDirectory:
    def __init__(self, queue: EngineQueue):
        self._queue = queue
        self.workers: list[EngineWorkerInfo] = []
        self._task: asyncio.Task[None] | None = None

    @property
    def queue(self) -> EngineQueue:
        """For the admin routes, which start jobs a worker runs on itself (P5)."""
        return self._queue

    async def refresh(self) -> None:
        self.workers = await self._queue.workers()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("could not read the list of workers")
            await asyncio.sleep(REFRESH_S)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def component(self, name: str) -> dict[str, Any] | None:
        """What a worker says about a component it runs: one that is ready if any is, else any."""
        found = [w.components[name] for w in self.workers if name in w.components]
        ready = [c for c in found if c.get("ready")]
        return (ready or found or [None])[0]
