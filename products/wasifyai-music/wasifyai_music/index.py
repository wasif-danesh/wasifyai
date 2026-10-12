"""Making songs searchable (ADR-0041): the words that are indexed, and the source the platform pages
through to backfill the index and to clean it up.

Every new kind of creation needs the same three things: text when it is saved, removal when it is
deleted, and an `IndexSource`."""

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

PRODUCT_ID = "wasifyai-music"
_SECTION = re.compile(r"^\s*\[[^\]\n]{1,40}\]\s*$", re.MULTILINE)  # [verse], [chorus] ...


def index_text(title: str, style: str, lyrics: str) -> str:
    """What a song is found by: its title, style tags and lyrics without the section tags."""
    return search_text(title, style, _SECTION.sub("", lyrics))


class SongIndexSource:
    product_id = PRODUCT_ID
    kind = "song"

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT CAST(id AS text) AS id, tenant_id, user_id, title, style, lyrics
                    FROM songs
                    WHERE product_id = :p AND (CAST(:a AS text) IS NULL OR CAST(id AS text) > :a)
                    ORDER BY CAST(id AS text) LIMIT :n
                    """
                ),
                {"p": PRODUCT_ID, "a": after, "n": limit},
            )
            return [
                IndexItem(r[1], PRODUCT_ID, r[2], self.kind, r[0], index_text(r[3], r[4], r[5]))
                for r in rows
            ]

    async def present(self, item_ids: list[str]) -> set[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT CAST(id AS text) FROM songs WHERE CAST(id AS text) = ANY(:ids)"),
                {"ids": item_ids},
            )
            return {r[0] for r in rows}
