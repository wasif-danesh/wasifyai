"""The search index over a user's creations (ADR-0041).

`CreationIndex` is the logic (embed, store, search, reconcile); an `IndexStore` holds the rows:
`PostgresIndexStore` with pgvector in production, `InMemoryIndexStore` in tests. Every query is
scoped by tenant and user, and a user's search never sees another user's rows.

Search returns exact-word matches first (every word of the query appears in the text, in any
script), then the nearest meanings at or above a similarity floor, so "nothing found" can
be the answer."""

import asyncio
import logging
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import (
    IndexItem,
    IndexSource,
    RunContext,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.search import MAX_TEXT_CHARS

log = logging.getLogger(__name__)

DIMENSIONS = 1024  # matches migration 0011
PLATFORM = "platform"  # the product id of platform-level work (a search is not any product's)
MAX_WORDS = 12
Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


@dataclass(frozen=True)
class Hit:
    kind: str
    product_id: str
    item_id: str
    score: float  # cosine similarity for meaning; 1.0 for an exact-word match
    match: str  # "words" or "meaning"


class IndexStore(Protocol):
    async def upsert(self, item: IndexItem, model: str, vector: list[float]) -> None: ...

    async def delete(self, tenant_id: str, product_id: str, item_id: str) -> None: ...

    async def delete_ids(self, product_id: str, item_ids: list[str]) -> None: ...

    async def nearest(
        self, tenant_id: str, user_id: str, vector: list[float], kind: str | None, limit: int
    ) -> list[Hit]: ...

    async def with_words(
        self, tenant_id: str, user_id: str, words: list[str], kind: str | None, limit: int
    ) -> list[Hit]: ...

    async def models(self, product_id: str, item_ids: list[str]) -> dict[str, str]:
        """Item id -> the model that embedded it, for the ids that are indexed."""
        ...

    async def ids_after(self, product_id: str, after: str | None, limit: int) -> list[str]: ...


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def like_patterns(words: list[str]) -> list[str]:
    """`%word%` patterns for LIKE, with the characters LIKE treats specially escaped."""
    out = []
    for w in words:
        esc = w.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        out.append(f"%{esc}%")
    return out


_CJK = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def long_enough(query: str) -> bool:
    """A search needs two characters, except in Chinese, Japanese and Korean, where one character
    can be a whole word (龙 is "dragon")."""
    q = query.strip()
    return len(q) >= 2 or bool(_CJK.search(q))


def query_words(query: str) -> list[str]:
    return [w for w in query.lower().split() if w][:MAX_WORDS]


class PostgresIndexStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def upsert(self, item: IndexItem, model: str, vector: list[float]) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO creation_index
                        (id, tenant_id, product_id, user_id, kind, item_id, text, model, embedding)
                    VALUES (:id, :t, :p, :u, :k, :i, :x, :m, CAST(:v AS vector))
                    ON CONFLICT (tenant_id, product_id, item_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id, kind = EXCLUDED.kind, text = EXCLUDED.text,
                        model = EXCLUDED.model, embedding = EXCLUDED.embedding
                    """
                ),
                {
                    "id": uuid4(), "t": item.tenant_id, "p": item.product_id, "u": item.user_id,
                    "k": item.kind, "i": item.item_id, "x": item.text[:MAX_TEXT_CHARS],
                    "m": model, "v": _vec(vector),
                },
            )  # fmt: skip

    async def delete(self, tenant_id: str, product_id: str, item_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM creation_index WHERE tenant_id = :t AND product_id = :p "
                    "AND item_id = :i"
                ),
                {"t": tenant_id, "p": product_id, "i": item_id},
            )

    async def delete_ids(self, product_id: str, item_ids: list[str]) -> None:
        if not item_ids:
            return
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM creation_index WHERE product_id = :p AND item_id = ANY(:ids)"),
                {"p": product_id, "ids": item_ids},
            )

    async def nearest(
        self, tenant_id: str, user_id: str, vector: list[float], kind: str | None, limit: int
    ) -> list[Hit]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT product_id, kind, item_id,
                           1 - (embedding <=> CAST(:v AS vector)) AS sim
                    FROM creation_index
                    WHERE tenant_id = :t AND user_id = :u
                      AND (CAST(:k AS text) IS NULL OR kind = :k)
                    ORDER BY embedding <=> CAST(:v AS vector)
                    LIMIT :n
                    """
                ),
                {"t": tenant_id, "u": user_id, "k": kind, "v": _vec(vector), "n": limit},
            )
            return [Hit(r[1], r[0], r[2], float(r[3]), "meaning") for r in rows]

    async def with_words(
        self, tenant_id: str, user_id: str, words: list[str], kind: str | None, limit: int
    ) -> list[Hit]:
        if not words:
            return []
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT product_id, kind, item_id FROM creation_index
                    WHERE tenant_id = :t AND user_id = :u
                      AND (CAST(:k AS text) IS NULL OR kind = :k)
                      AND lower(text) LIKE ALL (CAST(:pats AS text[]))
                    ORDER BY created_at DESC
                    LIMIT :n
                    """
                ),
                {"t": tenant_id, "u": user_id, "k": kind, "pats": like_patterns(words), "n": limit},
            )
            return [Hit(r[1], r[0], r[2], 1.0, "words") for r in rows]

    async def models(self, product_id: str, item_ids: list[str]) -> dict[str, str]:
        if not item_ids:
            return {}
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT item_id, model FROM creation_index "
                    "WHERE product_id = :p AND item_id = ANY(:ids)"
                ),
                {"p": product_id, "ids": item_ids},
            )
            return {r[0]: r[1] for r in rows}

    async def ids_after(self, product_id: str, after: str | None, limit: int) -> list[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT item_id FROM creation_index WHERE product_id = :p "
                    "AND (CAST(:a AS text) IS NULL OR item_id > :a) ORDER BY item_id LIMIT :n"
                ),
                {"p": product_id, "a": after, "n": limit},
            )
            return [r[0] for r in rows]


class InMemoryIndexStore:
    """For tests: the same behaviour in plain Python."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], tuple[IndexItem, str, list[float]]] = {}

    async def upsert(self, item: IndexItem, model: str, vector: list[float]) -> None:
        self.rows[(item.tenant_id, item.product_id, item.item_id)] = (item, model, vector)

    async def delete(self, tenant_id: str, product_id: str, item_id: str) -> None:
        self.rows.pop((tenant_id, product_id, item_id), None)

    async def delete_ids(self, product_id: str, item_ids: list[str]) -> None:
        for key in [k for k in self.rows if k[1] == product_id and k[2] in set(item_ids)]:
            del self.rows[key]

    def _mine(self, tenant_id: str, user_id: str, kind: str | None):
        return [
            (item, vec)
            for (item, _model, vec) in self.rows.values()
            if (item.tenant_id, item.user_id) == (tenant_id, user_id) and kind in (None, item.kind)
        ]

    async def nearest(
        self, tenant_id: str, user_id: str, vector: list[float], kind: str | None, limit: int
    ) -> list[Hit]:
        def cos(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b, strict=True))
            return dot / ((math.hypot(*a) * math.hypot(*b)) or 1.0)

        hits = [
            Hit(i.kind, i.product_id, i.item_id, cos(vector, v), "meaning")
            for i, v in self._mine(tenant_id, user_id, kind)
        ]
        return sorted(hits, key=lambda h: -h.score)[:limit]

    async def with_words(
        self, tenant_id: str, user_id: str, words: list[str], kind: str | None, limit: int
    ) -> list[Hit]:
        if not words:
            return []
        return [
            Hit(i.kind, i.product_id, i.item_id, 1.0, "words")
            for i, _ in self._mine(tenant_id, user_id, kind)
            if all(w in i.text.lower() for w in words)
        ][:limit]

    async def models(self, product_id: str, item_ids: list[str]) -> dict[str, str]:
        return {
            k[2]: v[1] for k, v in self.rows.items() if k[1] == product_id and k[2] in set(item_ids)
        }

    async def ids_after(self, product_id: str, after: str | None, limit: int) -> list[str]:
        ids = sorted(
            k[2] for k in self.rows if k[1] == product_id and (after is None or k[2] > after)
        )
        return ids[:limit]


