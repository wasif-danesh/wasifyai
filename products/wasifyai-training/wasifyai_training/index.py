"""Trained models in My creations search (ADR-0041): found by their name, their magic word and what
they were taught. The desktop's table is in `training.db` next to the app's other data."""

import asyncio
import sqlite3
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

PRODUCT_ID = "wasifyai-training"
KIND = "lora"


def training_db(engine: AsyncEngine) -> Path | None:
    """`<data>/training/training.db` for a desktop engine (main database `wasifyai.db`)."""
    if engine.dialect.name != "sqlite" or not engine.url.database:
        return None
    path = Path(engine.url.database).parent / "training" / "training.db"
    return path if path.is_file() else None


class TrainingIndexSource:
    product_id = PRODUCT_ID
    kind = KIND

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    def _connect(self) -> sqlite3.Connection | None:
        path = training_db(self._engine)
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) if path else None

    def _page(self, after: str | None, limit: int) -> list[IndexItem]:
        db = self._connect()
        if db is None:
            return []
        try:
            rows = db.execute(
                "SELECT id, tenant_id, user_id, name, trigger_word, kind FROM models "
                "WHERE (? IS NULL OR id > ?) ORDER BY id LIMIT ?",
                (after, after, limit),
            ).fetchall()
            return [
                IndexItem(
                    t, PRODUCT_ID, u, KIND, i,
                    search_text(". ".join(x for x in (name, word, kind) if x and x.strip())),
                )
                for i, t, u, name, word, kind in rows
            ]  # fmt: skip
        finally:
            db.close()

    def _present(self, ids: list[str]) -> set[str]:
        db = self._connect()
        if db is None:
            return set()
        try:
            marks = ",".join("?" * len(ids))
            return {r[0] for r in db.execute(f"SELECT id FROM models WHERE id IN ({marks})", ids)}
        finally:
            db.close()

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        return await asyncio.to_thread(self._page, after, limit)

    async def present(self, item_ids: list[str]) -> set[str]:
        if not item_ids:
            return set()
        return await asyncio.to_thread(self._present, item_ids)


def training_index_source(engine: AsyncEngine) -> TrainingIndexSource:
    return TrainingIndexSource(engine)
