"""The safeguards switch (ADR-0047): one system-wide setting for content moderation and quotas.

Off by default (local and staging). A deployment forces it on (production) with
`SAFEGUARDS_FORCE_ON=true`; the stored value is then ignored and the admin cannot change it. The
value is read often (every request), so it is cached for a few seconds; a change in one API replica
reaches the others within that time."""

import json
import time
from typing import Protocol

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

KEY = "safeguards.enabled"
CACHE_SECONDS = 5.0


class SafeguardsStatus(BaseModel):
    enabled: bool
    forced: bool  # on, because the deployment says so: the switch cannot be changed here


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


class Safeguards:
    def __init__(self, store: SettingsStore, force_on: bool = False):
        self._store = store
        self._forced = force_on
        self._cached: tuple[float, bool] | None = None

    async def enabled(self) -> bool:
        """The one question graphs ask. If the stored value cannot be read it fails closed (on)."""
        if self._forced:
            return True
        now = time.monotonic()
        if self._cached is not None and now - self._cached[0] < CACHE_SECONDS:
            return self._cached[1]
        try:
            value = (await self._store.get(KEY)) is True
        except Exception:
            return True
        self._cached = (now, value)
        return value

    async def status(self) -> SafeguardsStatus:
        return SafeguardsStatus(enabled=await self.enabled(), forced=self._forced)

    async def set(self, enabled: bool, by: str) -> SafeguardsStatus:
        if self._forced:
            raise ForcedOn
        await self._store.put(KEY, enabled, by)
        self._cached = (time.monotonic(), enabled)
        return await self.status()


class ForcedOn(Exception):
    """The deployment forces the safeguards on."""
