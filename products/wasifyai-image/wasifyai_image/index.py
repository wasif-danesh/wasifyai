"""Making images searchable (ADR-0041): the words that are indexed, and the source the platform
pages through to backfill the index and to clean it up."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, IndexSource, search_text
from wasifyai_platform_sdk.sqlite import is_sqlite, migrate

PRODUCT_ID = "wasifyai-image"


def index_text(prompt: str) -> str:
    """What an image is found by: the prompt that made it."""
    return search_text(prompt)


class ImageIndexSource:
    product_id = PRODUCT_ID
    kind = "image"

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT CAST(id AS text) AS id, tenant_id, user_id, prompt
                    FROM images
                    WHERE product_id = :p AND (CAST(:a AS text) IS NULL OR CAST(id AS text) > :a)
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
                text("SELECT CAST(id AS text) FROM images WHERE CAST(id AS text) = ANY(:ids)"),
                {"ids": item_ids},
            )
            return {r[0] for r in rows}


class SqliteImageIndexSource:
    """The same listing on the desktop profile's SQLite file (ADR-0056)."""

    product_id = PRODUCT_ID
    kind = "image"

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        from wasifyai_image.images import SQLITE_MIGRATIONS

        await migrate(self._engine, "images", SQLITE_MIGRATIONS)

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT id, tenant_id, user_id, prompt FROM images
                    WHERE product_id = :p AND (:a IS NULL OR id > :a)
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
                    text(f"SELECT id FROM images WHERE id IN ({marks})"),
                    {f"i{n}": v for n, v in enumerate(chunk)},
                )
                found.update(r[0] for r in rows)
        return found


def image_index_source(engine: AsyncEngine) -> IndexSource:
    """The source for the database the engine speaks to (Postgres on the web, SQLite on desktop)."""
    return SqliteImageIndexSource(engine) if is_sqlite(engine) else ImageIndexSource(engine)
