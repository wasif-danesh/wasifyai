"""System-wide settings by key (the `system_settings` table on the web, a SQLite table on the
desktop): what the Model hub, discovery, web search and the desktop's own switches keep."""

import json
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class SettingsStore(Protocol):
    async def get(self, key: str) -> object | None: ...
    async def put(self, key: str, value: object, by: str) -> None: ...


class InMemorySettingsStore:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values: dict[str, object] = dict(values or {})

    async def get(self, key: str) -> object | None:
        return self.values.get(key)

    async def put(self, key: str, value: object, by: str) -> None:
        self.values[key] = value


class PostgresSettingsStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def get(self, key: str) -> object | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT value FROM system_settings WHERE key = :k"), {"k": key}
                )
            ).first()
        return None if row is None else row[0]

    async def put(self, key: str, value: object, by: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO system_settings (key, value, updated_by) "
                    "VALUES (:k, CAST(:v AS jsonb), :by) ON CONFLICT (key) DO UPDATE "
                    "SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
                    "updated_at = now()"
                ),
                {"k": key, "v": json.dumps(value), "by": by},
            )
