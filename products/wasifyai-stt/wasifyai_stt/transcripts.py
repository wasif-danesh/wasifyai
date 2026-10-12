"""Transcripts: storage, the daily minutes quota and the one-at-a-time rule.

A row exists from the moment the job starts (status "working") so the site can show "being made"
on any page (ADR-0043). A row that stays "working" for over an hour belongs to a run that died; it
is marked "failed" the next time anyone reads the table. The audio is gone by then: only words are
kept."""

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import RunContext, start_of_day_utc, sum_usage

log = logging.getLogger(__name__)

TRANSCRIPT_CREATED = "transcript.created"
STALE_AFTER = timedelta(hours=1)
STALE_MESSAGE = "This took too long and was stopped. Please try again."


@dataclass(frozen=True)
class TranscriptRecord:
    id: str
    tenant_id: str
    product_id: str
    user_id: str
    thread_id: str | None
    run_id: str | None
    status: str  # "working" | "done" | "failed"
    seconds: float  # the length of the recording
    title: str = ""
    language: str = ""  # what was spoken (chosen or detected)
    engine: str = ""
    text: str = ""
    segments: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    created_at: datetime | None = field(default=None, compare=False)  # set by the database


class TranscriptStore(Protocol):
    async def add(self, t: TranscriptRecord) -> None: ...

    async def finish(
        self,
        tenant_id: str,
        transcript_id: str,
        title: str,
        language: str,
        engine: str,
        text: str,
        segments: list[dict[str, Any]],
    ) -> None: ...

    async def fail(self, tenant_id: str, transcript_id: str, message: str) -> None: ...

    async def list(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        before: datetime | None,
        status: str | None = None,
    ) -> list[TranscriptRecord]:
        """The user's transcripts, newest first, strictly older than `before`."""
        ...

    async def get(
        self, tenant_id: str, user_id: str, transcript_id: str
    ) -> TranscriptRecord | None: ...

    async def delete(self, tenant_id: str, user_id: str, transcript_id: str) -> None: ...

    async def working_count(self, tenant_id: str, user_id: str) -> int: ...


_COLUMNS = (
    "id, tenant_id, product_id, user_id, thread_id, run_id, status, seconds, title, language, "
    "engine, text, segments, error, created_at"
)


def _record(r) -> TranscriptRecord:
    segments = r[12]
    return TranscriptRecord(
        id=str(r[0]), tenant_id=r[1], product_id=r[2], user_id=r[3], thread_id=r[4], run_id=r[5],
        status=r[6], seconds=r[7], title=r[8], language=r[9], engine=r[10], text=r[11],
        segments=json.loads(segments) if isinstance(segments, str) else list(segments or []),
        error=r[13], created_at=r[14],
    )  # fmt: skip


class PostgresTranscriptStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _expire(self, conn) -> None:
        await conn.execute(
            sql(
                "UPDATE transcripts SET status = 'failed', error = :msg WHERE status = 'working' "
                "AND product_id = 'wasifyai-stt' AND created_at < :cutoff"
            ),
            {"msg": STALE_MESSAGE, "cutoff": datetime.now(UTC) - STALE_AFTER},
        )

    async def add(self, t: TranscriptRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                sql(
                    """
                    INSERT INTO transcripts (id, tenant_id, product_id, user_id, thread_id, run_id,
                                             status, seconds)
                    VALUES (:id, :tenant_id, :product_id, :user_id, :thread_id, :run_id,
                            :status, :seconds)
                    """
                ),
                {
                    "id": UUID(t.id), "tenant_id": t.tenant_id, "product_id": t.product_id,
                    "user_id": t.user_id, "thread_id": t.thread_id, "run_id": t.run_id,
                    "status": t.status, "seconds": t.seconds,
                },
            )  # fmt: skip

    async def finish(
        self,
        tenant_id: str,
        transcript_id: str,
        title: str,
        language: str,
        engine: str,
        text: str,
        segments: list[dict[str, Any]],
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                sql(
                    "UPDATE transcripts SET status = 'done', title = :title, language = :lang, "
                    "engine = :engine, text = :text, segments = CAST(:segments AS jsonb), "
                    "error = NULL WHERE id = :id AND tenant_id = :t"
                ),
                {
                    "title": title, "lang": language, "engine": engine, "text": text,
                    "segments": json.dumps(segments, ensure_ascii=False),
                    "id": UUID(transcript_id), "t": tenant_id,
                },
            )  # fmt: skip

    async def fail(self, tenant_id: str, transcript_id: str, message: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                sql(
                    "UPDATE transcripts SET status = 'failed', error = :m "
                    "WHERE id = :id AND tenant_id = :t AND status = 'working'"
                ),
                {"m": message, "id": UUID(transcript_id), "t": tenant_id},
            )

    async def list(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        before: datetime | None,
        status: str | None = None,
    ) -> list[TranscriptRecord]:
        async with self._engine.begin() as conn:
            await self._expire(conn)
            rows = await conn.execute(
                sql(
                    f"""
                    SELECT {_COLUMNS} FROM transcripts
                    WHERE tenant_id = :t AND product_id = 'wasifyai-stt' AND user_id = :u
                      AND (CAST(:before AS timestamptz) IS NULL OR created_at < :before)
                      AND (CAST(:status AS text) IS NULL OR status = :status)
                    ORDER BY created_at DESC, id DESC LIMIT :limit
                    """
                ),
                {"t": tenant_id, "u": user_id, "before": before, "status": status, "limit": limit},
            )
            return [_record(r) for r in rows]

    async def get(
        self, tenant_id: str, user_id: str, transcript_id: str
    ) -> TranscriptRecord | None:
        try:
            tid = UUID(transcript_id)
        except ValueError:
            return None
        async with self._engine.begin() as conn:
            await self._expire(conn)
            row = (
                await conn.execute(
                    sql(
                        f"SELECT {_COLUMNS} FROM transcripts WHERE id = :id AND tenant_id = :t "
                        "AND user_id = :u AND product_id = 'wasifyai-stt'"
                    ),
                    {"id": tid, "t": tenant_id, "u": user_id},
                )
            ).first()
            return _record(row) if row else None

    async def delete(self, tenant_id: str, user_id: str, transcript_id: str) -> None:
        try:
            tid = UUID(transcript_id)
        except ValueError:
            return
        async with self._engine.begin() as conn:
            await conn.execute(
                sql("DELETE FROM transcripts WHERE id = :id AND tenant_id = :t AND user_id = :u"),
                {"id": tid, "t": tenant_id, "u": user_id},
            )

    async def working_count(self, tenant_id: str, user_id: str) -> int:
        async with self._engine.begin() as conn:
            await self._expire(conn)
            row = (
                await conn.execute(
                    sql(
                        "SELECT count(*) FROM transcripts WHERE tenant_id = :t AND user_id = :u "
                        "AND product_id = 'wasifyai-stt' AND status = 'working'"
                    ),
                    {"t": tenant_id, "u": user_id},
                )
            ).one()
            return int(row[0])


