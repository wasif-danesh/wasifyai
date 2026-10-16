# SPDX-License-Identifier: Apache-2.0
"""Speeches and transcripts in My creations search (ADR-0041): a speech is found by the words it
says, a
transcript by its title and its text. One source covers both kinds (the platform reconciles per
product)."""

import asyncio
import sqlite3
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

PRODUCT_ID = "wasifyai-voice"
TRANSCRIPT_CHARS = 2000


def voice_db(engine: AsyncEngine) -> Path | None:
    """`<data>/voice/voice.db` for a desktop engine (main database `<data>/wasifyai.db`)."""
    if engine.dialect.name != "sqlite" or not engine.url.database:
        return None
    path = Path(engine.url.database).parent / "voice" / "voice.db"
    return path if path.is_file() else None


class VoiceIndexSource:
    product_id = PRODUCT_ID
    kind = "speech"  # and "transcript", "voice", "track": items carry their own kind

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    def _connect(self) -> sqlite3.Connection | None:
        path = voice_db(self._engine)
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) if path else None

    def _page(self, after: str | None, limit: int) -> list[IndexItem]:
        db = self._connect()
        if db is None:
            return []
        try:
            rows = db.execute(
                "SELECT id, tenant_id, user_id, 'speech', text FROM speeches "
                "WHERE (? IS NULL OR id > ?) "
                "UNION ALL SELECT id, tenant_id, user_id, 'transcript', "
                "title || '. ' || substr(text, 1, ?) FROM transcripts WHERE (? IS NULL OR id > ?) "
                "UNION ALL SELECT id, tenant_id, user_id, 'voice', "
                "name || '. ' || CASE WHEN description = '' THEN 'cloned voice' "
                "ELSE description END "
                "FROM voices WHERE (? IS NULL OR id > ?) "
                "UNION ALL SELECT id, tenant_id, user_id, 'track', "
                "title || '. ' || description || CASE WHEN lyrics = '' THEN '' ELSE '. ' || "
                "substr(lyrics, 1, ?) END FROM tracks WHERE (? IS NULL OR id > ?) "
                "ORDER BY id LIMIT ?",
                (
                    after,
                    after,
                    TRANSCRIPT_CHARS,
                    after,
                    after,
                    after,
                    after,
                    TRANSCRIPT_CHARS,
                    after,
                    after,
                    limit,
                ),
            ).fetchall()
            return [IndexItem(t, PRODUCT_ID, u, k, i, search_text(x)) for i, t, u, k, x in rows]
        finally:
            db.close()

    def _present(self, ids: list[str]) -> set[str]:
        db = self._connect()
        if db is None:
            return set()
        try:
            marks = ",".join("?" * len(ids))
            return {
                r[0]
                for r in db.execute(
                    f"SELECT id FROM speeches WHERE id IN ({marks}) "
                    f"UNION SELECT id FROM transcripts WHERE id IN ({marks}) "
                    f"UNION SELECT id FROM voices WHERE id IN ({marks}) "
                    f"UNION SELECT id FROM tracks WHERE id IN ({marks})",
                    [*ids, *ids, *ids, *ids],
                )
            }
        finally:
            db.close()

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        return await asyncio.to_thread(self._page, after, limit)

    async def present(self, item_ids: list[str]) -> set[str]:
        if not item_ids:
            return set()
        return await asyncio.to_thread(self._present, item_ids)


def voice_index_source(engine: AsyncEngine) -> VoiceIndexSource:
    return VoiceIndexSource(engine)
