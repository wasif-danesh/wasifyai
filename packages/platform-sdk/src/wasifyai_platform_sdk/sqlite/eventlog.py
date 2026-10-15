"""Run event log on SQLite: the same behaviour as the Redis Streams log (ADR-0021).

`seq` is allocated per run, starting at 1, and is the SSE id, so `Last-Event-ID` reconnects work.
Events are kept for the same seven days as in Redis (`prune`)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.sqlite.engine import ensure_tables, now_iso, to_iso

TTL = timedelta(days=7)
POLL_S = 0.25  # a writer in another process cannot wake a reader here, so readers also poll
_BATCH = 200

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS run_events (
        tenant_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, run_id, seq)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_run_events_created ON run_events (created_at)",
)

_APPEND = text(
    """
    INSERT INTO run_events (tenant_id, run_id, seq, data, created_at)
    SELECT :t, :r, COALESCE(MAX(seq), 0) + 1, :d, :c
    FROM run_events WHERE tenant_id = :t AND run_id = :r
    RETURNING seq
    """
)
_READ = text(
    "SELECT seq, data FROM run_events WHERE tenant_id = :t AND run_id = :r AND seq > :a "
    "ORDER BY seq LIMIT :n"
)


class SqliteEventLog:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine
        self._changed: dict[tuple[str, str], asyncio.Event] = {}

    async def append(self, tenant_id: str, run_id: str, event: dict[str, Any]) -> int:
        await ensure_tables(self._engine, "run_events", _DDL)
        async with self._engine.begin() as conn:
            seq = (
                await conn.execute(
                    _APPEND,
                    {"t": tenant_id, "r": run_id, "d": json.dumps(event), "c": now_iso()},
                )
            ).scalar_one()
        if waiter := self._changed.pop((tenant_id, run_id), None):
            waiter.set()
        return int(seq)

    async def read(
        self, tenant_id: str, run_id: str, after: int, block_ms: int
    ) -> list[dict[str, Any]]:
        """Events with seq > `after`. Waits up to `block_ms` for one if none exist yet."""
        await ensure_tables(self._engine, "run_events", _DDL)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(block_ms, 1) / 1000
        key = (tenant_id, run_id)
        while True:
            # Register before reading, so an append between the read and the wait is not missed.
            waiter = self._changed.setdefault(key, asyncio.Event())
            async with self._engine.connect() as conn:
                rows = (
                    await conn.execute(
                        _READ, {"t": tenant_id, "r": run_id, "a": after, "n": _BATCH}
                    )
                ).all()
            if rows:
                return [{**json.loads(r[1]), "seq": int(r[0])} for r in rows]
            remaining = deadline - loop.time()
            if remaining <= 0:
                return []
            try:
                await asyncio.wait_for(waiter.wait(), timeout=min(remaining, POLL_S))
            except TimeoutError:
                pass

    async def last_seq(self, tenant_id: str, run_id: str) -> int:
        await ensure_tables(self._engine, "run_events", _DDL)
        async with self._engine.connect() as conn:
            value = (
                await conn.execute(
                    text(
                        "SELECT COALESCE(MAX(seq), 0) FROM run_events "
                        "WHERE tenant_id = :t AND run_id = :r"
                    ),
                    {"t": tenant_id, "r": run_id},
                )
            ).scalar_one()
        return int(value)

    async def prune(self, now: datetime | None = None) -> int:
        """Drop events older than the retention window. Returns how many rows went."""
        await ensure_tables(self._engine, "run_events", _DDL)
        cutoff = to_iso((now or datetime.now(UTC)) - TTL)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM run_events WHERE created_at < :c"), {"c": cutoff}
            )
        return result.rowcount or 0
