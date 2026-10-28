"""Finished images: storage, the daily quota, and thumbnails."""

import asyncio
import io
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import RunContext, start_of_day_utc, sum_usage
from wasifyai_platform_sdk.sqlite import (
    Migration,
    from_iso,
    is_sqlite,
    migrate,
    now_iso,
    to_iso,
)

IMAGE_CREATED = "image.created"
THUMB_PX = 480


@dataclass(frozen=True)
class ImageRecord:
    id: str
    tenant_id: str
    product_id: str
    user_id: str
    thread_id: str | None
    run_id: str | None
    mode: str  # "text" or "image"
    prompt: str
    width: int
    height: int
    image_key: str  # relative to the user's storage prefix
    thumb_key: str
    # What made the image (versioned JSON): prompt, mode, size, width, height, seed. None on rows
    # from before recipes existed.
    recipe: dict | None = None
    favourite: bool = False
    # the picture of the library this one was made from (Edit, Inpaint, the first of Reference),
    # when the person started from one; None for a picture made from words or from a file they
    # added (ADR-0093, U8)
    source_id: str | None = None
    created_at: datetime | None = field(default=None, compare=False)  # set by the database


class ImageStore(Protocol):
    async def add(self, image: ImageRecord) -> None: ...

    async def list(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        before: datetime | None,
        favourites_only: bool = False,
        source_id: str | None = None,
    ) -> list[ImageRecord]:
        """The user's images, newest first, strictly older than `before`; with `source_id`, only the
        ones made from that picture."""
        ...

    async def set_favourite(
        self, tenant_id: str, user_id: str, image_id: str, favourite: bool
    ) -> bool:
        """Mark or unmark; False when the user has no such image."""
        ...

    async def get(self, tenant_id: str, user_id: str, image_id: str) -> ImageRecord | None: ...

    async def delete(self, tenant_id: str, user_id: str, image_id: str) -> None: ...


_COLUMNS = (
    "id, tenant_id, product_id, user_id, thread_id, run_id, mode, prompt, width, height, "
    "image_key, thumb_key, recipe, favourite, created_at, source_id"
)


