"""Making videos searchable (ADR-0041): the words that are indexed, and the source the platform
pages through to backfill the index and to clean it up. Only finished clips are indexed."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

PRODUCT_ID = "wasifyai-video"


def index_text(prompt: str) -> str:
    """What a clip is found by: the prompt that made it."""
    return search_text(prompt)


class VideoIndexSource:
    product_id = PRODUCT_ID
    kind = "video"

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT CAST(id AS text) AS id, tenant_id, user_id, prompt
                    FROM videos
                    WHERE product_id = :p AND status = 'done'
                      AND (CAST(:a AS text) IS NULL OR CAST(id AS text) > :a)
                    ORDER BY CAST(id AS text) LIMIT :n
                    """
                ),
                {"p": PRODUCT_ID, "a": after, "n": limit},
            )
            return [
                IndexItem(r[1], PRODUCT_ID, r[2], self.kind, r[0], index_text(r[3])) for r in rows
            ]

    async def present(self, item_ids: list[str]) -> set[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT CAST(id AS text) FROM videos "
                    "WHERE status = 'done' AND CAST(id AS text) = ANY(:ids)"
                ),
                {"ids": item_ids},
            )
            return {r[0] for r in rows}
