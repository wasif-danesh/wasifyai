# SPDX-License-Identifier: Apache-2.0
"""Notebooks in My creations search (ADR-0041, ADR-0065 decision 12): a notebook is found by its
title and the names of its sources, in any language.

On the desktop the notebooks live in their own SQLite file next to the main one, so the source reads
that file directly and read-only. On the web they are in the `notebooks` schema of the main Postgres
database (`NotebookStore.on_postgres`) and the source reads them through the engine's connection.
"""

import asyncio
import sqlite3
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
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
                try:
                    outputs = [
                        r[0]
                        for r in db.execute(
                            "SELECT title FROM artifacts WHERE notebook_id = ? AND title != '' "
                            "AND status = 'ready' ORDER BY created_at LIMIT 20",
                            (nid,),
                        )
                    ]
                except sqlite3.OperationalError:  # a file from before outputs existed
                    outputs = []
                items.append(
                    IndexItem(
                        tenant, PRODUCT_ID, user, KIND, nid, search_text(title, *names, *outputs)
                    )
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


class PgNotebookIndexSource:
    """The same listing from the Postgres schema of the web profile. Until the store has made its
    schema (nothing was ever added) there is nothing to list."""

    product_id = PRODUCT_ID
    kind = KIND

    def __init__(self, engine: AsyncEngine, schema: str = "notebooks"):
        self._engine = engine
        self._schema = schema

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        s = self._schema
        try:
            async with self._engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            f"SELECT id, tenant_id, user_id, title FROM {s}.notebooks "
                            "WHERE (CAST(:a AS text) IS NULL OR id > :a) ORDER BY id LIMIT :n"
                        ),
                        {"a": after, "n": limit},
                    )
                ).all()
                items = []
                for nid, tenant, user, title in rows:
                    names = (
                        await conn.execute(
                            text(
                                f"SELECT title FROM {s}.documents WHERE notebook_id = :n "
                                "ORDER BY created_at LIMIT :k"
                            ),
                            {"n": nid, "k": MAX_SOURCE_NAMES},
                        )
                    ).scalars()
                    outputs = (
                        await conn.execute(
                            text(
                                f"SELECT title FROM {s}.artifacts WHERE notebook_id = :n "
                                "AND title != '' AND status = 'ready' ORDER BY created_at LIMIT 20"
                            ),
                            {"n": nid},
                        )
                    ).scalars()
                    items.append(
                        IndexItem(
                            tenant,
                            PRODUCT_ID,
                            user,
                            KIND,
                            nid,
                            search_text(title, *names, *outputs),
                        )
                    )
                return items
        except ProgrammingError:  # the schema does not exist yet
            return []

    async def present(self, item_ids: list[str]) -> set[str]:
        if not item_ids:
            return set()
        try:
            async with self._engine.connect() as conn:
                rows = await conn.execute(
                    text(f"SELECT id FROM {self._schema}.notebooks WHERE id = ANY(:ids)"),
                    {"ids": item_ids},
                )
                return {r[0] for r in rows}
        except ProgrammingError:
            return set()


def notebook_index_source(engine: AsyncEngine) -> NotebookIndexSource | PgNotebookIndexSource:
    if engine.dialect.name == "postgresql":
        return PgNotebookIndexSource(engine)
    return NotebookIndexSource(engine)
