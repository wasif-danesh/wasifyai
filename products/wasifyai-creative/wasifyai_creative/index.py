# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""Creative Studio's projects in My creations search (ADR-0041): found by their title, idea, cast, places, shots and
lyrics. The desktop's table is in `creative.db` next to the app's other data."""

import asyncio
import json
import sqlite3
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

from wasifyai_creative.document import index_words

PRODUCT_ID = "wasifyai-creative"
KIND = "creative_project"


def creative_db(engine: AsyncEngine) -> Path | None:
    """`<data>/creative/creative.db` for a desktop engine (main database `wasifyai.db`)."""
    if engine.dialect.name != "sqlite" or not engine.url.database:
        return None
    path = Path(engine.url.database).parent / "creative" / "creative.db"
    return path if path.is_file() else None


class CreativeIndexSource:
    product_id = PRODUCT_ID
    kind = KIND

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    def _connect(self) -> sqlite3.Connection | None:
        path = creative_db(self._engine)
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) if path else None

    def _page(self, after: str | None, limit: int) -> list[IndexItem]:
        db = self._connect()
        if db is None:
            return []
        try:
            rows = db.execute(
                "SELECT id, tenant_id, user_id, title, brief, plan, facts FROM projects "
                "WHERE (? IS NULL OR id > ?) ORDER BY id LIMIT ?",
                (after, after, limit),
            ).fetchall()
            out = []
            for i, t, u, title, brief, plan, facts in rows:
                lyrics = " ".join(x["text"] for x in json.loads(facts or "{}").get("lines", []))
                words = index_words(
                    title, json.loads(brief), json.loads(plan) if plan else None, lyrics
                )
                out.append(IndexItem(t, PRODUCT_ID, u, KIND, i, search_text(*words)))
            return out
        finally:
            db.close()

    def _present(self, ids: list[str]) -> set[str]:
        db = self._connect()
        if db is None:
            return set()
        try:
            marks = ",".join("?" * len(ids))
            return {r[0] for r in db.execute(f"SELECT id FROM projects WHERE id IN ({marks})", ids)}
        finally:
            db.close()

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        return await asyncio.to_thread(self._page, after, limit)

    async def present(self, item_ids: list[str]) -> set[str]:
        if not item_ids:
            return set()
        return await asyncio.to_thread(self._present, item_ids)


def creative_index_source(engine: AsyncEngine) -> CreativeIndexSource:
    return CreativeIndexSource(engine)
