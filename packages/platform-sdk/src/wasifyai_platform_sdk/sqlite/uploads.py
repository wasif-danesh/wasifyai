"""Uploads on SQLite (same rules as PostgresUploadStore, ADR-0035)."""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.sqlite.engine import Migration, from_iso, migrate, now_iso, to_iso
from wasifyai_platform_sdk.uploads import UNUSED_LIFETIME, UploadRecord

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS uploads (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        key TEXT NOT NULL,
        bytes INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        consumed_at TEXT,
        kind TEXT NOT NULL DEFAULT 'image',
        seconds REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_uploads_owner_key "
    "ON uploads (tenant_id, product_id, user_id, key)",
    "CREATE INDEX IF NOT EXISTS ix_uploads_created ON uploads (created_at)",
)

# the store's shape before the migration runner (stage J1); a change is a new Migration(2, ...)
_MIGRATIONS = (Migration(1, _DDL),)

_COLUMNS = "id, tenant_id, product_id, user_id, key, bytes, created_at, consumed_at, kind, seconds"


def _row(r) -> UploadRecord:
    return UploadRecord(
        id=r[0], tenant_id=r[1], product_id=r[2], user_id=r[3], key=r[4], bytes=r[5],
        created_at=from_iso(r[6]), consumed_at=from_iso(r[7]), kind=r[8], seconds=r[9],
    )  # fmt: skip


class SqliteUploadStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        await migrate(self._engine, "uploads", _MIGRATIONS)

    async def add(self, upload: UploadRecord) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO uploads "
                    "(id, tenant_id, product_id, user_id, key, bytes, created_at, kind, seconds) "
                    "VALUES (:id, :t, :p, :u, :k, :b, :c, :kind, :s)"
                ),
                {
                    "id": upload.id, "t": upload.tenant_id, "p": upload.product_id,
                    "u": upload.user_id, "k": upload.key, "b": upload.bytes,
                    "c": to_iso(upload.created_at) if upload.created_at else now_iso(),
                    "kind": upload.kind, "s": upload.seconds,
                },
            )  # fmt: skip

    async def find(
        self, tenant_id: str, product_id: str, user_id: str, key: str
    ) -> UploadRecord | None:
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM uploads WHERE tenant_id = :t AND product_id = :p "
                        "AND user_id = :u AND key = :k AND consumed_at IS NULL"
                    ),
                    {"t": tenant_id, "p": product_id, "u": user_id, "k": key},
                )
            ).first()
        return _row(row) if row else None

    async def consume(self, upload: UploadRecord) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(text("DELETE FROM uploads WHERE id = :id"), {"id": upload.id})

    async def expired(self, now: datetime, limit: int = 200) -> list[UploadRecord]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM uploads WHERE consumed_at IS NULL "
                        "AND created_at < :cutoff ORDER BY created_at LIMIT :n"
                    ),
                    {"cutoff": to_iso(now - UNUSED_LIFETIME), "n": limit},
                )
            ).all()
        return [_row(r) for r in rows]
