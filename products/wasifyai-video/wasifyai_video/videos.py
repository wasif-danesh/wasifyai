"""Clips: storage, the daily quota, the one-at-a-time rule and the poster picture.

A row exists from the moment a run starts (status "working") so that the site can show "being made"
on any page (ADR-0037). A row that stays "working" for 90 minutes belongs to a run that died;
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
from wasifyai_platform_sdk.sqlite import (
    ensure_tables,
    from_iso,
    is_sqlite,
    now_iso,
    to_iso,
)

log = logging.getLogger(__name__)

VIDEO_CREATED = "video.created"
POSTER_PX = 480
STALE_AFTER = timedelta(minutes=90)  # a long clip on a slow computer takes most of an hour
STALE_MESSAGE = "This took too long and was stopped. Please try again."
FFMPEG_TIMEOUT_S = 60
JOIN_TIMEOUT_S = 180
IMPORT_TIMEOUT_S = 300
IMPORT_MAX_SECONDS = 30  # a longer file is refused: it would take long to read and hold much memory
IMPORT_BOX = 768  # the longer side of an added video after it is made to fit the model
TAIL_FRAMES = 24  # what the engine is given of a long clip: one second, enough for the nine it uses


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


_SQLITE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS videos (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        thread_id TEXT,
        run_id TEXT,
        mode TEXT NOT NULL,
        status TEXT NOT NULL,
        prompt TEXT NOT NULL,
        seconds INTEGER NOT NULL,
        frames INTEGER NOT NULL,
        fps INTEGER NOT NULL,
        width INTEGER,
        height INTEGER,
        video_key TEXT,
        poster_key TEXT,
        error TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_videos_user_created "
    "ON videos (tenant_id, product_id, user_id, created_at)",
)


class SqliteVideoStore:
    """The same records on the SQLite file of the desktop profile (ADR-0056)."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        await ensure_tables(self._engine, "videos", _SQLITE_DDL)

    @staticmethod
    def _record(r) -> VideoRecord:
        return VideoRecord(
            id=r[0], tenant_id=r[1], product_id=r[2], user_id=r[3], thread_id=r[4], run_id=r[5],
            mode=r[6], status=r[7], prompt=r[8], seconds=r[9], frames=r[10], fps=r[11],
            width=r[12], height=r[13], video_key=r[14], poster_key=r[15], error=r[16],
            created_at=from_iso(r[17]),
        )  # fmt: skip

    async def _expire(self, conn) -> None:
        await conn.execute(
            text(
                "UPDATE videos SET status = 'failed', error = :msg WHERE status = 'working' "
                "AND product_id = 'wasifyai-video' AND created_at < :cutoff"
            ),
            {"msg": STALE_MESSAGE, "cutoff": to_iso(datetime.now(UTC) - STALE_AFTER)},
        )

    async def add(self, video: VideoRecord) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO videos (id, tenant_id, product_id, user_id, thread_id, run_id, mode,
                                        status, prompt, seconds, frames, fps, created_at)
                    VALUES (:id, :tenant_id, :product_id, :user_id, :thread_id, :run_id, :mode,
                            :status, :prompt, :seconds, :frames, :fps, :created_at)
                    """
                ),
                {
                    "id": video.id, "tenant_id": video.tenant_id, "product_id": video.product_id,
                    "user_id": video.user_id, "thread_id": video.thread_id,
                    "run_id": video.run_id, "mode": video.mode, "status": video.status,
                    "prompt": video.prompt, "seconds": video.seconds, "frames": video.frames,
                    "fps": video.fps,
                    "created_at": to_iso(video.created_at) if video.created_at else now_iso(),
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
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE videos SET status = 'done', width = :w, height = :h, video_key = :v, "
                    "poster_key = :p, error = NULL WHERE id = :id AND tenant_id = :t"
                ),
                {"w": width, "h": height, "v": video_key, "p": poster_key,
                 "id": video_id, "t": tenant_id},
            )  # fmt: skip

    async def fail(self, tenant_id: str, video_id: str, message: str) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE videos SET status = 'failed', error = :m "
                    "WHERE id = :id AND tenant_id = :t AND status = 'working'"
                ),
                {"m": message, "id": video_id, "t": tenant_id},
            )

    async def list(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        before: datetime | None,
        status: str | None = None,
    ) -> list[VideoRecord]:
        await self._ready()
        async with self._engine.begin() as conn:
            await self._expire(conn)
            rows = await conn.execute(
                text(
                    f"""
                    SELECT {_COLUMNS} FROM videos
                    WHERE tenant_id = :t AND product_id = 'wasifyai-video' AND user_id = :u
                      AND (:before IS NULL OR created_at < :before)
                      AND (:status IS NULL OR status = :status)
                    ORDER BY created_at DESC, id DESC LIMIT :limit
                    """
                ),
                {
                    "t": tenant_id, "u": user_id, "limit": limit, "status": status,
                    "before": to_iso(before) if before else None,
                },
            )  # fmt: skip
            return [self._record(r) for r in rows]

    async def get(self, tenant_id: str, user_id: str, video_id: str) -> VideoRecord | None:
        await self._ready()
        async with self._engine.begin() as conn:
            await self._expire(conn)
            row = (
                await conn.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM videos WHERE id = :id AND tenant_id = :t "
                        "AND user_id = :u AND product_id = 'wasifyai-video'"
                    ),
                    {"id": video_id, "t": tenant_id, "u": user_id},
                )
            ).first()
            return self._record(row) if row else None

    async def delete(self, tenant_id: str, user_id: str, video_id: str) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM videos WHERE id = :id AND tenant_id = :t AND user_id = :u"),
                {"id": video_id, "t": tenant_id, "u": user_id},
            )

    async def working_count(self, tenant_id: str, user_id: str) -> int:
        await self._ready()
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


def video_store(engine: AsyncEngine) -> VideoStore:
    """The store for the database the engine speaks to: Postgres in the web profile, SQLite in the
    desktop profile (ADR-0056). Callers do not know which."""
    return SqliteVideoStore(engine) if is_sqlite(engine) else PostgresVideoStore(engine)


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


class JoinError(Exception):
    """ffmpeg could not join two clips. The details go to the log; the message is safe to show."""


async def join_clips(source: bytes, extension: bytes, keep: int) -> bytes:
    """The first `keep` frames of `source` followed by every frame of `extension`, as one MP4.
    Both are LTX clips of the same size at 24 frames a second; the join is frame exact."""
    exe = ffmpeg_path()
    with tempfile.TemporaryDirectory(prefix="wasifyai-video-") as tmp:
        a, b, out = Path(tmp) / "a.mp4", Path(tmp) / "b.mp4", Path(tmp) / "joined.mp4"
        a.write_bytes(source)
        b.write_bytes(extension)
        graph = (
            f"[0:v]trim=end_frame={keep},setpts=PTS-STARTPTS,fps=24[a];"
            "[1:v]setpts=PTS-STARTPTS,fps=24[b];[a][b]concat=n=2:v=1:a=0[v]"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                exe, "-hide_banner", "-y", "-i", str(a), "-i", str(b), "-filter_complex", graph,
                "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                "-movflags", "+faststart", str(out),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )  # fmt: skip
            _, err = await asyncio.wait_for(proc.communicate(), JOIN_TIMEOUT_S)
        except (OSError, TimeoutError) as exc:
            log.error("ffmpeg could not join two clips: %s", type(exc).__name__)
            raise JoinError("the clips could not be joined") from exc
        if proc.returncode != 0 or not out.exists():
            log.error(
                "ffmpeg failed to join two clips (exit %s): %s",
                proc.returncode, err.decode(errors="replace")[-300:],
            )  # fmt: skip
            raise JoinError("the clips could not be joined")
        return out.read_bytes()


class ClipError(Exception):
    """A video file that cannot be used. The message is in words for the person."""


_DURATION = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_FRAMES = re.compile(r"frame=\s*(\d+)")


async def _run_ffmpeg(args: list[str], limit_s: float) -> tuple[int, str]:
    """ffmpeg with no input from the keyboard and a time limit; its report and exit status."""
    try:
        proc = await asyncio.create_subprocess_exec(
            ffmpeg_path(), "-hide_banner", "-nostdin", *args,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        _, err = await asyncio.wait_for(proc.communicate(), limit_s)
    except TimeoutError:
        proc.kill()  # type: ignore[possibly-undefined]
        raise ClipError("That video took too long to read. Try a shorter one.") from None
    except OSError as exc:
        log.error("ffmpeg could not start: %s", type(exc).__name__)
        raise ClipError("Videos cannot be read on this computer.") from exc
    return proc.returncode or 0, err.decode(errors="replace")


async def count_frames(path: Path) -> int:
    """How many frames a clip has, as ffmpeg decodes them."""
    _, report = await _run_ffmpeg(["-i", str(path), "-f", "null", "-"], FFMPEG_TIMEOUT_S * 3)
    found = _FRAMES.findall(report)
    if not found:
        raise ClipError("That video could not be read.")
    return int(found[-1])


def fit_size(width: int, height: int) -> tuple[int, int]:
    """The size an added video is made: multiples of 32 (which LTX needs), the longer side at most
    IMPORT_BOX, about the size the model makes its own clips."""
    f = min(1.0, IMPORT_BOX / max(width, height))
    return max(64, int(width * f) // 32 * 32), max(64, int(height * f) // 32 * 32)


async def import_clip(source: Path, out: Path) -> tuple[int, int, int]:
    """Make a video file of the person's into a clip the engine can carry on: H.264 at 24 frames a
    second, no sound and no tags, a multiple of 32 on each side, at most IMPORT_MAX_SECONDS long.
    Returns its width, height and frame count. The file is decoded by ffmpeg, never trusted."""
    rc, report = await _run_ffmpeg(
        ["-i", str(source)], FFMPEG_TIMEOUT_S
    )  # no output: it only reads
    size, length = _SIZE.search(report), _DURATION.search(report)
    if not size or not length:
        log.info("an added file was not a readable video (exit %s)", rc)
        raise ClipError("That file is not a video this app can read. Try an MP4 or MOV file.")
    seconds = int(length[1]) * 3600 + int(length[2]) * 60 + float(length[3])
    if seconds > IMPORT_MAX_SECONDS:
        raise ClipError(
            f"That video is longer than {IMPORT_MAX_SECONDS} seconds. Try a shorter one."
        )
    if seconds < 0.5:
        raise ClipError("That video is too short. It needs to be at least half a second.")
    w, h = fit_size(int(size[1]), int(size[2]))
    rc, report = await _run_ffmpeg(
        ["-y", "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn", "-map_metadata", "-1",
         "-vf", f"fps=24,scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart",
         str(out)],
        IMPORT_TIMEOUT_S,
    )  # fmt: skip
    if rc != 0 or not await asyncio.to_thread(out.exists):
        log.error("ffmpeg could not make an added video fit (exit %s): %s", rc, report[-300:])
        raise ClipError("That video could not be read. Try another file.")
    frames = await count_frames(out)
    if frames < OVERLAP_MIN_FRAMES:
        raise ClipError("That video is too short to carry on.")
    return w, h, frames


OVERLAP_MIN_FRAMES = 9  # what the engine takes of a clip's end: a clip needs at least that


async def last_frame(mp4: bytes) -> bytes:
    """The last frame of a clip as a JPEG, for the check of what a person added (ADR-0047)."""
    with tempfile.TemporaryDirectory(prefix="wasifyai-video-") as tmp:
        src, out = Path(tmp) / "clip.mp4", Path(tmp) / "last.jpg"
        src.write_bytes(mp4)
        await _run_ffmpeg(
            ["-y", "-sseof", "-0.3", "-i", str(src), "-update", "1", "-q:v", "4", str(out)],
            FFMPEG_TIMEOUT_S,
        )
        if not await asyncio.to_thread(out.exists):
            raise ClipError("That video could not be read.")
        return out.read_bytes()


async def tail_of(mp4: bytes, frames: int, total: int) -> bytes:
    """The last `frames` frames of a clip of `total` frames as a new clip: all the engine needs of a
    long one, so it does not have to hold every frame of it in memory."""
    with tempfile.TemporaryDirectory(prefix="wasifyai-video-") as tmp:
        src, out = Path(tmp) / "clip.mp4", Path(tmp) / "tail.mp4"
        src.write_bytes(mp4)
        rc, report = await _run_ffmpeg(
            ["-y", "-i", str(src), "-vf", f"select='gte(n,{total - frames})',setpts=N/(24*TB)",
             "-r", "24", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "14", str(out)],
            FFMPEG_TIMEOUT_S * 2,
        )  # fmt: skip
        if rc != 0 or not await asyncio.to_thread(out.exists):
            log.error("ffmpeg could not cut the end of a clip (exit %s): %s", rc, report[-300:])
            raise ClipError("That video could not be read.")
        return out.read_bytes()
