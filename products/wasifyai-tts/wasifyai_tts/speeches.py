"""Finished speech: storage, the daily quota, and the WAV to MP3 conversion (AI-generated tag)."""

import asyncio
import io
import logging
import re
import wave
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import RunContext, start_of_day_utc, sum_usage

log = logging.getLogger(__name__)

SPEECH_CREATED = "speech.created"
FFMPEG_TIMEOUT_S = 90
AI_TAG = "AI-generated speech"


@dataclass(frozen=True)
class SpeechRecord:
    id: str
    tenant_id: str
    product_id: str
    user_id: str
    thread_id: str | None
    run_id: str | None
    text: str
    language: str
    gender: str
    voice: str
    characters: int
    seconds: float
    audio_key: str  # relative to the user's storage prefix
    created_at: datetime | None = field(default=None, compare=False)  # set by the database


class SpeechStore(Protocol):
    async def add(self, speech: SpeechRecord) -> None: ...

    async def list(
        self, tenant_id: str, user_id: str, limit: int, before: datetime | None
    ) -> list[SpeechRecord]:
        """The user's results, newest first, strictly older than `before`."""
        ...

    async def get(self, tenant_id: str, user_id: str, speech_id: str) -> SpeechRecord | None: ...

    async def delete(self, tenant_id: str, user_id: str, speech_id: str) -> None: ...


_COLUMNS = (
    "id, tenant_id, product_id, user_id, thread_id, run_id, text, language, gender, voice, "
    "characters, seconds, audio_key, created_at"
)


def _record(r) -> SpeechRecord:
    return SpeechRecord(
        id=str(r[0]), tenant_id=r[1], product_id=r[2], user_id=r[3], thread_id=r[4], run_id=r[5],
        text=r[6], language=r[7], gender=r[8], voice=r[9], characters=r[10], seconds=r[11],
        audio_key=r[12], created_at=r[13],
    )  # fmt: skip


class PostgresSpeechStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def add(self, speech: SpeechRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO speeches (id, tenant_id, product_id, user_id, thread_id, run_id,
                                          text, language, gender, voice, characters, seconds,
                                          audio_key)
                    VALUES (:id, :tenant_id, :product_id, :user_id, :thread_id, :run_id, :text,
                            :language, :gender, :voice, :characters, :seconds, :audio_key)
                    """
                ),
                {**{k: v for k, v in speech.__dict__.items() if k != "created_at"},
                 "id": UUID(speech.id)},
            )  # fmt: skip

    async def list(
        self, tenant_id: str, user_id: str, limit: int, before: datetime | None
    ) -> list[SpeechRecord]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    f"""
                    SELECT {_COLUMNS} FROM speeches
                    WHERE tenant_id = :t AND product_id = 'wasifyai-tts' AND user_id = :u
                      AND (CAST(:before AS timestamptz) IS NULL OR created_at < :before)
                    ORDER BY created_at DESC, id DESC LIMIT :limit
                    """
                ),
                {"t": tenant_id, "u": user_id, "before": before, "limit": limit},
            )
            return [_record(r) for r in rows]

    async def get(self, tenant_id: str, user_id: str, speech_id: str) -> SpeechRecord | None:
        try:
            sid = UUID(speech_id)
        except ValueError:
            return None
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM speeches WHERE id = :id AND tenant_id = :t "
                        "AND user_id = :u AND product_id = 'wasifyai-tts'"
                    ),
                    {"id": sid, "t": tenant_id, "u": user_id},
                )
            ).first()
            return _record(row) if row else None

    async def delete(self, tenant_id: str, user_id: str, speech_id: str) -> None:
        try:
            sid = UUID(speech_id)
        except ValueError:
            return
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM speeches WHERE id = :id AND tenant_id = :t AND user_id = :u"),
                {"id": sid, "t": tenant_id, "u": user_id},
            )


class InMemorySpeechStore:
    def __init__(self) -> None:
        self.speeches: list[SpeechRecord] = []

    async def add(self, speech: SpeechRecord) -> None:
        self.speeches.append(replace(speech, created_at=speech.created_at or datetime.now(UTC)))

    async def list(
        self, tenant_id: str, user_id: str, limit: int, before: datetime | None
    ) -> list[SpeechRecord]:
        mine = [s for s in self.speeches if (s.tenant_id, s.user_id) == (tenant_id, user_id)]
        mine = [s for s in mine if before is None or (s.created_at and s.created_at < before)]
        return sorted(mine, key=lambda s: (s.created_at, s.id), reverse=True)[:limit]

    async def get(self, tenant_id: str, user_id: str, speech_id: str) -> SpeechRecord | None:
        return next(
            (
                s
                for s in self.speeches
                if (s.tenant_id, s.user_id, s.id) == (tenant_id, user_id, speech_id)
            ),
            None,
        )

    async def delete(self, tenant_id: str, user_id: str, speech_id: str) -> None:
        self.speeches = [
            s
            for s in self.speeches
            if (s.tenant_id, s.user_id, s.id) != (tenant_id, user_id, speech_id)
        ]


class Quota(Protocol):
    async def used_today(self, ctx: RunContext) -> int: ...


class UsageQuota:
    """Results made today (UTC), counted from the `speech.created` usage events."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def used_today(self, ctx: RunContext) -> int:
        return int(
            await sum_usage(
                self._engine, ctx.tenant_id, ctx.product_id, ctx.user_id, SPEECH_CREATED,
                start_of_day_utc(),
            )
        )  # fmt: skip


class FixedQuota:
    """For tests: pretend the user already made `used` results today."""

    def __init__(self, used: int = 0) -> None:
        self.used = used

    async def used_today(self, ctx: RunContext) -> int:
        return self.used


class SpeechError(Exception):
    """ffmpeg or the audio was unusable. The details go to the log; the message is safe to show."""


def wav_seconds(wav: bytes) -> float:
    try:
        with wave.open(io.BytesIO(wav)) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError) as exc:
        raise SpeechError("the speech could not be read") from exc


def ffmpeg_path() -> str:
    """The static ffmpeg that comes with `imageio-ffmpeg`, else whatever is on the PATH."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil

        return shutil.which("ffmpeg") or "ffmpeg"


def _tag(value: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:60]


async def to_mp3(wav: bytes, title: str) -> bytes:
    """A small MP3 of the speech, tagged as AI-generated (ADR-0042), made by a child ffmpeg."""
    try:
        proc = await asyncio.create_subprocess_exec(
            ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", "pipe:0",
            "-vn", "-codec:a", "libmp3lame", "-b:a", "96k", "-id3v2_version", "3",
            "-metadata", f"comment={AI_TAG}", "-metadata", f"title={_tag(title)}",
            "-metadata", "genre=Speech", "-f", "mp3", "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        out, err = await asyncio.wait_for(proc.communicate(wav), FFMPEG_TIMEOUT_S)
    except (OSError, TimeoutError) as exc:
        log.error("ffmpeg could not make the MP3: %s", type(exc).__name__)
        raise SpeechError("the speech could not be saved") from exc
    if proc.returncode != 0 or not out:
        log.error(
            "ffmpeg failed (exit %s): %s", proc.returncode, err.decode(errors="replace")[-300:]
        )
        raise SpeechError("the speech could not be saved")
    return out
