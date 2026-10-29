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
import os
import socket
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from wasifyai_platform_sdk.tracing import carrier

NAMESPACE = "wasifyai:engine"
JOBS_GROUP = "engine-workers"

DONE_TTL_S = 6 * 3600  # an outcome waits this long for an API that restarted to come and read it
SEEN_TTL_S = 6 * 3600
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
    # the trace it belongs to (`traceparent`), taken where it is made, so the worker's span joins it
    trace: dict[str, str] = Field(default_factory=carrier)


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
    # other components this worker runs, by name, with their state (`model3d`: ready, problem, fit)
    components: dict[str, Any] = Field(default_factory=dict)
    busy: bool = False
    seen: float = 0.0


PLACE_LIMIT = 1000  # a place further back than this is said as this


def _entry(stream_id: str) -> tuple[int, int]:
    ms, _, seq = stream_id.partition("-")
    return int(ms), int(seq or 0)


# one id per running API process: the replica that follows a job after a restart (stage J3)
REPLICA = f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:6]}"
RESUME_HOLD_S = 60  # a replica that stops renewing its hold lets another follow the job


class EngineUnavailable(Exception):
    """No worker answered in time (none running, or the job waited too long)."""


ProgressFn = Callable[[float, str], Awaitable[None]]


class EngineQueue:
    def __init__(self, redis: Redis, namespace: str = NAMESPACE, policy: Any = None):
        self._r = redis
        # ADR-0088: the one policy point; a job enters only when its person may have one more
        self.policy = policy
        self._owner = f"{namespace}:owner:"  # job id -> "tenant user", to give its lease back
        self._resumer = f"{namespace}:resumer:"  # job id -> the API replica following it now
        self._ready = False
        self._jobs = f"{namespace}:jobs"
        self._done = f"{namespace}:done:"
        self._progress = f"{namespace}:progress:"
        self._worker = f"{namespace}:worker:"
        self._cancel = f"{namespace}:cancel:"
        self._seen = f"{namespace}:seen:"
        self._sid = f"{namespace}:sid:"  # job id -> its stream entry, for its place in the queue

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

    async def submit(self, job: EngineJob, timeout_s: float = 3600) -> None:
        """Queue a job. With a policy, the job enters only when its person may have one more in
        the line (raises `JobLimitReached` naming the job in the way) and holds a lease until it
        ends."""
        await self._ensure()
        if self.policy is not None:
            await self.policy.admit(job.tenant_id, job.user_id, job.id, job.kind, timeout_s)
            await self._r.set(self._owner + job.id, f"{job.tenant_id} {job.user_id}", ex=SEEN_TTL_S)
        sid = await self._r.xadd(self._jobs, {"d": job.model_dump_json()})
        await self._r.set(self._sid + job.id, sid, ex=SEEN_TTL_S)
        await self._r.set(self._seen + job.id, "1", ex=SEEN_TTL_S)  # `status` knows it was sent

    async def _release(self, job_id: str) -> None:
        """The job ended or was stopped: its person's place in the line is free (ADR-0088)."""
        if self.policy is None:
            return
        owner = await self._r.getdel(self._owner + job_id)
        if owner:
            tenant_id, user_id = str(owner).split(" ", 1)
            await self.policy.release(tenant_id, user_id, job_id)

    async def place(self, job_id: str) -> int | None:
        """The job's place among the jobs no worker has taken yet (1 = next), or None once a
        worker has it or it is not known (stage J3: the speech screens say how many are ahead)."""
        sid = await self._r.get(self._sid + job_id)
        if not sid:
            return None
        try:
            groups: Any = await self._r.xinfo_groups(self._jobs)
        except ResponseError:
            return None
        last = next(
            (str(g["last-delivered-id"]) for g in groups if str(g["name"]) == JOBS_GROUP), "0-0"
        )
        if _entry(str(sid)) <= _entry(last):
            return None
        ahead: Any = await self._r.xrange(
            self._jobs, min=f"({last}", max=f"({sid}", count=PLACE_LIMIT
        )
        return len(ahead) + 1

    async def take_resume(self, job_id: str) -> bool:
        """After a restart, only one API replica follows a job that was already sent (stage J3):
        True when this replica took it. The hold runs out unless `wait` keeps it, so a replica
        that dies while following lets another take over."""
        return (
            bool(await self._r.set(self._resumer + job_id, REPLICA, nx=True, ex=RESUME_HOLD_S))
            or (await self._r.get(self._resumer + job_id)) == REPLICA
        )

    async def resume_turn(self, job_id: str, poll_s: float = 10) -> None:
        """Wait until this replica may follow the job: at once when nobody does, else when the
        replica that does has finished with it or stopped holding it."""
        while True:
            if await self.take_resume(job_id):
                return
            await asyncio.sleep(poll_s)

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
            # this replica follows the job: keep holding it so no other one waits for it too
            if await self._r.get(self._resumer + job_id) == REPLICA:
                await self._r.expire(self._resumer + job_id, RESUME_HOLD_S)
            left = deadline - time.monotonic()
            if left <= 0:
                raise EngineUnavailable("The speech worker did not answer in time.")
            popped = await self._r.brpop([key], timeout=max(1, min(poll_s, int(left))))
            if popped:
                await self._r.delete(self._seen + job_id, self._sid + job_id)
                await self._r.delete(self._resumer + job_id)
                await self._release(job_id)
                return EngineOutcome.model_validate_json(popped[1])
            if on_progress is not None:
                raw = await self._r.get(self._progress + job_id)
                if raw and raw != last:
                    last = raw
                    p = json.loads(raw)
                    await on_progress(float(p.get("fraction", 0.0)), str(p.get("label", "")))

    async def status(self, job_id: str) -> str:
        """Where a job stands for an API that restarted and wants to pick it up again: `done` (the
        outcome is waiting), `waiting` (sent, not finished) or `lost` (never sent, or too old)."""
        if await self._r.exists(self._done + job_id):
            return "done"
        return "waiting" if await self._r.exists(self._seen + job_id) else "lost"

    async def peek(self, job_id: str) -> EngineOutcome | None:
        """The outcome of a job without taking it, for a page that follows a job it does not wait
        for (an admin fetching a model). It stays until it expires."""
        raw = await self._r.lindex(self._done + job_id, 0)  # type: ignore[misc]
        return EngineOutcome.model_validate_json(raw) if raw else None

    async def progress_of(self, job_id: str) -> tuple[float, str] | None:
        raw = await self._r.get(self._progress + job_id)
        if not raw:
            return None
        p = json.loads(raw)
        return float(p.get("fraction", 0.0)), str(p.get("label", ""))

    async def cancel(self, job_id: str) -> None:
        """Ask the worker that has this job to stop it (a 3D run takes minutes). Its place in the
        line is free at once (ADR-0088 decision 5)."""
        await self._r.set(self._cancel + job_id, "1", ex=DONE_TTL_S)
        await self._release(job_id)

    async def cancelled(self, job_id: str) -> bool:
        return bool(await self._r.exists(self._cancel + job_id))

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
