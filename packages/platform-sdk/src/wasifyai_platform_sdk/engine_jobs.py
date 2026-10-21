"""Engine jobs: the desktop's heavy capabilities (speech, music, splitting, lip sync, ...) run by
an engine worker for the web (ADR-0087). The API queues a job, a worker (the desktop engine
without the window, on a Mac or a GPU host) runs it, and the API reads the result.

Files go through object storage, never through Redis: the job names the keys of its inputs, the
outcome names the keys of its outputs, all under the person's own prefix (rule 7). Redis streams
give at-least-once delivery and crash recovery:

    wasifyai:engine:jobs            jobs waiting for a worker        group `engine-workers`
    wasifyai:engine:done:<id>       the outcome of one job (a list the API pops), kept for an hour
    wasifyai:engine:progress:<id>   how far a running job is
    wasifyai:engine:worker:<id>     a live worker and the models it lists (expires unless renewed)
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import ResponseError

NAMESPACE = "wasifyai:engine"
JOBS_GROUP = "engine-workers"

DONE_TTL_S = 3600
WORKER_TTL_S = 30  # a worker refreshes its entry well inside this; a dead one drops out of the list
# a job a worker took and never finished is run again by another after this long
RECLAIM_AFTER_MS = 45 * 60 * 1000


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EngineJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: str  # "speech.speak", "speech.music", ... (the worker's handlers are keyed by it)
    tenant_id: str
    product_id: str
    user_id: str
    # every file of the job lives under this key prefix (the person's own); a worker refuses others
    prefix: str
    params: dict[str, Any] = Field(default_factory=dict)  # what was asked, as JSON
    files: dict[str, str] = Field(default_factory=dict)  # input name -> storage key
    created_at: str = Field(default_factory=_now)


class EngineError(BaseModel):
    code: str
    message: str  # user-safe: no stack traces, paths or host names


class EngineOutcome(BaseModel):
    id: str
    ok: bool
    outputs: dict[str, str] = Field(default_factory=dict)  # output name -> storage key
    meta: dict[str, Any] = Field(
        default_factory=dict
    )  # numbers and words that belong to the result
    error: EngineError | None = None
    worker: str | None = None
    seconds: float = 0.0  # time the worker spent on it


class EngineWorkerInfo(BaseModel):
    id: str
    kinds: list[str]
    models: list[dict[str, Any]]  # the engine's descriptors with their state on that machine
    busy: bool = False
    seen: float = 0.0


class EngineUnavailable(Exception):
    """No worker answered in time (none running, or the job waited too long)."""


ProgressFn = Callable[[float, str], Awaitable[None]]


class EngineQueue:
    def __init__(self, redis: Redis, namespace: str = NAMESPACE):
        self._r = redis
        self._ready = False
        self._jobs = f"{namespace}:jobs"
        self._done = f"{namespace}:done:"
        self._progress = f"{namespace}:progress:"
        self._worker = f"{namespace}:worker:"

    async def _ensure(self) -> None:
        if self._ready:
            return
        try:
            await self._r.xgroup_create(self._jobs, JOBS_GROUP, id="0", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        self._ready = True

    # ---- the API's side ------------------------------------------------------------------

    async def submit(self, job: EngineJob) -> None:
        await self._ensure()
        await self._r.xadd(self._jobs, {"d": job.model_dump_json()})

    async def wait(
        self,
        job_id: str,
        timeout_s: float,
        on_progress: ProgressFn | None = None,
        poll_s: int = 2,
    ) -> EngineOutcome:
        """The outcome of a job. Raises EngineUnavailable when it takes longer than `timeout_s`."""
        deadline = time.monotonic() + timeout_s
        key = self._done + job_id
        last = ""
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise EngineUnavailable("The speech worker did not answer in time.")
            popped = await self._r.brpop([key], timeout=max(1, min(poll_s, int(left))))
            if popped:
                return EngineOutcome.model_validate_json(popped[1])
            if on_progress is not None:
                raw = await self._r.get(self._progress + job_id)
                if raw and raw != last:
                    last = raw
                    p = json.loads(raw)
                    await on_progress(float(p.get("fraction", 0.0)), str(p.get("label", "")))

    async def workers(self) -> list[EngineWorkerInfo]:
        out = []
        async for key in self._r.scan_iter(match=self._worker + "*", count=50):
            raw = await self._r.get(key)
            if raw:
                out.append(EngineWorkerInfo.model_validate_json(raw))
        return sorted(out, key=lambda w: w.id)

    # ---- a worker's side -----------------------------------------------------------------

    async def claim(self, consumer: str, block_ms: int = 5000) -> tuple[str, EngineJob] | None:
        """The next job for this worker, or None after `block_ms`. A job another worker took and
        left for too long is taken over first."""
        await self._ensure()
        stale: Any = await self._r.xautoclaim(
            self._jobs,
            JOBS_GROUP,
            consumer,
            min_idle_time=RECLAIM_AFTER_MS,
            start_id="0-0",
            count=1,
        )
        entries = stale[1] if stale else []
        if not entries:
            got: Any = await self._r.xreadgroup(
                JOBS_GROUP, consumer, {self._jobs: ">"}, count=1, block=block_ms
            )
            entries = got[0][1] if got else []
        if not entries:
            return None
        stream_id, fields = entries[0]
        return str(stream_id), EngineJob.model_validate_json(fields["d"])

    async def report(self, job_id: str, fraction: float, label: str = "") -> None:
        await self._r.set(
            self._progress + job_id, json.dumps({"fraction": fraction, "label": label}), ex=600
        )

    async def finish(self, stream_id: str, outcome: EngineOutcome) -> None:
        key = self._done + outcome.id
        await self._r.lpush(key, outcome.model_dump_json())  # type: ignore[misc]
        await self._r.expire(key, DONE_TTL_S)
        await self._r.xack(self._jobs, JOBS_GROUP, stream_id)
        await self._r.xdel(self._jobs, stream_id)
        await self._r.delete(self._progress + outcome.id)

    async def register(self, worker: EngineWorkerInfo) -> None:
        worker = worker.model_copy(update={"seen": time.time()})
        await self._r.set(self._worker + worker.id, worker.model_dump_json(), ex=WORKER_TTL_S)

    async def leave(self, worker_id: str) -> None:
        await self._r.delete(self._worker + worker_id)


async def sleep_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    """Wait `seconds`, or until `stop` is set. True when stopped."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
        return True
    except TimeoutError:
        return False
