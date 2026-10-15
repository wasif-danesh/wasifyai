"""Run records on SQLite: who owns a run and what it is waiting for (same rules as the Redis
store)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.runstore import RunRecord
from wasifyai_platform_sdk.sqlite.engine import ensure_tables

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS runs (
        tenant_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        status TEXT NOT NULL,
        awaiting TEXT,
        waiting_job TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, run_id)
    )
    """,
)
_COLUMNS = (
    "run_id, thread_id, product_id, tenant_id, user_id, status, awaiting, waiting_job, created_at"
)


class SqliteRunStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        await ensure_tables(self._engine, "runs", _DDL)

    async def create(self, rec: RunRecord) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    f"INSERT OR REPLACE INTO runs ({_COLUMNS}) VALUES "
                    "(:run_id, :thread_id, :product_id, :tenant_id, :user_id, :status, "
                    ":awaiting, :waiting_job, :created_at)"
                ),
                rec.model_dump(),
            )

    async def get(self, tenant_id: str, run_id: str) -> RunRecord | None:
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(f"SELECT {_COLUMNS} FROM runs WHERE tenant_id = :t AND run_id = :r"),
                    {"t": tenant_id, "r": run_id},
                )
            ).first()
        if row is None:
            return None
        return RunRecord(
            run_id=row[0], thread_id=row[1], product_id=row[2], tenant_id=row[3], user_id=row[4],
            status=row[5], awaiting=row[6] or None, waiting_job=row[7] or None, created_at=row[8],
        )  # fmt: skip

    async def set_state(
        self,
        tenant_id: str,
        run_id: str,
        status: str,
        awaiting: str | None = None,
        waiting_job: str | None = None,
    ) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE runs SET status = :s, awaiting = :a, waiting_job = :j "
                    "WHERE tenant_id = :t AND run_id = :r"
                ),
                {"s": status, "a": awaiting, "j": waiting_job, "t": tenant_id, "r": run_id},
            )

    async def _take(
        self, tenant_id: str, run_id: str, column: str, expect: str | None
    ) -> str | None:
        """Clear `column` and set the run back to running, only if it holds a value (and `expect`,
        when given). The guarded UPDATE makes two simultaneous takers get one winner."""
        await self._ready()
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(f"SELECT {column} FROM runs WHERE tenant_id = :t AND run_id = :r"),
                    {"t": tenant_id, "r": run_id},
                )
            ).first()
            value = row[0] if row else None
            if not value or (expect is not None and value != expect):
                return None
            claimed = await conn.execute(
                text(
                    f"UPDATE runs SET {column} = NULL, status = 'running' "
                    f"WHERE tenant_id = :t AND run_id = :r AND {column} = :v"
                ),
                {"t": tenant_id, "r": run_id, "v": value},
            )
            return value if claimed.rowcount else None

    async def take_awaiting(self, tenant_id: str, run_id: str) -> str | None:
        return await self._take(tenant_id, run_id, "awaiting", None)

    async def take_waiting_job(self, tenant_id: str, run_id: str, job_id: str) -> bool:
        return await self._take(tenant_id, run_id, "waiting_job", job_id) is not None
