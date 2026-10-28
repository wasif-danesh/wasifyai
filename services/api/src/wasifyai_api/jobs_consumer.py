"""Resumes graphs that were paused on a media job when the worker reports the result.

Workers write results to a Redis stream; API replicas share a consumer group, so each result is
handled by exactly one replica, survives restarts (unacknowledged entries are re-claimed) and
needs no extra HTTP surface (ADR-0021).
"""

import asyncio
import json
import logging
import socket
from typing import Any

from redis.asyncio import Redis
from wasifyai_platform_sdk import RunStore
from wasifyai_platform_sdk.jobqueue import DONE_GROUP, DONE_STREAM, ensure_groups

from wasifyai_api.runs import RunManager

log = logging.getLogger(__name__)

RETRY_AFTER_MS = 1000  # re-check a result whose graph has not reached its wait yet
MAX_ATTEMPTS = 120  # about two minutes, then drop: the run finished or never waited


async def handle_completion(runs: RunManager, store: RunStore, message: dict[str, Any]) -> bool:
    """Resume the run waiting on this job. Returns True when the message is finished with
    (resumed, or nothing left to resume) and False when it should be retried shortly."""
    tenant_id, run_id, job_id = message["tenant_id"], message.get("run_id"), message["job_id"]
    if not run_id:
        return True  # a job started outside a run
    rec = await store.get(tenant_id, run_id)
    policy = getattr(runs, "job_policy", None)
    if rec is not None and policy is not None:  # the job is over: its person's place is free
        await policy.release(rec.tenant_id, rec.user_id, job_id)
    if rec is None or rec.status in ("done", "error", "cancelled"):
        return True
    if await store.take_waiting_job(tenant_id, run_id, job_id):
        runs.resume_with_job(rec, message["result"])
        return True
    return False  # the graph is still on its way to `await_job`; try again


class JobCompletionConsumer:
    def __init__(self, redis: Redis, runs: RunManager, store: RunStore):
        self._r = redis
        self._runs = runs
        self._store = store
        self._name = f"{socket.gethostname()}-{id(self)}"
        self._attempts: dict[str, int] = {}
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await ensure_groups(self._r)
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            try:
                fresh: Any = await self._r.xreadgroup(
                    DONE_GROUP, self._name, {DONE_STREAM: ">"}, count=20, block=500
                )
                entries = [e for _s, es in fresh or [] for e in es]
                # entries delivered earlier but not finished (retries, or a crashed replica's)
                reclaimed: Any = await self._r.xautoclaim(
                    DONE_STREAM, DONE_GROUP, self._name, min_idle_time=RETRY_AFTER_MS, count=20
                )
                claimed = reclaimed[1]
                for entry_id, fields in [*entries, *claimed]:
                    await self._process(entry_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("job completion consumer error")
                await asyncio.sleep(1)

    async def _process(self, entry_id: str, fields: dict[str, str]) -> None:
        try:
            done = await handle_completion(self._runs, self._store, json.loads(fields["d"]))
        except Exception:
            log.exception("failed to handle job completion", extra={"entry": entry_id})
            done = False
        n = self._attempts[entry_id] = self._attempts.get(entry_id, 0) + 1
        if done or n >= MAX_ATTEMPTS:
            if not done:
                log.error("dropping job completion after %d attempts", n, extra={"entry": entry_id})
            await self._r.xack(DONE_STREAM, DONE_GROUP, entry_id)
            self._attempts.pop(entry_id, None)
