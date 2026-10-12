"""Making speech results searchable (ADR-0041): the words that are indexed, and the source the
platform pages through to backfill the index and to clean it up."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

PRODUCT_ID = "wasifyai-tts"


def index_text(spoken: str, language_name: str) -> str:
    """What a result is found by: the words that were spoken, and the language's name."""
    return search_text(spoken, language_name)


class SpeechIndexSource:
    product_id = PRODUCT_ID
    kind = "speech"

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        from wasifyai_tts.voices import load_catalog

        catalog = load_catalog()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT CAST(id AS text) AS id, tenant_id, user_id, text, language
                    FROM speeches
                    WHERE product_id = :p AND (CAST(:a AS text) IS NULL OR CAST(id AS text) > :a)
                    ORDER BY CAST(id AS text) LIMIT :n
                    """
                ),
                {"p": PRODUCT_ID, "a": after, "n": limit},
            )
            out = []
            for r in rows:
                lang = catalog.language(r[4])
                out.append(
                    IndexItem(
                        r[1], PRODUCT_ID, r[2], self.kind, r[0],
                        index_text(r[3], lang.english if lang else r[4]),
                    )
                )  # fmt: skip
            return out

    async def present(self, item_ids: list[str]) -> set[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT CAST(id AS text) FROM speeches WHERE CAST(id AS text) = ANY(:ids)"),
                {"ids": item_ids},
            )
            return {r[0] for r in rows}
