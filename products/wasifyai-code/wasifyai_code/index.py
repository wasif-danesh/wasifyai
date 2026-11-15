"""Coding sessions in My creations search (ADR-0041): found by their title, their project's name
and what was asked first. And the extensions a person added (ADR-0104, decision 10): found by
their name and by what they say they are for. One source covers both kinds; an item carries its
own. The desktop's table is in `code/code.db` beside the app's other data.
Coding is on the desktop only (ADR-0101, decision 8), so on the web there is nothing to list."""

import asyncio
import sqlite3
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

from wasifyai_code import PRODUCT_ID, extensions
from wasifyai_code.runtime import EXTENSION_KIND, KIND, words_of

SQL = (
    "SELECT s.id, s.tenant_id, s.user_id, s.title, w.name, "
    "(SELECT t.request FROM turns t WHERE t.session_id = s.id ORDER BY t.position LIMIT 1) "
    "FROM sessions s LEFT JOIN workspaces w ON w.id = s.workspace_id "
    "WHERE (? IS NULL OR s.id > ?) ORDER BY s.id LIMIT ?"
)


ADDED_SQL = (
    "SELECT id, tenant_id, user_id, title, path FROM extensions "
    "WHERE (? IS NULL OR id > ?) ORDER BY id LIMIT ?"
)


def _has(db: sqlite3.Connection, table: str) -> bool:
    found = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return found is not None


def _extension_words(item: str, title: str, path: str) -> str:
    """What an added extension is found by. Its description is in its own file."""
    try:
        skill = extensions.read_skill(
            Path(path), id=f"{extensions.ADDED}:{item}", source=extensions.ADDED, title=title
        )
        return extensions.words_of(skill)
    except extensions.ExtensionError:
        return f"{title}. A skill for the coding agent"


def code_db(engine: AsyncEngine) -> Path | None:
    """`<data>/code/code.db` for a desktop engine (main database `wasifyai.db`)."""
    if engine.dialect.name != "sqlite" or not engine.url.database:
        return None
    path = Path(engine.url.database).parent / "code" / "code.db"
    return path if path.is_file() else None


class CodeIndexSource:
    product_id = PRODUCT_ID
    kind = KIND

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    def _connect(self) -> sqlite3.Connection | None:
        path = code_db(self._engine)
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) if path else None

    def _page(self, after: str | None, limit: int) -> list[IndexItem]:
        db = self._connect()
        if db is None:
            return []
        try:
            rows = db.execute(SQL, (after, after, limit)).fetchall()
            found = [
                IndexItem(
                    tenant, PRODUCT_ID, user, KIND, item,
                    search_text(words_of(title or "", project or "", first or "")),
                )
                for item, tenant, user, title, project, first in rows
            ]  # fmt: skip
            if _has(db, "extensions"):
                found += [
                    IndexItem(
                        tenant, PRODUCT_ID, user, EXTENSION_KIND, item,
                        search_text(_extension_words(item, title or "", path or "")),
                    )
                    for item, tenant, user, title, path in db.execute(
                        ADDED_SQL, (after, after, limit)
                    ).fetchall()
                ]  # fmt: skip
            # both kinds in one order of ids, as the platform pages through them
            return sorted(found, key=lambda i: i.item_id)[:limit]
        finally:
            db.close()

    def _present(self, ids: list[str]) -> set[str]:
        db = self._connect()
        if db is None:
            return set(ids)  # unknown is not gone: never remove what cannot be checked
        try:
            marks = ",".join("?" * len(ids))
            there: set[str] = set()
            for table in ("sessions", "extensions"):
                if _has(db, table):
                    sql = f"SELECT id FROM {table} WHERE id IN ({marks})"
                    there |= {r[0] for r in db.execute(sql, ids)}
            return there
        finally:
            db.close()

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        return await asyncio.to_thread(self._page, after, limit)

    async def present(self, item_ids: list[str]) -> set[str]:
        if not item_ids:
            return set()
        return await asyncio.to_thread(self._present, item_ids)


def code_index_source(engine: AsyncEngine) -> CodeIndexSource:
    return CodeIndexSource(engine)
