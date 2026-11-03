# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""Creative Studio's projects in My creations search (ADR-0041): found by their title, idea, cast, places, shots and
lyrics. The desktop's table is in `creative.db` next to the app's other data; the web's in the `creative` schema of
its Postgres."""

import asyncio
import json
import sqlite3
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

from wasifyai_creative.cut import captions_of
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
            has_cuts = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cuts'"
            ).fetchone()
            cut = (
                "(SELECT r.cut FROM cut_revisions r JOIN cuts c ON c.project_id = r.project_id "
                "AND r.n = c.at WHERE r.project_id = projects.id)"
                if has_cuts
                else "NULL"
            )
            rows = db.execute(
                f"SELECT id, tenant_id, user_id, title, brief, plan, facts, {cut} FROM projects "
                "WHERE (? IS NULL OR id > ?) ORDER BY id LIMIT ?",
                (after, after, limit),
            ).fetchall()
            return [_item(*row) for row in rows]
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

    # on Postgres (the web) the projects are in the `creative` schema
    @property
    def _postgres(self) -> bool:
        return self._engine.dialect.name == "postgresql"

    async def _pg_page(self, after: str | None, limit: int) -> list[IndexItem]:
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT p.id, p.tenant_id, p.user_id, p.title, p.brief, p.plan, p.facts, "
                        "(SELECT r.cut FROM creative.cut_revisions r JOIN creative.cuts c "
                        "ON c.project_id = r.project_id AND r.n = c.at WHERE r.project_id = p.id) "
                        "FROM creative.projects p WHERE (CAST(:a AS text) IS NULL OR p.id > :a) "
                        "ORDER BY p.id LIMIT :n"
                    ),
                    {"a": after, "n": limit},
                )
            ).all()
        return [_item(*row) for row in rows]

    async def _pg_present(self, ids: list[str]) -> set[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT id FROM creative.projects WHERE id = ANY(:ids)"), {"ids": ids}
            )
            return {r[0] for r in rows}

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        if self._postgres:
            try:
                return await self._pg_page(after, limit)
            except (
                Exception
            ):  # the web has no creative tables (the product is off): nothing to index
                return []
        return await asyncio.to_thread(self._page, after, limit)

    async def present(self, item_ids: list[str]) -> set[str]:
        if not item_ids:
            return set()
        if self._postgres:
            try:
                return await self._pg_present(item_ids)
            except Exception:
                return set(item_ids)  # unknown is not gone: never remove what cannot be checked
        return await asyncio.to_thread(self._present, item_ids)


def _item(
    i: str,
    t: str,
    u: str,
    title: str,
    brief: str,
    plan: str | None,
    facts: str | None,
    kept: str | None,
) -> IndexItem:
    lines = json.loads(facts or "{}").get("lines", [])
    lyrics = " ".join(x["text"] for x in lines)
    lyrics = f"{lyrics} {captions_of(json.loads(kept) if kept else None)}".strip()
    words = index_words(title, json.loads(brief), json.loads(plan) if plan else None, lyrics)
    return IndexItem(t, PRODUCT_ID, u, KIND, i, search_text(*words))


def creative_index_source(engine: AsyncEngine) -> CreativeIndexSource:
    return CreativeIndexSource(engine)
