"""Resumes graphs paused on a media job, from the SQLite queue of the desktop profile (ADR-0056).
The counterpart of `JobCompletionConsumer`, with the same retry rules."""

import asyncio
import logging

from wasifyai_platform_sdk import RunStore
from wasifyai_platform_sdk.sqlite import SqliteJobQueue

from wasifyai_api.jobs_consumer import MAX_ATTEMPTS, RETRY_AFTER_MS, handle_completion
from wasifyai_api.runs import RunManager

log = logging.getLogger(__name__)

POLL_S = 0.25


class LocalCompletionConsumer:
    def __init__(self, queue: SqliteJobQueue, runs: RunManager, store: RunStore):
        self._queue = queue
        self._runs = runs
        self._store = store
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            try:
                batch = await self._queue.take_done(20, retry_after_s=RETRY_AFTER_MS / 1000)
                for done in batch:
                    await self._process(done.entry_id, done.attempts, done.message)
                if not batch:
                    await asyncio.sleep(POLL_S)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("job completion consumer error")
                await asyncio.sleep(1)

    async def _process(self, entry_id: int, attempts: int, message: dict) -> None:
        try:
            done = await handle_completion(self._runs, self._store, message)
        except Exception:
            log.exception("failed to handle job completion", extra={"entry": entry_id})
            done = False
        if done or attempts >= MAX_ATTEMPTS:
            if not done:
                log.error("dropping job completion after %d attempts", attempts)
            await self._queue.ack_done(entry_id)
