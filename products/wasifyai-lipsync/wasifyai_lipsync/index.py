"""Making lip syncs searchable (ADR-0041, ADR-0044): the words that are indexed, and the source the
platform pages through to backfill the index and to clean it up. Only finished ones are indexed."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

PRODUCT_ID = "wasifyai-lipsync"


def index_text(script: str, transcript: str, style: str) -> str:
    """What a lip sync is found by: what is said (the script, or the words of the voice) and the
    style asked for."""
    return search_text(" ".join(p for p in (script or transcript, style) if p))


class LipSyncIndexSource:
    product_id = PRODUCT_ID
    kind = "lipsync"

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT CAST(id AS text) AS id, tenant_id, user_id, script, transcript, style
                    FROM lipsyncs
                    WHERE product_id = :p AND status = 'done'
                      AND (CAST(:a AS text) IS NULL OR CAST(id AS text) > :a)
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
                text(
                    "SELECT CAST(id AS text) FROM lipsyncs "
                    "WHERE status = 'done' AND CAST(id AS text) = ANY(:ids)"
                ),
                {"ids": item_ids},
            )
            return {r[0] for r in rows}