def _uuid_or_none(value: str | None) -> UUID | None:
    """An id as Postgres keeps it, or None when there is none or it is not an id."""
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _recipe_of(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _record(r) -> ImageRecord:
    return ImageRecord(
        id=str(r[0]), tenant_id=r[1], product_id=r[2], user_id=r[3], thread_id=r[4], run_id=r[5],
        mode=r[6], prompt=r[7], width=r[8], height=r[9], image_key=r[10], thumb_key=r[11],
        recipe=_recipe_of(r[12]), favourite=bool(r[13]), created_at=r[14],
        source_id=str(r[15]) if r[15] else None,
    )  # fmt: skip


class PostgresImageStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def add(self, image: ImageRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO images (id, tenant_id, product_id, user_id, thread_id, run_id, mode,
                                        prompt, width, height, image_key, thumb_key, recipe,
                                        favourite, source_id)
                    VALUES (:id, :tenant_id, :product_id, :user_id, :thread_id, :run_id, :mode,
                            :prompt, :width, :height, :image_key, :thumb_key, :recipe, :favourite,
                            :source_id)
                    """
                ),
                {
                    **{k: v for k, v in image.__dict__.items() if k != "created_at"},
                    "id": UUID(image.id),
                    "recipe": json.dumps(image.recipe) if image.recipe is not None else None,
                    "source_id": _uuid_or_none(image.source_id),
                },
            )

    async def list(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        before: datetime | None,
        favourites_only: bool = False,
        source_id: str | None = None,
    ) -> list[ImageRecord]:
        if source_id is not None and _uuid_or_none(source_id) is None:
            return []  # not an id: nothing was made from it
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    f"""
                    SELECT {_COLUMNS} FROM images
                    WHERE tenant_id = :t AND product_id = 'wasifyai-image' AND user_id = :u
                      AND (CAST(:before AS timestamptz) IS NULL OR created_at < :before)
                      AND (NOT :fav OR favourite)
                      AND (CAST(:src AS uuid) IS NULL OR source_id = CAST(:src AS uuid))
                    ORDER BY created_at DESC, id DESC LIMIT :limit
                    """
                ),
                {
                    "t": tenant_id, "u": user_id, "before": before, "limit": limit,
                    "fav": favourites_only, "src": _uuid_or_none(source_id),
                },
            )  # fmt: skip
            return [_record(r) for r in rows]

    async def set_favourite(
        self, tenant_id: str, user_id: str, image_id: str, favourite: bool
    ) -> bool:
        try:
            iid = UUID(image_id)
        except ValueError:
            return False
        async with self._engine.begin() as conn:
            res = await conn.execute(
                text(
                    "UPDATE images SET favourite = :f WHERE id = :id AND tenant_id = :t "
                    "AND user_id = :u AND product_id = 'wasifyai-image'"
                ),
                {"f": favourite, "id": iid, "t": tenant_id, "u": user_id},
            )
            return (res.rowcount or 0) > 0

    async def get(self, tenant_id: str, user_id: str, image_id: str) -> ImageRecord | None:
        try:
            iid = UUID(image_id)
        except ValueError:
            return None
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM images WHERE id = :id AND tenant_id = :t "
                        "AND user_id = :u AND product_id = 'wasifyai-image'"
                    ),
                    {"id": iid, "t": tenant_id, "u": user_id},
                )
            ).first()
            return _record(row) if row else None

    async def delete(self, tenant_id: str, user_id: str, image_id: str) -> None:
        try:
            iid = UUID(image_id)
        except ValueError:
            return
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM images WHERE id = :id AND tenant_id = :t AND user_id = :u"),
                {"id": iid, "t": tenant_id, "u": user_id},
            )


_SQLITE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS images (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        thread_id TEXT,
        run_id TEXT,
        mode TEXT NOT NULL,
        prompt TEXT NOT NULL,
        width INTEGER NOT NULL,
        height INTEGER NOT NULL,
        image_key TEXT NOT NULL,
        thumb_key TEXT NOT NULL,
        recipe TEXT,
        favourite INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        source_id TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_images_user_created "
    "ON images (tenant_id, product_id, user_id, created_at)",
)


_SQLITE_NEW_COLUMNS = {
    "recipe": "TEXT",
    "favourite": "INTEGER NOT NULL DEFAULT 0",
    "source_id": "TEXT",
}

# the store's shape before the migration runner (stage J1); a change is a new Migration(2, ...)
SQLITE_MIGRATIONS = (Migration(1, _SQLITE_DDL, columns={"images": _SQLITE_NEW_COLUMNS}),)


class SqliteImageStore:
    """The same records on the SQLite file of the desktop profile (ADR-0056)."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        await migrate(self._engine, "images", SQLITE_MIGRATIONS)

    @staticmethod
    def _record(r) -> ImageRecord:
        return ImageRecord(
            id=r[0], tenant_id=r[1], product_id=r[2], user_id=r[3], thread_id=r[4], run_id=r[5],
            mode=r[6], prompt=r[7], width=r[8], height=r[9], image_key=r[10], thumb_key=r[11],
            recipe=_recipe_of(r[12]), favourite=bool(r[13]), created_at=from_iso(r[14]),
            source_id=r[15] or None,
        )  # fmt: skip

    async def add(self, image: ImageRecord) -> None:
        await self._ready()
        values = {k: v for k, v in image.__dict__.items() if k not in ("created_at", "recipe")}
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO images (id, tenant_id, product_id, user_id, thread_id, run_id, mode,
                                        prompt, width, height, image_key, thumb_key, recipe,
                                        favourite, created_at, source_id)
                    VALUES (:id, :tenant_id, :product_id, :user_id, :thread_id, :run_id, :mode,
                            :prompt, :width, :height, :image_key, :thumb_key, :recipe,
                            :favourite, :created_at, :source_id)
                    """
                ),
                {
                    **values,
                    "recipe": json.dumps(image.recipe) if image.recipe is not None else None,
                    "favourite": int(image.favourite),
                    "created_at": to_iso(image.created_at) if image.created_at else now_iso(),
                },
            )

    async def list(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        before: datetime | None,
        favourites_only: bool = False,
        source_id: str | None = None,
    ) -> list[ImageRecord]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    f"""
                    SELECT {_COLUMNS} FROM images
                    WHERE tenant_id = :t AND product_id = 'wasifyai-image' AND user_id = :u
                      AND (:before IS NULL OR created_at < :before)
                      AND (:fav = 0 OR favourite = 1)
                      AND (:src IS NULL OR source_id = :src)
                    ORDER BY created_at DESC, id DESC LIMIT :limit
                    """
                ),
                {
                    "t": tenant_id, "u": user_id, "limit": limit,
                    "before": to_iso(before) if before else None,
                    "fav": int(favourites_only), "src": source_id,
                },
            )  # fmt: skip
            return [self._record(r) for r in rows]

    async def set_favourite(
        self, tenant_id: str, user_id: str, image_id: str, favourite: bool
    ) -> bool:
        await self._ready()
        async with self._engine.begin() as conn:
            res = await conn.execute(
                text(
                    "UPDATE images SET favourite = :f WHERE id = :id AND tenant_id = :t "
                    "AND user_id = :u AND product_id = 'wasifyai-image'"
                ),
                {"f": int(favourite), "id": image_id, "t": tenant_id, "u": user_id},
            )
            return (res.rowcount or 0) > 0

    async def get(self, tenant_id: str, user_id: str, image_id: str) -> ImageRecord | None:
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM images WHERE id = :id AND tenant_id = :t "
                        "AND user_id = :u AND product_id = 'wasifyai-image'"
                    ),
                    {"id": image_id, "t": tenant_id, "u": user_id},
                )
            ).first()
            return self._record(row) if row else None

    async def delete(self, tenant_id: str, user_id: str, image_id: str) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM images WHERE id = :id AND tenant_id = :t AND user_id = :u"),
                {"id": image_id, "t": tenant_id, "u": user_id},
            )


def image_store(engine: AsyncEngine) -> ImageStore:
    """The store for the database the engine speaks to: Postgres in the web profile, SQLite in the
    desktop profile (ADR-0056). Callers do not know which."""
    return SqliteImageStore(engine) if is_sqlite(engine) else PostgresImageStore(engine)


class InMemoryImageStore:
    def __init__(self) -> None:
        self.images: list[ImageRecord] = []

    async def add(self, image: ImageRecord) -> None:
        self.images.append(replace(image, created_at=image.created_at or datetime.now(UTC)))

    async def list(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        before: datetime | None,
        favourites_only: bool = False,
        source_id: str | None = None,
    ) -> list[ImageRecord]:
        mine = [i for i in self.images if (i.tenant_id, i.user_id) == (tenant_id, user_id)]
        mine = [i for i in mine if i.favourite or not favourites_only]
        mine = [i for i in mine if source_id is None or i.source_id == source_id]
        mine = [i for i in mine if before is None or (i.created_at and i.created_at < before)]
        return sorted(mine, key=lambda i: (i.created_at, i.id), reverse=True)[:limit]

    async def get(self, tenant_id: str, user_id: str, image_id: str) -> ImageRecord | None:
        return next(
            (
                i
                for i in self.images
                if (i.tenant_id, i.user_id, i.id) == (tenant_id, user_id, image_id)
            ),
            None,
        )

    async def set_favourite(
        self, tenant_id: str, user_id: str, image_id: str, favourite: bool
    ) -> bool:
        for n, i in enumerate(self.images):
            if (i.tenant_id, i.user_id, i.id) == (tenant_id, user_id, image_id):
                self.images[n] = replace(i, favourite=favourite)
                return True
        return False

    async def delete(self, tenant_id: str, user_id: str, image_id: str) -> None:
        self.images = [
            i
            for i in self.images
            if (i.tenant_id, i.user_id, i.id) != (tenant_id, user_id, image_id)
        ]


class Quota(Protocol):
    async def used_today(self, ctx: RunContext) -> int: ...


class UsageQuota:
    """Images made today (UTC), counted from the `image.created` usage events."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def used_today(self, ctx: RunContext) -> int:
        return int(
            await sum_usage(
                self._engine, ctx.tenant_id, ctx.product_id, ctx.user_id, IMAGE_CREATED,
                start_of_day_utc(),
            )
        )  # fmt: skip


class FixedQuota:
    """For tests: pretend the user already made `used` images today."""

    def __init__(self, used: int = 0) -> None:
        self.used = used

    async def used_today(self, ctx: RunContext) -> int:
        return self.used


def measure_and_thumbnail(png: bytes) -> tuple[int, int, bytes]:
    """The picture's size and a small JPEG for the gallery grid (the picture is over a megabyte)."""
    with Image.open(io.BytesIO(png)) as im:
        width, height = im.size
        rgb = im.convert("RGB")
    rgb.thumbnail((THUMB_PX, THUMB_PX))
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=82, optimize=True)
    return width, height, out.getvalue()


async def thumbnail_of(png: bytes) -> tuple[int, int, bytes]:
    return await asyncio.to_thread(measure_and_thumbnail, png)
