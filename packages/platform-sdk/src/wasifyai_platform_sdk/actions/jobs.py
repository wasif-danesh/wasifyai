"""Job handles (ADR-0068 decision 3): a long action returns `{job_id, status}` at once, and
`job.status`, `job.wait` and `job.cancel` follow it.

The book holds the jobs this process is running (their tasks and the event a waiter waits on) and
writes every job through to a `JobStore` (stage J3 of the 2026-10-27 plan): the `action_jobs` table
in the database the engine already has, so a job outlives a restart. A job a restarted engine finds
"running" in the store is settled by the executor from the product run it started (`run_id`), or
said to have stopped with the app when it ran in the engine's own process."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.actions.result import ActionResult
from wasifyai_platform_sdk.sqlite.engine import Migration, is_sqlite, migrate

JobStatus = Literal["running", "ok", "refused", "error", "cancelled"]
MAX_JOBS = (
    200  # finished jobs beyond this are forgotten by the book, oldest first (the store keeps them)
)
PROGRESS_EVERY_S = 2.0  # progress is written to the store at most this often


@dataclass
class Job:
    id: str
    action_id: str
    tenant_id: str
    user_id: str
    origin: str
    cancellable: bool
    product_id: str = "platform"  # the action's product (rule 7: tenant and product on every row)
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    status: JobStatus = "running"
    result: ActionResult | None = None
    progress: dict[str, Any] | None = None
    # the product run the job started (a run binding), so a restarted engine can follow it
    run_id: str | None = None
    # the action's parameters, so its result can be read from that run after a restart
    params: dict[str, Any] | None = None
    task: asyncio.Task[Any] | None = None
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    saved_progress_at: float = 0.0

    @property
    def seconds(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.time()
        return round(max(0.0, end - self.started_at), 1)

    @property
    def live(self) -> bool:
        """Whether this process is running it (a job read back from the store is not)."""
        return self.task is not None


class JobStore(Protocol):
    async def save(self, job: Job) -> None:
        """Insert the job or replace what is known of it."""
        ...

    async def get(self, tenant_id: str, user_id: str, job_id: str) -> Job | None:
        """A job of this person only: another person's job is no job at all."""
        ...


class InMemoryJobStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def save(self, job: Job) -> None:
        self.rows[job.id] = _row(job)

    async def get(self, tenant_id: str, user_id: str, job_id: str) -> Job | None:
        row = self.rows.get(job_id)
        if row is None or (row["tenant_id"], row["user_id"]) != (tenant_id, user_id):
            return None
        return _job(row)


def _row(job: Job) -> dict[str, Any]:
    return {
        "id": job.id, "tenant_id": job.tenant_id, "product_id": job.product_id,
        "user_id": job.user_id, "action_id": job.action_id, "origin": job.origin,
        "cancellable": int(job.cancellable),
        "status": job.status, "run_id": job.run_id,
        "params": json.dumps(job.params) if job.params is not None else None,
        "progress": json.dumps(job.progress) if job.progress else None,
        "result": job.result.model_dump_json(exclude_none=True) if job.result else None,
        "started_at": job.started_at, "ended_at": job.ended_at,
    }  # fmt: skip


def _job(row: Any) -> Job:
    m = dict(row)
    job = Job(
        m["id"], m["action_id"], m["tenant_id"], m["user_id"], m["origin"],
        bool(m["cancellable"]), product_id=m["product_id"], started_at=float(m["started_at"]),
        ended_at=float(m["ended_at"]) if m["ended_at"] is not None else None,
        status=m["status"], run_id=m["run_id"],
        params=json.loads(m["params"]) if m["params"] else None,
        progress=json.loads(m["progress"]) if m["progress"] else None,
        result=ActionResult.model_validate_json(m["result"]) if m["result"] else None,
    )  # fmt: skip
    if job.status != "running":
        job.finished.set()
    return job


