"""Clips: storage, the daily quota, the one-at-a-time rule and the poster picture.

A row exists from the moment a run starts (status "working") so that the site can show "being made"
on any page (ADR-0037). A row that stays "working" for over half an hour belongs to a run that died;
it is marked "failed" the next time anyone reads the table."""

import asyncio
import logging
import re
import tempfile
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import RunContext, start_of_day_utc, sum_usage

log = logging.getLogger(__name__)

VIDEO_CREATED = "video.created"
POSTER_PX = 480
STALE_AFTER = timedelta(minutes=30)
STALE_MESSAGE = "This took too long and was stopped. Please try again."
FFMPEG_TIMEOUT_S = 60


@dataclass(frozen=True)
class VideoRecord:
    id: str
    tenant_id: str
    product_id: str
    user_id: str
    thread_id: str | None
    run_id: str | None
    mode: str  # "text" or "image"
    status: str  # "working" | "done" | "failed"
    prompt: str
    seconds: int
    frames: int
    fps: int
    width: int | None = None
    height: int | None = None
    video_key: str | None = None  # relative to the user's storage prefix
    poster_key: str | None = None
    error: str | None = None
    created_at: datetime | None = field(default=None, compare=False)  # set by the database


class VideoStore(Protocol):
    async def add(self, video: VideoRecord) -> None: ...

    async def finish(
        self,
        tenant_id: str,
        video_id: str,
        width: int,
        height: int,
        video_key: str,
        poster_key: str,
    ) -> None: ...

    async def fail(self, tenant_id: str, video_id: str, message: str) -> None: ...

    async def list(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        before: datetime | None,
        status: str | None = None,
    ) -> list[VideoRecord]:
        """The user's clips, newest first, strictly older than `before`."""
        ...

    async def get(self, tenant_id: str, user_id: str, video_id: str) -> VideoRecord | None: ...

    async def delete(self, tenant_id: str, user_id: str, video_id: str) -> None: ...

    async def working_count(self, tenant_id: str, user_id: str) -> int: ...


_COLUMNS = (
    "id, tenant_id, product_id, user_id, thread_id, run_id, mode, status, prompt, seconds, frames, "
    "fps, width, height, video_key, poster_key, error, created_at"
)


def _record(r) -> VideoRecord:
    return VideoRecord(
        id=str(r[0]), tenant_id=r[1], product_id=r[2], user_id=r[3], thread_id=r[4], run_id=r[5],
        mode=r[6], status=r[7], prompt=r[8], seconds=r[9], frames=r[10], fps=r[11], width=r[12],
        height=r[13], video_key=r[14], poster_key=r[15], error=r[16], created_at=r[17],
    )  # fmt: skip


class PostgresVideoStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _expire(self, conn) -> None:
        await conn.execute(
            text(
                "UPDATE videos SET status = 'failed', error = :msg WHERE status = 'working' "
                "AND product_id = 'wasifyai-video' AND created_at < :cutoff"
            ),
            {"msg": STALE_MESSAGE, "cutoff": datetime.now(UTC) - STALE_AFTER},
        )

    async def add(self, video: VideoRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO videos (id, tenant_id, product_id, user_id, thread_id, run_id, mode,
                                        status, prompt, seconds, frames, fps)
                    VALUES (:id, :tenant_id, :product_id, :user_id, :thread_id, :run_id, :mode,
                            :status, :prompt, :seconds, :frames, :fps)
                    """
                ),
                {
                    "id": UUID(video.id), "tenant_id": video.tenant_id,
                    "product_id": video.product_id, "user_id": video.user_id,
                    "thread_id": video.thread_id, "run_id": video.run_id, "mode": video.mode,
                    "status": video.status, "prompt": video.prompt, "seconds": video.seconds,
                    "frames": video.frames, "fps": video.fps,
                },
            )  # fmt: skip

    async def finish(
        self,
        tenant_id: str,
        video_id: str,
        width: int,
        height: int,
        video_key: str,
        poster_key: str,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE videos SET status = 'done', width = :w, height = :h, video_key = :v, "
                    "poster_key = :p, error = NULL WHERE id = :id AND tenant_id = :t"
                ),
                {"w": width, "h": height, "v": video_key, "p": poster_key,
                 "id": UUID(video_id), "t": tenant_id},
            )  # fmt: skip

    async def fail(self, tenant_id: str, video_id: str, message: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE videos SET status = 'failed', error = :m "
                    "WHERE id = :id AND tenant_id = :t AND status = 'working'"
                ),
                {"m": message, "id": UUID(video_id), "t": tenant_id},
            )

    async def list(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        before: datetime | None,
        status: str | None = None,
    ) -> list[VideoRecord]:
        async with self._engine.begin() as conn:
            await self._expire(conn)
            rows = await conn.execute(
                text(
                    f"""
                    SELECT {_COLUMNS} FROM videos
                    WHERE tenant_id = :t AND product_id = 'wasifyai-video' AND user_id = :u
                      AND (CAST(:before AS timestamptz) IS NULL OR created_at < :before)
                      AND (CAST(:status AS text) IS NULL OR status = :status)
                    ORDER BY created_at DESC, id DESC LIMIT :limit
                    """
                ),
                {"t": tenant_id, "u": user_id, "before": before, "status": status, "limit": limit},
            )
            return [_record(r) for r in rows]

    async def get(self, tenant_id: str, user_id: str, video_id: str) -> VideoRecord | None:
        try:
            vid = UUID(video_id)
        except ValueError:
            return None
        async with self._engine.begin() as conn:
            await self._expire(conn)
            row = (
                await conn.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM videos WHERE id = :id AND tenant_id = :t "
                        "AND user_id = :u AND product_id = 'wasifyai-video'"
                    ),
                    {"id": vid, "t": tenant_id, "u": user_id},
                )
            ).first()
            return _record(row) if row else None

    async def delete(self, tenant_id: str, user_id: str, video_id: str) -> None:
        try:
            vid = UUID(video_id)
        except ValueError:
            return
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM videos WHERE id = :id AND tenant_id = :t AND user_id = :u"),
                {"id": vid, "t": tenant_id, "u": user_id},
            )

    async def working_count(self, tenant_id: str, user_id: str) -> int:
        async with self._engine.begin() as conn:
            await self._expire(conn)
            row = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM videos WHERE tenant_id = :t AND user_id = :u "
                        "AND product_id = 'wasifyai-video' AND status = 'working'"
                    ),
                    {"t": tenant_id, "u": user_id},
                )
            ).one()
            return int(row[0])


class InMemoryVideoStore:
    def __init__(self) -> None:
        self.videos: list[VideoRecord] = []

    def _expire(self) -> None:
        cutoff = datetime.now(UTC) - STALE_AFTER
        self.videos = [
            replace(v, status="failed", error=STALE_MESSAGE)
            if v.status == "working" and v.created_at and v.created_at < cutoff
            else v
            for v in self.videos
        ]

    def _update(self, tenant_id: str, video_id: str, **changes) -> None:
        self.videos = [
            replace(v, **changes) if (v.tenant_id, v.id) == (tenant_id, video_id) else v
            for v in self.videos
        ]

    async def add(self, video: VideoRecord) -> None:
        self.videos.append(replace(video, created_at=video.created_at or datetime.now(UTC)))

    async def finish(
        self,
        tenant_id: str,
        video_id: str,
        width: int,
        height: int,
        video_key: str,
        poster_key: str,
    ) -> None:
        self._update(
            tenant_id, video_id, status="done", width=width, height=height,
            video_key=video_key, poster_key=poster_key, error=None,
        )  # fmt: skip

    async def fail(self, tenant_id: str, video_id: str, message: str) -> None:
        self.videos = [
            replace(v, status="failed", error=message)
            if (v.tenant_id, v.id, v.status) == (tenant_id, video_id, "working")
            else v
            for v in self.videos
        ]

    async def list(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        before: datetime | None,
        status: str | None = None,
    ) -> list[VideoRecord]:
        self._expire()
        mine = [v for v in self.videos if (v.tenant_id, v.user_id) == (tenant_id, user_id)]
        mine = [v for v in mine if before is None or (v.created_at and v.created_at < before)]
        mine = [v for v in mine if status is None or v.status == status]
        return sorted(mine, key=lambda v: (v.created_at, v.id), reverse=True)[:limit]

    async def get(self, tenant_id: str, user_id: str, video_id: str) -> VideoRecord | None:
        self._expire()
        return next(
            (
                v
                for v in self.videos
                if (v.tenant_id, v.user_id, v.id) == (tenant_id, user_id, video_id)
            ),
            None,
        )

    async def delete(self, tenant_id: str, user_id: str, video_id: str) -> None:
        self.videos = [
            v
            for v in self.videos
            if (v.tenant_id, v.user_id, v.id) != (tenant_id, user_id, video_id)
        ]

    async def working_count(self, tenant_id: str, user_id: str) -> int:
        self._expire()
        return sum(
            1
            for v in self.videos
            if (v.tenant_id, v.user_id, v.status) == (tenant_id, user_id, "working")
        )


class Quota(Protocol):
    async def used_today(self, ctx: RunContext) -> int: ...


class UsageQuota:
    """Clips made today (UTC), counted from the `video.created` usage events."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def used_today(self, ctx: RunContext) -> int:
        return int(
            await sum_usage(
                self._engine, ctx.tenant_id, ctx.product_id, ctx.user_id, VIDEO_CREATED,
                start_of_day_utc(),
            )
        )  # fmt: skip


class FixedQuota:
    """For tests: pretend the user already made `used` clips today."""

    def __init__(self, used: int = 0) -> None:
        self.used = used

    async def used_today(self, ctx: RunContext) -> int:
        return self.used


class PosterError(Exception):
    """ffmpeg could not read the clip. The details go to the log; the message is safe to show."""


def ffmpeg_path() -> str:
    """The static ffmpeg that comes with `imageio-ffmpeg`, else whatever is on the PATH."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil

        return shutil.which("ffmpeg") or "ffmpeg"


_SIZE = re.compile(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})")


async def poster_of(mp4: bytes) -> tuple[int, int, bytes]:
    """The clip's size and a small JPEG of its first frame, both from ffmpeg."""
    exe = ffmpeg_path()
    with tempfile.TemporaryDirectory(prefix="wasifyai-video-") as tmp:
        src, out = Path(tmp) / "clip.mp4", Path(tmp) / "poster.jpg"
        src.write_bytes(mp4)
        try:
            proc = await asyncio.create_subprocess_exec(
                exe, "-hide_banner", "-y", "-i", str(src), "-frames:v", "1",
                "-vf", f"scale='min({POSTER_PX},iw)':-2", "-q:v", "4", str(out),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )  # fmt: skip
            _, err = await asyncio.wait_for(proc.communicate(), FFMPEG_TIMEOUT_S)
        except (OSError, TimeoutError) as exc:
            log.error("ffmpeg could not make a poster: %s", type(exc).__name__)
            raise PosterError("the poster could not be made") from exc
        report = err.decode(errors="replace")
        match = _SIZE.search(report)
        if proc.returncode != 0 or not out.exists() or not match:
            log.error(
                "ffmpeg failed to make a poster (exit %s): %s", proc.returncode, report[-300:]
            )
            raise PosterError("the poster could not be made")
        return int(match[1]), int(match[2]), out.read_bytes()
