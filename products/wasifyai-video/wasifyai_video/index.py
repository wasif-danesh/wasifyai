"""Making videos searchable (ADR-0041): the words that are indexed, and the source the platform
pages through to backfill the index and to clean it up. Only finished clips are indexed."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, IndexSource, search_text
from wasifyai_platform_sdk.sqlite import ensure_tables, is_sqlite

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


class SqliteVideoIndexSource:
    """The same listing on the desktop profile's SQLite file (ADR-0056)."""

    product_id = PRODUCT_ID
    kind = "video"

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        from wasifyai_video.videos import _SQLITE_DDL

        await ensure_tables(self._engine, "videos", _SQLITE_DDL)

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT id, tenant_id, user_id, prompt FROM videos
                    WHERE product_id = :p AND status = 'done' AND (:a IS NULL OR id > :a)
                    ORDER BY id LIMIT :n
                    """
                ),
                {"p": PRODUCT_ID, "a": after, "n": limit},
            )
            return [
                IndexItem(r[1], PRODUCT_ID, r[2], self.kind, r[0], index_text(r[3])) for r in rows
            ]

    async def present(self, item_ids: list[str]) -> set[str]:
        await self._ready()
        found: set[str] = set()
        async with self._engine.connect() as conn:
            for i in range(0, len(item_ids), 500):
                chunk = item_ids[i : i + 500]
                marks = ",".join(f":i{n}" for n in range(len(chunk)))
                rows = await conn.execute(
                    text(f"SELECT id FROM videos WHERE status = 'done' AND id IN ({marks})"),
                    {f"i{n}": v for n, v in enumerate(chunk)},
                )
                found.update(r[0] for r in rows)
        return found


class CombinedIndexSource:
    """The clips and the Video Builder compositions as one source (a product registers one):
    every item carries its own kind, and a page is the next `limit` items of both, in id order."""

    product_id = PRODUCT_ID
    kind = "video"

    def __init__(self, *sources: IndexSource):
        self._sources = sources

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        items = [i for s in self._sources for i in await s.page(after, limit)]
        return sorted(items, key=lambda i: i.item_id)[:limit]

    async def present(self, item_ids: list[str]) -> set[str]:
        found: set[str] = set()
        for s in self._sources:
            found |= await s.present(item_ids)
        return found


def video_index_source(engine: AsyncEngine) -> IndexSource:
    """The source for the database the engine speaks to (Postgres on the web, SQLite on desktop,
    where Video Builder's compositions are searchable too)."""
    if not is_sqlite(engine):
        return VideoIndexSource(engine)
    from wasifyai_video.builder.index import BuilderIndexSource

    return CombinedIndexSource(SqliteVideoIndexSource(engine), BuilderIndexSource(engine))
