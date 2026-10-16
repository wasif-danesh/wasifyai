# SPDX-License-Identifier: Apache-2.0
"""Notebooks in My creations search (ADR-0041, ADR-0065 decision 12): a notebook is found by its
title and the names of its sources, in any language.

The notebooks live in their own SQLite file next to the main one (desktop only), so the source
reads that file directly and read-only; on another profile there is nothing to list.
"""

import asyncio
import sqlite3
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

PRODUCT_ID = "wasifyai-notebooks"
KIND = "notebook"
MAX_SOURCE_NAMES = 40


def notebooks_db(engine: AsyncEngine) -> Path | None:
    """`<data>/notebooks/notebooks.db` for a desktop engine (whose main database is
    `<data>/wasifyai.db`)."""
    if engine.dialect.name != "sqlite" or not engine.url.database:
        return None
    path = Path(engine.url.database).parent / "notebooks" / "notebooks.db"
    return path if path.is_file() else None


class NotebookIndexSource:
    product_id = PRODUCT_ID
    kind = KIND

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    def _connect(self) -> sqlite3.Connection | None:
        path = notebooks_db(self._engine)
        if path is None:
            return None
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)

    def _page(self, after: str | None, limit: int) -> list[IndexItem]:
        db = self._connect()
        if db is None:
            return []
        try:
            rows = db.execute(
                "SELECT id, tenant_id, user_id, title FROM notebooks "
                "WHERE (? IS NULL OR id > ?) ORDER BY id LIMIT ?",
                (after, after, limit),
            ).fetchall()
            items = []
            for nid, tenant, user, title in rows:
                names = [
                    r[0]
                    for r in db.execute(
                        "SELECT title FROM documents WHERE notebook_id = ? "
                        "ORDER BY created_at LIMIT ?",
                        (nid, MAX_SOURCE_NAMES),
                    )
                ]
                items.append(
                    IndexItem(tenant, PRODUCT_ID, user, KIND, nid, search_text(title, *names))
                )
            return items
        finally:
            db.close()

    def _present(self, ids: list[str]) -> set[str]:
        db = self._connect()
        if db is None:
            return set()
        try:
            marks = ",".join("?" * len(ids))
            return {
                r[0] for r in db.execute(f"SELECT id FROM notebooks WHERE id IN ({marks})", ids)
            }
        finally:
            db.close()

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        return await asyncio.to_thread(self._page, after, limit)

    async def present(self, item_ids: list[str]) -> set[str]:
        if not item_ids:
            return set()
        return await asyncio.to_thread(self._present, item_ids)


def notebook_index_source(engine: AsyncEngine) -> NotebookIndexSource:
    return NotebookIndexSource(engine)
