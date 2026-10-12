"""Finished images: storage, the daily quota, and thumbnails."""

import asyncio
import io
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import RunContext, start_of_day_utc, sum_usage

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
    created_at: datetime | None = field(default=None, compare=False)  # set by the database


class ImageStore(Protocol):
    async def add(self, image: ImageRecord) -> None: ...

    async def list(
        self, tenant_id: str, user_id: str, limit: int, before: datetime | None
    ) -> list[ImageRecord]:
        """The user's images, newest first, strictly older than `before`."""
        ...

    async def get(self, tenant_id: str, user_id: str, image_id: str) -> ImageRecord | None: ...

    async def delete(self, tenant_id: str, user_id: str, image_id: str) -> None: ...


_COLUMNS = (
    "id, tenant_id, product_id, user_id, thread_id, run_id, mode, prompt, width, height, "
    "image_key, thumb_key, created_at"
)


def _record(r) -> ImageRecord:
    return ImageRecord(
        id=str(r[0]), tenant_id=r[1], product_id=r[2], user_id=r[3], thread_id=r[4], run_id=r[5],
        mode=r[6], prompt=r[7], width=r[8], height=r[9], image_key=r[10], thumb_key=r[11],
        created_at=r[12],
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
                                        prompt, width, height, image_key, thumb_key)
                    VALUES (:id, :tenant_id, :product_id, :user_id, :thread_id, :run_id, :mode,
                            :prompt, :width, :height, :image_key, :thumb_key)
                    """
                ),
                {
                    **{k: v for k, v in image.__dict__.items() if k != "created_at"},
                    "id": UUID(image.id),
                },
            )

    async def list(
        self, tenant_id: str, user_id: str, limit: int, before: datetime | None
    ) -> list[ImageRecord]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    f"""
                    SELECT {_COLUMNS} FROM images
                    WHERE tenant_id = :t AND product_id = 'wasifyai-image' AND user_id = :u
                      AND (CAST(:before AS timestamptz) IS NULL OR created_at < :before)
                    ORDER BY created_at DESC, id DESC LIMIT :limit
                    """
                ),
                {"t": tenant_id, "u": user_id, "before": before, "limit": limit},
            )
            return [_record(r) for r in rows]

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


class InMemoryImageStore:
    def __init__(self) -> None:
        self.images: list[ImageRecord] = []

    async def add(self, image: ImageRecord) -> None:
        self.images.append(replace(image, created_at=image.created_at or datetime.now(UTC)))

    async def list(
        self, tenant_id: str, user_id: str, limit: int, before: datetime | None
    ) -> list[ImageRecord]:
        mine = [i for i in self.images if (i.tenant_id, i.user_id) == (tenant_id, user_id)]
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
