"""The job queue on SQLite: what the Redis streams do in the web profile (ADR-0021).

    job_queue   jobs waiting for a worker (state `waiting`) or taken by one (`running`)
    job_done    results waiting for the API to resume the paused graph

Same guarantees as the streams, for one process: FIFO claims, a position for every waiting job,
at-least-once delivery (a job taken by a worker that died goes back with `recover`), and a result
is written before the job entry goes away, so a crash in between delivers it again."""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.eventlog import EventLog
from wasifyai_platform_sdk.jobs import JobRequest, progress_event
from wasifyai_platform_sdk.sqlite.engine import Migration, migrate, now_iso, to_iso

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS job_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        job_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'waiting',
        claimed_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_job_queue_state ON job_queue (state, id)",
    """
    CREATE TABLE IF NOT EXISTS job_done (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        job_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        tried_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
)

# the store's shape before the migration runner (stage J1); a change is a new Migration(2, ...)
_MIGRATIONS = (Migration(1, _DDL),)


@dataclass(frozen=True)
class QueuedJob:
    entry_id: int
    request: JobRequest


@dataclass(frozen=True)
class DoneMessage:
    entry_id: int
    attempts: int  # deliveries so far, this one included
    message: dict[str, Any]


class SqliteJobQueue:
    """Both ends of the queue: `submit` is the JobSink the API uses; the worker side claims and
    completes; the API side reads the results with `take_done`."""

    def __init__(self, engine: AsyncEngine, log: EventLog):
        self._engine = engine
        self._log = log
        self._work = asyncio.Event()  # set by `submit` and `requeue`, so a worker need not poll
        # jobs the person stopped (stage J3): the worker in this process stops them where they
        # are; the row says so too, so a restart never runs them again
        self._cancelled: set[str] = set()

    async def cancel(self, job_id: str) -> None:
        """Stop a job: one still waiting leaves the queue, one being made is marked `stopping`
        (the worker stops it within a second; `recover` drops it if the app quit first)."""
        self._cancelled.add(job_id)
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM job_queue WHERE job_id = :j AND state = 'waiting'"), {"j": job_id}
            )
            await conn.execute(
                text(
                    "UPDATE job_queue SET state = 'stopping' "
                    "WHERE job_id = :j AND state = 'running'"
                ),
                {"j": job_id},
            )

    async def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancelled

    async def wait_for_work(self, timeout_s: float) -> None:
        """Return when a job has been submitted, or after `timeout_s`, whichever is first."""
        self._work.clear()
        try:
            await asyncio.wait_for(self._work.wait(), timeout=timeout_s)
        except TimeoutError:
            pass

    async def _ready(self) -> None:
        await migrate(self._engine, "job_queue", _MIGRATIONS)

    # ---- API side -----------------------------------------------------------------------

    async def submit(self, request: JobRequest) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            entry_id = (
                await conn.execute(
                    text(
                        "INSERT INTO job_queue (tenant_id, job_id, payload, created_at) "
                        "VALUES (:t, :j, :p, :c) RETURNING id"
                    ),
                    {
                        "t": request.tenant_id,
                        "j": request.job_id,
                        "p": request.model_dump_json(),
                        "c": now_iso(),
                    },
                )
            ).scalar_one()
        if event := progress_event(request, "queued", await self.position(int(entry_id))):
            await self._log.append(request.tenant_id, request.run_id or "", event)
        self._work.set()

    async def position(self, entry_id: int) -> int:
        """1 = running now or next to run: running jobs plus the waiting jobs ahead, plus one."""
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT "
                        "(SELECT COUNT(*) FROM job_queue WHERE state = 'running'), "
                        "(SELECT COUNT(*) FROM job_queue WHERE state = 'waiting' AND id < :i)"
                    ),
                    {"i": entry_id},
                )
            ).one()
        return int(row[0]) + int(row[1]) + 1

    async def take_done(self, limit: int = 20, retry_after_s: float = 1.0) -> list[DoneMessage]:
        """Results not yet finished with. A result handed out is not handed out again until
        `retry_after_s` has passed, so a caller can ack it or let it come back."""
        await self._ready()
        cutoff = to_iso(datetime.now(UTC) - timedelta(seconds=retry_after_s))
        async with self._engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "UPDATE job_done SET attempts = attempts + 1, tried_at = :now "
                        "WHERE id IN (SELECT id FROM job_done "
                        "WHERE tried_at IS NULL OR tried_at < :cutoff ORDER BY id LIMIT :n) "
                        "RETURNING id, attempts, payload"
                    ),
                    {"now": now_iso(), "cutoff": cutoff, "n": limit},
                )
            ).all()
        return [DoneMessage(int(r[0]), int(r[1]), json.loads(r[2])) for r in sorted(rows)]

    async def ack_done(self, entry_id: int) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(text("DELETE FROM job_done WHERE id = :i"), {"i": entry_id})

    # ---- worker side --------------------------------------------------------------------

    async def claim(self) -> QueuedJob | None:
        """Take the oldest waiting job, or None when there is none."""
        await self._ready()
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "UPDATE job_queue SET state = 'running', claimed_at = :now "
                        "WHERE id = (SELECT id FROM job_queue WHERE state = 'waiting' "
                        "ORDER BY id LIMIT 1) RETURNING id, payload"
                    ),
                    {"now": now_iso()},
                )
            ).first()
        if row is None:
            return None
        return QueuedJob(int(row[0]), JobRequest.model_validate_json(row[1]))

    async def waiting(self, limit: int = 100) -> list[QueuedJob]:
        """Jobs no worker has taken yet, oldest first."""
        await self._ready()
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, payload FROM job_queue WHERE state = 'waiting' "
                        "ORDER BY id LIMIT :n"
                    ),
                    {"n": limit},
                )
            ).all()
        return [QueuedJob(int(r[0]), JobRequest.model_validate_json(r[1])) for r in rows]

    async def complete(self, entry_id: int, message: dict[str, Any]) -> None:
        """Result first, then the job entry goes away, in one transaction."""
        await self._ready()
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT tenant_id, job_id FROM job_queue WHERE id = :i"), {"i": entry_id}
                )
            ).first()
            if row is None:
                return  # completed already (a redelivery that finished twice)
            await conn.execute(
                text(
                    "INSERT INTO job_done (tenant_id, job_id, payload, created_at) "
                    "VALUES (:t, :j, :p, :c)"
                ),
                {"t": row[0], "j": row[1], "p": json.dumps(message), "c": now_iso()},
            )
            await conn.execute(text("DELETE FROM job_queue WHERE id = :i"), {"i": entry_id})

    async def requeue(self, entry_id: int) -> None:
        """Put a job at the back of the queue (a transient backend failure)."""
        await self._ready()
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT tenant_id, job_id, payload FROM job_queue WHERE id = :i"),
                    {"i": entry_id},
                )
            ).first()
            if row is None:
                return
            await conn.execute(text("DELETE FROM job_queue WHERE id = :i"), {"i": entry_id})
            await conn.execute(
                text(
                    "INSERT INTO job_queue (tenant_id, job_id, payload, created_at) "
                    "VALUES (:t, :j, :p, :c)"
                ),
                {"t": row[0], "j": row[1], "p": row[2], "c": now_iso()},
            )
        self._work.set()

    async def recover(self, older_than_s: float = 0.0) -> int:
        """Give jobs taken by a worker that is gone back to the queue, and drop the ones that were
        being stopped. At startup `older_than_s` is 0: the one worker of this process is the only
        one that could have held them."""
        await self._ready()
        cutoff = to_iso(datetime.now(UTC) - timedelta(seconds=older_than_s))
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM job_queue WHERE state = 'stopping' AND claimed_at <= :c"),
                {"c": cutoff},
            )
            result = await conn.execute(
                text(
                    "UPDATE job_queue SET state = 'waiting', claimed_at = NULL "
                    "WHERE state = 'running' AND claimed_at <= :c"
                ),
                {"c": cutoff},
            )
        return result.rowcount or 0
