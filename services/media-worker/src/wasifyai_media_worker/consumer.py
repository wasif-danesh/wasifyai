"""The worker loop: take a job from the Redis stream, process it, report the result.

Streams with a consumer group give at-least-once delivery. A worker that dies mid-job leaves its
entry unacknowledged; another worker re-claims it after the job timeout and the processor's
stored result keeps the retry idempotent.
"""

import asyncio
import json
import logging
import socket
from collections.abc import Callable
from typing import Any

from redis.asyncio import Redis
from wasifyai_platform_sdk import JobRequest, JobResult
from wasifyai_platform_sdk.jobqueue import (
    DONE_STREAM,
    JOBS_GROUP,
    JOBS_STREAM,
    ensure_groups,
    waiting_jobs,
)
from wasifyai_platform_sdk.jobs import progress_event

from wasifyai_media_worker.processor import JobProcessor, RetryJob

log = logging.getLogger(__name__)

MAX_QUEUE_UPDATES = 50


def completion_message(job: JobRequest, result: JobResult) -> dict[str, Any]:
    return {
        "tenant_id": job.tenant_id,
        "run_id": job.run_id,
        "job_id": job.job_id,
        "result": result.model_dump(mode="json"),
    }


class Worker:
    def __init__(
        self,
        redis: Redis,
        processor: JobProcessor,
        name: str | None = None,
        retry_backoff: Callable[[int], float] = lambda attempt: min(2**attempt, 30),
    ):
        self._r = redis
        self._p = processor
        self._backoff = retry_backoff
        self.name = name or f"{socket.gethostname()}-{id(self)}"
        # An entry idle longer than the job timeout belongs to a worker that died.
        self._stale_ms = (processor.s.job_timeout_s + 60) * 1000

    async def run_forever(self) -> None:
        await ensure_groups(self._r)
        log.info("worker %s started (gpu=%s)", self.name, self._p.s.gpu_id)
        while True:
            try:
                if not await self.run_once(block_ms=2000):
                    await self._reclaim_stale()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("worker loop error")
                await asyncio.sleep(2)

    async def run_once(self, block_ms: int = 0) -> bool:
        """Handle at most one new job. Returns False when the queue was empty."""
        res: Any = await self._r.xreadgroup(
            JOBS_GROUP, self.name, {JOBS_STREAM: ">"}, count=1, block=block_ms or None
        )
        entries = [e for _s, es in res or [] for e in es]
        for entry_id, fields in entries:
            await self._handle(entry_id, fields)
        return bool(entries)

    async def _reclaim_stale(self) -> None:
        claimed: Any = await self._r.xautoclaim(
            JOBS_STREAM, JOBS_GROUP, self.name, min_idle_time=self._stale_ms, count=1
        )
        for entry_id, fields in claimed[1]:
            log.warning("re-claimed stale job entry %s", entry_id)
            await self._handle(entry_id, fields)

    async def _handle(self, entry_id: str, fields: dict[str, str]) -> None:
        job = JobRequest.model_validate_json(fields["d"])
        await self._announce_queue_positions()
        try:
            result = await self._p.process(job)
        except RetryJob as e:
            delay = self._backoff(e.attempt)
            log.warning("job %s: transient failure (%s); retrying in %ss", job.job_id, e, delay)
            await asyncio.sleep(delay)
            await self._r.xadd(JOBS_STREAM, {"d": job.model_dump_json()})  # back of the queue
            await self._r.xack(JOBS_STREAM, JOBS_GROUP, entry_id)
            return
        # Result first, ack second: a crash in between redelivers the job, and the stored result
        # makes the duplicate completion harmless.
        await self._r.xadd(DONE_STREAM, {"d": json.dumps(completion_message(job, result))})
        await self._r.xack(JOBS_STREAM, JOBS_GROUP, entry_id)

    async def _announce_queue_positions(self) -> None:
        """Tell jobs still waiting where they are now (the running job counts as position 1)."""
        for i, (_id, waiting) in enumerate(await waiting_jobs(self._r, MAX_QUEUE_UPDATES)):
            if event := progress_event(waiting, "queued", queue_position=i + 2):
                await self._p.log.append(waiting.tenant_id, waiting.run_id or "", event)