class CreationIndex:
    """Embeds, stores and searches. `model` names the embedder that made each row: a row made by a
    different one is re-embedded by the reconciler."""

    def __init__(
        self,
        store: IndexStore,
        embed: Embedder,
        model: str,
        min_similarity: float,
        timeout_s: float = 5.0,
    ):
        self._store = store
        self._embed = embed
        self.model = model
        self.min_similarity = min_similarity
        self._timeout = timeout_s

    async def _vector(self, tenant_id: str, user_id: str, text_: str) -> list[float]:
        token = set_context(RunContext(tenant_id, PLATFORM, user_id))  # for the usage event
        try:
            async with asyncio.timeout(self._timeout):
                (vector,) = await self._embed([text_])
            return vector
        finally:
            reset_context(token)

    async def index_item(self, item: IndexItem) -> None:
        vector = await self._vector(item.tenant_id, item.user_id, item.text[:MAX_TEXT_CHARS])
        await self._store.upsert(item, self.model, vector)

    async def index(
        self, tenant_id: str, product_id: str, user_id: str, kind: str, item_id: str, text_: str
    ) -> None:
        await self.index_item(IndexItem(tenant_id, product_id, user_id, kind, item_id, text_))

    async def remove(self, tenant_id: str, product_id: str, item_id: str) -> None:
        await self._store.delete(tenant_id, product_id, item_id)

    async def search(
        self, tenant_id: str, user_id: str, query: str, kind: str | None, limit: int
    ) -> tuple[list[Hit], bool]:
        """Returns (hits, degraded). `degraded` means the embedder did not answer and only exact
        words were searched."""
        words = query_words(query)
        exact = await self._store.with_words(tenant_id, user_id, words, kind, limit)
        try:
            vector = await self._vector(tenant_id, user_id, query.strip())
        except Exception:
            log.warning("search: the embedder did not answer; exact words only")
            return exact, True
        near = await self._store.nearest(tenant_id, user_id, vector, kind, limit)
        seen = {(h.product_id, h.item_id) for h in exact}
        meaning = [
            h
            for h in near
            if h.score >= self.min_similarity and (h.product_id, h.item_id) not in seen
        ]
        return (exact + meaning)[:limit], False

    async def reconcile(self, sources: list[IndexSource], budget: int = 50) -> dict[str, int]:
        """Fill gaps and remove orphans. Embeds at most `budget` items per call, so the work is
        spread over several runs and never competes with a render."""
        embedded = removed = 0
        for src in sources:
            after: str | None = None
            while True:  # rows whose item is gone
                ids = await self._store.ids_after(src.product_id, after, 200)
                if not ids:
                    break
                alive = await src.present(ids)
                dead = [i for i in ids if i not in alive]
                await self._store.delete_ids(src.product_id, dead)
                removed += len(dead)
                after = ids[-1]
            after = None
            while embedded < budget:  # items with no row, or made by another embedder
                items = await src.page(after, 100)
                if not items:
                    break
                have = await self._store.models(src.product_id, [i.item_id for i in items])
                for item in items:
                    if embedded >= budget:
                        break
                    if have.get(item.item_id) == self.model or not item.text.strip():
                        continue
                    try:
                        await self.index_item(item)
                        embedded += 1
                    except Exception:
                        log.warning("could not index %s %s; will retry", item.kind, item.item_id)
                        return {"embedded": embedded, "removed": removed}  # the embedder is down
                after = items[-1].item_id
        return {"embedded": embedded, "removed": removed}


class ContextIndexer:
    """What `Capabilities.index_creation` calls: indexes for the user of the current run."""

    def __init__(self, index: CreationIndex):
        self._index = index

    async def index(self, kind: str, item_id: str, text_: str) -> None:
        from wasifyai_platform_sdk import require_context

        ctx = require_context()
        await self._index.index(ctx.tenant_id, ctx.product_id, ctx.user_id, kind, item_id, text_)


async def reconcile_forever(
    index: CreationIndex, sources: Callable[[], list[IndexSource]], every_s: int, batch: int = 200
) -> None:
    """Like the upload sweeper: check now, then every `every_s` seconds, and never die."""
    while True:
        try:
            report = await index.reconcile(sources(), batch)
            if any(report.values()):
                log.info("search index: %s", report)
        except Exception:
            log.exception("the search index check failed; it will try again")
        await asyncio.sleep(every_s)
