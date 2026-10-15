"""The worker loop of the desktop profile (ADR-0056): the same job handling as `consumer.Worker`,
over the SQLite queue instead of Redis streams, running inside the engine's process."""

import asyncio
import logging
from collections.abc import Callable

from wasifyai_platform_sdk.jobs import progress_event
from wasifyai_platform_sdk.sqlite import QueuedJob, SqliteJobQueue

from wasifyai_media_worker.consumer import MAX_QUEUE_UPDATES, completion_message
from wasifyai_media_worker.processor import JobProcessor, RetryJob

log = logging.getLogger(__name__)

IDLE_WAIT_S = 1.0  # a worker also looks now and then, in case a job arrived without a wake-up


class LocalWorker:
    def __init__(
        self,
        queue: SqliteJobQueue,
        processor: JobProcessor,
        retry_backoff: Callable[[int], float] = lambda attempt: min(2**attempt, 30),
    ):
        self._queue = queue
        self._p = processor
        self._backoff = retry_backoff

    async def run_forever(self) -> None:
        # This process is the only worker: a job marked running is one the last run never finished.
        recovered = await self._queue.recover()
        if recovered:
            log.warning("put %d unfinished job(s) back in the queue", recovered)
        while True:
            try:
                if not await self.run_once():
                    await self._queue.wait_for_work(IDLE_WAIT_S)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("worker loop error")
                await asyncio.sleep(2)

    async def run_once(self) -> bool:
        """Handle at most one job. Returns False when the queue was empty."""
        job = await self._queue.claim()
        if job is None:
            return False
        await self._handle(job)
        return True

    async def _handle(self, queued: QueuedJob) -> None:
        job = queued.request
        await self._announce_queue_positions()
        try:
            result = await self._p.process(job)
        except RetryJob as e:
            delay = self._backoff(e.attempt)
            log.warning("job %s: transient failure (%s); retrying in %ss", job.job_id, e, delay)
            await asyncio.sleep(delay)
            await self._queue.requeue(queued.entry_id)  # back of the queue
            return
        await self._queue.complete(queued.entry_id, completion_message(job, result))

    async def _announce_queue_positions(self) -> None:
        """Tell jobs still waiting where they are now (the running job counts as position 1)."""
        for i, waiting in enumerate(await self._queue.waiting(MAX_QUEUE_UPDATES)):
            if event := progress_event(waiting.request, "queued", queue_position=i + 2):
                await self._p.log.append(
                    waiting.request.tenant_id, waiting.request.run_id or "", event
                )
