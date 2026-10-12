"""Making transcripts searchable (ADR-0041, ADR-0043): the words that are indexed, and the source
the platform pages through to backfill the index and clean it up. Only finished ones are indexed.

The index holds the first part of a long transcript (the embedder reads about 6000 characters);
indexing a long one in several pieces is a planned change (ADR-0043)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text

from wasifyai_stt.languages import load_languages

PRODUCT_ID = "wasifyai-stt"


def index_text(title: str, language: str, words: str) -> str:
    """What a transcript is found by: its title, the language's name (in English, so "Bengali" finds
    it) and what was said. `language` is the code stored with the transcript."""
    known = load_languages().get(language)
    return search_text(title, known.english if known else language, words)


class TranscriptIndexSource:
    product_id = PRODUCT_ID
    kind = "transcript"

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT CAST(id AS text) AS id, tenant_id, user_id, title, language, text
                    FROM transcripts
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
                    "SELECT CAST(id AS text) FROM transcripts "
                    "WHERE status = 'done' AND CAST(id AS text) = ANY(:ids)"
                ),
                {"ids": item_ids},
            )
            return {r[0] for r in rows}