_JOBS_DDL = (
    """
    CREATE TABLE IF NOT EXISTS action_jobs (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        action_id TEXT NOT NULL,
        origin TEXT NOT NULL,
        cancellable INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        run_id TEXT,
        params TEXT,
        progress TEXT,
        result TEXT,
        started_at DOUBLE PRECISION NOT NULL,
        ended_at DOUBLE PRECISION
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_action_jobs_user ON action_jobs (tenant_id, user_id, status)",
)

# the store's shape before the migration runner (stage J1); a change is a new Migration(2, ...)
_JOBS_MIGRATIONS = (Migration(1, _JOBS_DDL),)


class SqlJobStore:
    """The `action_jobs` table: Alembic 0027 on Postgres, created on first use on SQLite."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        if is_sqlite(self._engine):
            await migrate(self._engine, "action_jobs", _JOBS_MIGRATIONS)

    async def save(self, job: Job) -> None:
        await self._ready()
        values = _row(job)
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO action_jobs (id, tenant_id, product_id, user_id, action_id, "
                    "origin, cancellable, status, run_id, params, progress, result, started_at, "
                    "ended_at) VALUES (:id, :tenant_id, :product_id, :user_id, :action_id, "
                    ":origin, :cancellable, "
                    ":status, :run_id, :params, :progress, :result, :started_at, :ended_at) "
                    "ON CONFLICT (id) DO UPDATE SET status = excluded.status, "
                    "run_id = excluded.run_id, progress = excluded.progress, "
                    "result = excluded.result, ended_at = excluded.ended_at"
                ),
                values,
            )

    async def get(self, tenant_id: str, user_id: str, job_id: str) -> Job | None:
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT * FROM action_jobs "
                        "WHERE tenant_id = :t AND user_id = :u AND id = :i"
                    ),
                    {"t": tenant_id, "u": user_id, "i": job_id},
                )
            ).first()
        return _job(row._mapping) if row else None


class JobBook:
    def __init__(self, store: JobStore | None = None, limit: int = MAX_JOBS) -> None:
        self._jobs: dict[str, Job] = {}
        self._limit = limit
        self.store: JobStore = store or InMemoryJobStore()

    async def start(
        self,
        action_id: str,
        tenant_id: str,
        user_id: str,
        origin: str,
        cancellable: bool,
        params: dict[str, Any] | None = None,
        product_id: str = "platform",
    ) -> Job:
        job = Job(
            uuid4().hex[:16], action_id, tenant_id, user_id, origin, cancellable,
            product_id=product_id, params=params,
        )  # fmt: skip
        self._jobs[job.id] = job
        self._trim()
        await self.store.save(job)
        return job

    def get(self, tenant_id: str, user_id: str, job_id: str) -> Job | None:
        """A job of this person that this process holds."""
        job = self._jobs.get(job_id)
        return job if job and (job.tenant_id, job.user_id) == (tenant_id, user_id) else None

    async def find(self, tenant_id: str, user_id: str, job_id: str) -> Job | None:
        """This process's job, else the one the store kept (started before a restart)."""
        return self.get(tenant_id, user_id, job_id) or await self.store.get(
            tenant_id, user_id, job_id
        )

    def running(self, tenant_id: str, user_id: str) -> list[Job]:
        return [
            j
            for j in self._jobs.values()
            if j.status == "running" and (j.tenant_id, j.user_id) == (tenant_id, user_id)
        ]

    async def ran(self, job: Job, run_id: str) -> None:
        """The job started a product run: kept, so it can be followed after a restart."""
        job.run_id = run_id
        await self.store.save(job)

    async def progressed(self, job: Job, progress: dict[str, Any]) -> None:
        job.progress = progress
        now = time.monotonic()
        if now - job.saved_progress_at >= PROGRESS_EVERY_S:
            job.saved_progress_at = now
            await self.store.save(job)

    async def finish(self, job: Job, status: JobStatus, result: ActionResult) -> None:
        job.status, job.result, job.ended_at = status, result, time.time()
        job.finished.set()
        await self.store.save(job)

    async def wait(self, job: Job, seconds: float) -> bool:
        """Whether the job finished within `seconds`."""
        if job.finished.is_set():
            return True
        try:
            await asyncio.wait_for(job.finished.wait(), timeout=max(0.0, seconds))
        except TimeoutError:
            return False
        return True

    def _trim(self) -> None:
        done = [j for j in self._jobs.values() if j.status != "running"]
        for j in done[: max(0, len(self._jobs) - self._limit)]:
            del self._jobs[j.id]
