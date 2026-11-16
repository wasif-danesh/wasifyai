"""Meetings in My creations search (ADR-0041, ADR-0108 decision 19): found by their title, their
speakers' names and what was said. The desktop's table is in `meetings.db` next to the app's other
data; the web's comes in stage MT6."""

import asyncio
import json
import sqlite3
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

from wasifyai_meetings.runtime import INDEX_CHARS, KIND, PRODUCT_ID


def meetings_db(engine: AsyncEngine) -> Path | None:
    """`<data>/meetings/meetings.db` for a desktop engine (main database `wasifyai.db`)."""
    if engine.dialect.name != "sqlite" or not engine.url.database:
        return None
    path = Path(engine.url.database).parent / "meetings" / "meetings.db"
    return path if path.is_file() else None


def _words(title: str, speakers: str, text: str) -> str:
    names = ", ".join(s.get("name", "") for s in json.loads(speakers or "[]"))
    return search_text(title, names, (text or "")[:INDEX_CHARS])


class MeetingsIndexSource:
    product_id = PRODUCT_ID
    kind = KIND

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    def _connect(self) -> sqlite3.Connection | None:
        path = meetings_db(self._engine)
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) if path else None

    def _page(self, after: str | None, limit: int) -> list[IndexItem]:
        db = self._connect()
        if db is None:
            return []
        try:
            rows = db.execute(
                "SELECT id, tenant_id, user_id, title, speakers, text FROM meetings "
                "WHERE status = 'done' AND (? IS NULL OR id > ?) ORDER BY id LIMIT ?",
                (after, after, limit),
            ).fetchall()
            return [
                IndexItem(t, PRODUCT_ID, u, KIND, i, _words(title, speakers, text))
                for i, t, u, title, speakers, text in rows
            ]
        finally:
            db.close()

    def _present(self, ids: list[str]) -> set[str]:
        db = self._connect()
        if db is None:
            return set()
        try:
            marks = ",".join("?" * len(ids))
            return {r[0] for r in db.execute(f"SELECT id FROM meetings WHERE id IN ({marks})", ids)}
        finally:
            db.close()

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        if self._engine.dialect.name != "sqlite":  # the web has no meetings yet (stage MT6)
            return []
        return await asyncio.to_thread(self._page, after, limit)

    async def present(self, item_ids: list[str]) -> set[str]:
        if not item_ids:
            return set()
        if self._engine.dialect.name != "sqlite":
            return set(item_ids)  # unknown is not gone: never remove what cannot be checked
        return await asyncio.to_thread(self._present, item_ids)


def meetings_index_source(engine: AsyncEngine) -> MeetingsIndexSource:
    return MeetingsIndexSource(engine)
