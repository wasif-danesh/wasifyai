"""Usage events on SQLite (the table billing reads in the web profile)."""

import json
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.sqlite.engine import ensure_tables, now_iso
from wasifyai_platform_sdk.usage import UsageEvent

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS usage_events (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT,
        run_id TEXT,
        kind TEXT NOT NULL,
        quantity REAL NOT NULL,
        unit TEXT NOT NULL,
        meta TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_usage_events_user_kind_time "
    "ON usage_events (tenant_id, product_id, user_id, kind, created_at)",
)


class SqliteUsageRecorder:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def record(self, event: UsageEvent) -> None:
        await ensure_tables(self._engine, "usage_events", _DDL)
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO usage_events "
                    "(id, tenant_id, product_id, user_id, run_id, kind, quantity, unit, meta, "
                    "created_at) VALUES "
                    "(:id, :tenant_id, :product_id, :user_id, :run_id, :kind, :quantity, :unit, "
                    ":meta, :created_at)"
                ),
                {
                    "id": str(uuid4()),
                    "tenant_id": event.tenant_id,
                    "product_id": event.product_id,
                    "user_id": event.user_id,
                    "run_id": event.run_id,
                    "kind": event.kind,
                    "quantity": event.quantity,
                    "unit": event.unit,
                    "meta": json.dumps(event.meta),
                    "created_at": now_iso(),
                },
            )
