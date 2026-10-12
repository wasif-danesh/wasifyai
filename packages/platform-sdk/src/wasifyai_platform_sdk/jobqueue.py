"""Redis job queue shared by the API (producer, completion consumer) and the media worker.

Streams with consumer groups give at-least-once delivery, crash recovery (XAUTOCLAIM) and
queue positions without extra bookkeeping:

    wasifyai:jobs        jobs waiting for a GPU worker       group `workers`
    wasifyai:jobs:done   results waiting for an API replica  group `api` (resumes the paused graph)
"""

from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from wasifyai_platform_sdk.eventlog import EventLog
from wasifyai_platform_sdk.jobs import JobRequest, progress_event

JOBS_STREAM = "wasifyai:jobs"
JOBS_GROUP = "workers"
DONE_STREAM = "wasifyai:jobs:done"
DONE_GROUP = "api"


async def ensure_groups(redis: Redis) -> None:
    for stream, group in ((JOBS_STREAM, JOBS_GROUP), (DONE_STREAM, DONE_GROUP)):
        try:
            # id "0": entries added before the first consumer started are still delivered
            await redis.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise


async def waiting_jobs(redis: Redis, limit: int = 100) -> list[tuple[str, JobRequest]]:
    """Jobs no worker has picked up yet, oldest first."""
    groups: Any = await redis.xinfo_groups(JOBS_STREAM)
    last = next((g["last-delivered-id"] for g in groups if g["name"] == JOBS_GROUP), "0-0")
    entries: Any = await redis.xrange(JOBS_STREAM, min=f"({last}", max="+", count=limit)
    return [(str(eid), JobRequest.model_validate_json(f["d"])) for eid, f in entries]


async def running_jobs(redis: Redis) -> int:
    """Jobs delivered to a worker and not yet acknowledged."""
    summary: Any = await redis.xpending(JOBS_STREAM, JOBS_GROUP)
    return int(summary["pending"]) if summary else 0


async def queue_position(redis: Redis, stream_id: str) -> int:
    """1 = running now or next to run. Counts running jobs plus the waiting jobs ahead of this
    one. A job a worker has already picked up is the running one, so its place is 1."""
    waiting = await waiting_jobs(redis)
    ahead = next((i for i, (eid, _) in enumerate(waiting) if eid == stream_id), None)
    if ahead is None:
        return 1
    return await running_jobs(redis) + ahead + 1


class RedisJobSink:
    """Queues a job for the media worker and tells the run's stream it is queued."""

    def __init__(self, redis: Redis, log: EventLog):
        self._r = redis
        self._log = log
        self._ready = False

    async def submit(self, request: JobRequest) -> None:
        if not self._ready:
            await ensure_groups(self._r)
            self._ready = True
        stream_id = str(await self._r.xadd(JOBS_STREAM, {"d": request.model_dump_json()}))
        if event := progress_event(request, "queued", await queue_position(self._r, stream_id)):
            await self._log.append(request.tenant_id, request.run_id or "", event)
