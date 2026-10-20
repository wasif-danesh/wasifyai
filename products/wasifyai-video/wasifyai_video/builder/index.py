"""Compositions in My creations search (ADR-0041): found by their title and the words on the
screen. One source covers them together with the clips (`video_index_source` combines the two); the
desktop's tables are in `builder.db` next to the app's other data."""

import asyncio
import sqlite3
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

PRODUCT_ID = "wasifyai-video"
KIND = "composition"


def builder_db(engine: AsyncEngine) -> Path | None:
    """`<data>/video-builder/builder.db` for a desktop engine (main database `wasifyai.db`)."""
    if engine.dialect.name != "sqlite" or not engine.url.database:
        return None
    path = Path(engine.url.database).parent / "video-builder" / "builder.db"
    return path if path.is_file() else None


def words_of(template: str, slots_json: str) -> str:
    """What a composition is found by: every word on its screen."""
    import json

    from wasifyai_video.builder import templates

    try:
        slots = json.loads(slots_json)
        return search_text(templates.describe(template, slots))
    except (ValueError, KeyError, TypeError, templates.SlotError):
        return ""


class BuilderIndexSource:
    product_id = PRODUCT_ID
    kind = KIND

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    def _connect(self) -> sqlite3.Connection | None:
        path = builder_db(self._engine)
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) if path else None

    def _page(self, after: str | None, limit: int) -> list[IndexItem]:
        db = self._connect()
        if db is None:
            return []
        try:
            rows = db.execute(
                "SELECT id, tenant_id, user_id, template, slots FROM compositions "
                "WHERE (? IS NULL OR id > ?) ORDER BY id LIMIT ?",
                (after, after, limit),
            ).fetchall()
            return [
                IndexItem(t, PRODUCT_ID, u, KIND, i, words_of(tm, s)) for i, t, u, tm, s in rows
            ]
        finally:
            db.close()

    def _present(self, ids: list[str]) -> set[str]:
        db = self._connect()
        if db is None:
            return set()
        try:
            marks = ",".join("?" * len(ids))
            return {
                r[0] for r in db.execute(f"SELECT id FROM compositions WHERE id IN ({marks})", ids)
            }
        finally:
            db.close()

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        return await asyncio.to_thread(self._page, after, limit)

    async def present(self, item_ids: list[str]) -> set[str]:
        if not item_ids:
            return set()
        return await asyncio.to_thread(self._present, item_ids)