class InMemoryTranscriptStore:
    def __init__(self) -> None:
        self.transcripts: list[TranscriptRecord] = []

    def _expire(self) -> None:
        cutoff = datetime.now(UTC) - STALE_AFTER
        self.transcripts = [
            replace(t, status="failed", error=STALE_MESSAGE)
            if t.status == "working" and t.created_at and t.created_at < cutoff
            else t
            for t in self.transcripts
        ]

    def _update(self, tenant_id: str, transcript_id: str, **changes: Any) -> None:
        self.transcripts = [
            replace(t, **changes) if (t.tenant_id, t.id) == (tenant_id, transcript_id) else t
            for t in self.transcripts
        ]

    async def add(self, t: TranscriptRecord) -> None:
        self.transcripts.append(replace(t, created_at=t.created_at or datetime.now(UTC)))

    async def finish(
        self,
        tenant_id: str,
        transcript_id: str,
        title: str,
        language: str,
        engine: str,
        text: str,
        segments: list[dict[str, Any]],
    ) -> None:
        self._update(
            tenant_id, transcript_id, status="done", title=title, language=language,
            engine=engine, text=text, segments=segments, error=None,
        )  # fmt: skip

    async def fail(self, tenant_id: str, transcript_id: str, message: str) -> None:
        self.transcripts = [
            replace(t, status="failed", error=message)
            if (t.tenant_id, t.id, t.status) == (tenant_id, transcript_id, "working")
            else t
            for t in self.transcripts
        ]

    async def list(
        self,
        tenant_id: str,
        user_id: str,
        limit: int,
        before: datetime | None,
        status: str | None = None,
    ) -> list[TranscriptRecord]:
        self._expire()
        mine = [t for t in self.transcripts if (t.tenant_id, t.user_id) == (tenant_id, user_id)]
        mine = [t for t in mine if before is None or (t.created_at and t.created_at < before)]
        mine = [t for t in mine if status is None or t.status == status]
        return sorted(mine, key=lambda t: (t.created_at, t.id), reverse=True)[:limit]

    async def get(
        self, tenant_id: str, user_id: str, transcript_id: str
    ) -> TranscriptRecord | None:
        self._expire()
        return next(
            (
                t
                for t in self.transcripts
                if (t.tenant_id, t.user_id, t.id) == (tenant_id, user_id, transcript_id)
            ),
            None,
        )

    async def delete(self, tenant_id: str, user_id: str, transcript_id: str) -> None:
        self.transcripts = [
            t
            for t in self.transcripts
            if (t.tenant_id, t.user_id, t.id) != (tenant_id, user_id, transcript_id)
        ]

    async def working_count(self, tenant_id: str, user_id: str) -> int:
        self._expire()
        return sum(
            1
            for t in self.transcripts
            if (t.tenant_id, t.user_id, t.status) == (tenant_id, user_id, "working")
        )


class Quota(Protocol):
    async def used_minutes_today(self, ctx: RunContext) -> float: ...


class UsageQuota:
    """Minutes of audio transcribed today (UTC), from the `transcript.created` usage events."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def used_minutes_today(self, ctx: RunContext) -> float:
        return await sum_usage(
            self._engine, ctx.tenant_id, ctx.product_id, ctx.user_id, TRANSCRIPT_CREATED,
            start_of_day_utc(),
        )  # fmt: skip


class FixedQuota:
    """For tests: pretend the user already transcribed `minutes` today."""

    def __init__(self, minutes: float = 0) -> None:
        self.minutes = minutes

    async def used_minutes_today(self, ctx: RunContext) -> float:
        return self.minutes
