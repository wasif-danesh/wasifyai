"""Song storage and the daily quota."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import RunContext, start_of_day_utc, sum_usage

SONG_CREATED = "song.created"


@dataclass(frozen=True)
class SongRecord:
    id: str
    tenant_id: str
    product_id: str
    user_id: str
    thread_id: str | None
    run_id: str | None
    title: str
    lyrics: str
    style: str
    audio_key: str  # relative to the user's storage prefix
    cover_key: str | None
    created_at: datetime | None = field(default=None, compare=False)  # set by the database


class SongStore(Protocol):
    async def add(self, song: SongRecord) -> None: ...

    async def list(
        self, tenant_id: str, user_id: str, limit: int, before: datetime | None
    ) -> list[SongRecord]:
        """The user's songs, newest first, strictly older than `before`."""
        ...

    async def get(self, tenant_id: str, user_id: str, song_id: str) -> SongRecord | None: ...


_COLUMNS = (
    "id, tenant_id, product_id, user_id, thread_id, run_id, title, lyrics, style, "
    "audio_key, cover_key, created_at"
)


def _record(r) -> SongRecord:
    return SongRecord(
        id=str(r[0]), tenant_id=r[1], product_id=r[2], user_id=r[3], thread_id=r[4], run_id=r[5],
        title=r[6], lyrics=r[7], style=r[8], audio_key=r[9], cover_key=r[10], created_at=r[11],
    )  # fmt: skip


class PostgresSongStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def add(self, song: SongRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO songs (id, tenant_id, product_id, user_id, thread_id, run_id,
                                       title, lyrics, style, audio_key, cover_key)
                    VALUES (:id, :tenant_id, :product_id, :user_id, :thread_id, :run_id,
                            :title, :lyrics, :style, :audio_key, :cover_key)
                    """
                ),
                {
                    **{k: v for k, v in song.__dict__.items() if k != "created_at"},
                    "id": UUID(song.id),
                },
            )

    async def list(
        self, tenant_id: str, user_id: str, limit: int, before: datetime | None
    ) -> list[SongRecord]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    f"""
                    SELECT {_COLUMNS} FROM songs
                    WHERE tenant_id = :t AND product_id = 'wasifyai-music' AND user_id = :u
                      AND (CAST(:before AS timestamptz) IS NULL OR created_at < :before)
                    ORDER BY created_at DESC, id DESC LIMIT :limit
                    """
                ),
                {"t": tenant_id, "u": user_id, "before": before, "limit": limit},
            )
            return [_record(r) for r in rows]

    async def get(self, tenant_id: str, user_id: str, song_id: str) -> SongRecord | None:
        try:
            sid = UUID(song_id)
        except ValueError:
            return None
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    f"""
                    SELECT {_COLUMNS} FROM songs
                    WHERE id = :id AND tenant_id = :t AND user_id = :u
                      AND product_id = 'wasifyai-music'
                    """
                ),
                {"id": sid, "t": tenant_id, "u": user_id},
            )
            row = rows.first()
            return _record(row) if row else None


class InMemorySongStore:
    def __init__(self) -> None:
        self.songs: list[SongRecord] = []

    async def add(self, song: SongRecord) -> None:
        self.songs.append(replace(song, created_at=song.created_at or datetime.now(UTC)))

    async def list(
        self, tenant_id: str, user_id: str, limit: int, before: datetime | None
    ) -> list[SongRecord]:
        mine = [s for s in self.songs if (s.tenant_id, s.user_id) == (tenant_id, user_id)]
        mine = [s for s in mine if before is None or (s.created_at and s.created_at < before)]
        return sorted(mine, key=lambda s: (s.created_at, s.id), reverse=True)[:limit]

    async def get(self, tenant_id: str, user_id: str, song_id: str) -> SongRecord | None:
        return next(
            (
                s
                for s in self.songs
                if (s.tenant_id, s.user_id, s.id) == (tenant_id, user_id, song_id)
            ),
            None,
        )


class Quota(Protocol):
    async def used_today(self, ctx: RunContext) -> int: ...


class UsageQuota:
    """Songs created today (UTC), counted from the `song.created` usage events."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def used_today(self, ctx: RunContext) -> int:
        return int(
            await sum_usage(
                self._engine,
                ctx.tenant_id,
                ctx.product_id,
                ctx.user_id,
                SONG_CREATED,
                start_of_day_utc(),
            )
        )


class FixedQuota:
    """For tests: pretend the user already made `used` songs today."""

    def __init__(self, used: int = 0) -> None:
        self.used = used

    async def used_today(self, ctx: RunContext) -> int:
        return self.used
