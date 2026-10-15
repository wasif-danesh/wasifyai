"""Conversations in My creations search (ADR-0041): the words that are indexed, and the source the
platform pages through to backfill the index and to clean it up."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem, search_text
from wasifyai_platform_sdk.sqlite import ensure_tables, is_sqlite

from wasifyai_assistant.store import _DDL, PRODUCT_ID


class ConversationIndexSource:
    product_id = PRODUCT_ID
    kind = "conversation"

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        if is_sqlite(self._engine):
            await ensure_tables(self._engine, "assistant", _DDL)

    async def page(self, after: str | None, limit: int) -> list[IndexItem]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, tenant_id, user_id, title FROM conversations "
                        "WHERE product_id = :p AND (:a IS NULL OR id > :a) ORDER BY id LIMIT :n"
                    ),
                    {"p": PRODUCT_ID, "a": after, "n": limit},
                )
            ).all()
            items: list[IndexItem] = []
            for cid, tenant, user, title in rows:
                said = (
                    await conn.execute(
                        text(
                            "SELECT parts FROM messages WHERE conversation_id = :c "
                            "AND role = 'user' ORDER BY seq LIMIT 50"
                        ),
                        {"c": cid},
                    )
                ).all()
                words = [_text_of(r[0]) for r in said]
                items.append(
                    IndexItem(tenant, PRODUCT_ID, user, self.kind, cid, search_text(title, *words))
                )
            return items

    async def present(self, item_ids: list[str]) -> set[str]:
        if not item_ids:
            return set()
        await self._ready()
        marks = ", ".join(f":i{n}" for n in range(len(item_ids)))
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(f"SELECT id FROM conversations WHERE id IN ({marks})"),
                {f"i{n}": v for n, v in enumerate(item_ids)},
            )
            return {r[0] for r in rows}


def _text_of(raw: str) -> str:
    import json

    try:
        parts = json.loads(raw)
    except ValueError:
        return ""
    return " ".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))


def conversation_index_source(engine: AsyncEngine) -> ConversationIndexSource:
    return ConversationIndexSource(engine)
