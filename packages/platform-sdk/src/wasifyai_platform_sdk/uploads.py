"""User uploads (ADR-0035): what we accept, what we keep, and how long.

An uploaded image is untrusted input and often a personal photo. It is decoded, rotated by its
EXIF orientation, stripped of every kind of metadata, scaled down and saved again as a PNG; what
the client sent, including its name, is never stored. Anything we cannot decode as a PNG, JPEG or
WebP is refused, whatever it claims to be."""

import io
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

MAX_PIXELS = 24_000_000  # refuses decompression bombs before the pixels are decoded
MAX_SIDE = 2048  # the models work at about one megapixel; more is only storage
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
UPLOADS_PER_HOUR = 60
UNUSED_LIFETIME = timedelta(hours=24)
UPLOAD_CREATED = "upload.created"


class UploadError(Exception):
    """A refused upload. `status` is the HTTP status; `message` is safe to show the user."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class ProcessedImage:
    png: bytes
    width: int
    height: int


def process_image(
    data: bytes, max_side: int = MAX_SIDE, max_pixels: int = MAX_PIXELS
) -> ProcessedImage:
    """The clean PNG that is stored in place of the upload."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ALLOWED_FORMATS:
                raise UploadError(415, "Please upload a PNG, JPEG or WebP image.")
            if im.width * im.height > max_pixels:
                raise UploadError(422, "That image has too many pixels. Try a smaller one.")
            im.load()
            oriented = ImageOps.exif_transpose(im)
            rgba = oriented.convert("RGBA")
    except UploadError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise UploadError(422, "That file could not be read as an image.") from None
    # Flatten any transparency onto white, then copy the pixels into a fresh image: nothing from
    # the original (EXIF, GPS, colour profile, comments) comes along.
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    flat.thumbnail((max_side, max_side))
    out = io.BytesIO()
    flat.save(out, "PNG", compress_level=6)
    return ProcessedImage(out.getvalue(), flat.width, flat.height)


@dataclass(frozen=True)
class UploadRecord:
    id: str
    tenant_id: str
    product_id: str
    user_id: str
    key: str  # relative to the owner's prefix, e.g. uploads/<id>.png
    bytes: int
    created_at: datetime | None = None
    consumed_at: datetime | None = None
    kind: str = "image"  # "image" or "audio" (ADR-0043)
    seconds: float | None = None  # the length of an audio upload

    @property
    def owner(self) -> tuple[str, str, str]:
        return (self.tenant_id, self.product_id, self.user_id)


def new_upload(
    tenant_id: str,
    product_id: str,
    user_id: str,
    size: int,
    kind: str = "image",
    seconds: float | None = None,
) -> UploadRecord:
    upload_id = str(uuid4())
    ext = "wav" if kind == "audio" else "png"
    return UploadRecord(
        upload_id, tenant_id, product_id, user_id, f"uploads/{upload_id}.{ext}", size,
        kind=kind, seconds=seconds,
    )  # fmt: skip


class UploadStore(Protocol):
    async def add(self, upload: UploadRecord) -> None: ...

    async def find(
        self, tenant_id: str, product_id: str, user_id: str, key: str
    ) -> UploadRecord | None:
        """The caller's own, unused upload with this key, or None."""
        ...

    async def consume(self, upload: UploadRecord) -> None:
        """Forget it: the file has been used (and deleted by the caller)."""
        ...

    async def expired(self, now: datetime, limit: int = 200) -> list[UploadRecord]:
        """Uploads never used and older than the unused lifetime."""
        ...


class InMemoryUploadStore:
    def __init__(self) -> None:
        self.rows: dict[str, UploadRecord] = {}

    async def add(self, upload: UploadRecord) -> None:
        self.rows[upload.id] = replace(upload, created_at=upload.created_at or datetime.now(UTC))

    async def find(
        self, tenant_id: str, product_id: str, user_id: str, key: str
    ) -> UploadRecord | None:
        return next(
            (
                u
                for u in self.rows.values()
                if (u.tenant_id, u.product_id, u.user_id, u.key)
                == (tenant_id, product_id, user_id, key)
                and u.consumed_at is None
            ),
            None,
        )

    async def consume(self, upload: UploadRecord) -> None:
        self.rows.pop(upload.id, None)

    async def expired(self, now: datetime, limit: int = 200) -> list[UploadRecord]:
        cutoff = now - UNUSED_LIFETIME
        old = [u for u in self.rows.values() if u.created_at and u.created_at < cutoff]
        return sorted(old, key=lambda u: u.created_at or now)[:limit]


class PostgresUploadStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    @staticmethod
    def _row(r) -> UploadRecord:
        return UploadRecord(
            id=str(r[0]), tenant_id=r[1], product_id=r[2], user_id=r[3], key=r[4], bytes=r[5],
            created_at=r[6], consumed_at=r[7], kind=r[8], seconds=r[9],
        )  # fmt: skip

    _COLUMNS = (
        "id, tenant_id, product_id, user_id, key, bytes, created_at, consumed_at, kind, seconds"
    )

    async def add(self, upload: UploadRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO uploads "
                    "(id, tenant_id, product_id, user_id, key, bytes, kind, seconds) "
                    "VALUES (:id, :t, :p, :u, :k, :b, :kind, :s)"
                ),
                {
                    "id": UUID(upload.id), "t": upload.tenant_id, "p": upload.product_id,
                    "u": upload.user_id, "k": upload.key, "b": upload.bytes,
                    "kind": upload.kind, "s": upload.seconds,
                },
            )  # fmt: skip

    async def find(
        self, tenant_id: str, product_id: str, user_id: str, key: str
    ) -> UploadRecord | None:
        sql = text(
            f"SELECT {self._COLUMNS} FROM uploads WHERE tenant_id = :t AND product_id = :p "
            "AND user_id = :u AND key = :k AND consumed_at IS NULL"
        )
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(sql, {"t": tenant_id, "p": product_id, "u": user_id, "k": key})
            ).first()
        return self._row(row) if row else None

    async def consume(self, upload: UploadRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(text("DELETE FROM uploads WHERE id = :id"), {"id": UUID(upload.id)})

    async def expired(self, now: datetime, limit: int = 200) -> list[UploadRecord]:
        sql = text(
            f"SELECT {self._COLUMNS} FROM uploads WHERE consumed_at IS NULL "
            "AND created_at < :cutoff ORDER BY created_at LIMIT :n"
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(sql, {"cutoff": now - UNUSED_LIFETIME, "n": limit})).all()
        return [self._row(r) for r in rows]


def upload_store(engine: AsyncEngine) -> UploadStore:
    """The upload store for the database the engine speaks to: Postgres in the web profile, SQLite
    in the desktop profile (ADR-0056)."""
    if engine.dialect.name == "sqlite":
        from wasifyai_platform_sdk.sqlite.uploads import SqliteUploadStore

        return SqliteUploadStore(engine)
    return PostgresUploadStore(engine)


class UploadLimiter(Protocol):
    async def allow(self, tenant_id: str, user_id: str) -> bool: ...


class InMemoryUploadLimiter:
    def __init__(self, per_hour: int = UPLOADS_PER_HOUR, clock=time.time):
        self._max, self._clock = per_hour, clock
        self._seen: dict[tuple[str, str, int], int] = {}

    async def allow(self, tenant_id: str, user_id: str) -> bool:
        hour = int(self._clock() // 3600)
        key = (tenant_id, user_id, hour)
        self._seen = {k: v for k, v in self._seen.items() if k[2] == hour}
        self._seen[key] = self._seen.get(key, 0) + 1
        return self._seen[key] <= self._max


class RedisUploadLimiter:
    """A counter per user per clock hour, in Redis, so every API replica shares it. `name` keeps
    separate limits apart (uploads, prompt enhancements)."""

    def __init__(self, redis, per_hour: int = UPLOADS_PER_HOUR, clock=time.time, name="uploads"):
        self._r, self._max, self._clock, self._name = redis, per_hour, clock, name

    async def allow(self, tenant_id: str, user_id: str) -> bool:
        key = f"wasifyai:{self._name}:{tenant_id}:{user_id}:{int(self._clock() // 3600)}"
        count = await self._r.incr(key)
        if count == 1:
            await self._r.expire(key, 3700)
        return int(count) <= self._max
