"""RAG helpers on pgvector: chunk, embed (through the product's `text.embed` capability), store,
and search. Every row and query is scoped by tenant and product (rule 7)."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import require_context

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]

DIMENSIONS = 768  # matches migration 0003; change both together (ADR-0017)


@dataclass
class Hit:
    document_id: str
    chunk_index: int
    content: str
    metadata: dict[str, Any]
    score: float  # cosine similarity, 1.0 = identical direction


def chunk_text(content: str, size: int = 800, overlap: int = 100) -> list[str]:
    """Paragraph-aware chunks of at most `size` characters, overlapping by `overlap`."""
    if size <= overlap:
        raise ValueError("size must be larger than overlap")
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > size:  # a single oversized paragraph: hard-split with overlap
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:size])
            para = para[size - overlap :]
        if current and len(current) + len(para) + 2 > size:
            chunks.append(current)
            current = current[-overlap:] + "\n\n" + para if overlap else para
            if len(current) > size:
                current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


class RagService:
    def __init__(self, engine: AsyncEngine, embed: Embedder, dims: int = DIMENSIONS):
        self._engine = engine
        self._embed = embed
        self._dims = dims

    async def ingest(
        self,
        collection: str,
        document_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Replace a document's chunks. Returns how many chunks were stored."""
        ctx = require_context()
        chunks = chunk_text(content)
        if not chunks:
            return 0
        vectors = await self._embed(chunks)
        if any(len(v) != self._dims for v in vectors):
            raise ValueError(
                f"embedding size {len(vectors[0])} != table size {self._dims}: "
                "the embedding model changed; add a migration and re-embed (ADR-0017)"
            )
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM rag_chunks WHERE tenant_id=:t AND product_id=:p "
                    "AND collection=:c AND document_id=:d"
                ),
                {"t": ctx.tenant_id, "p": ctx.product_id, "c": collection, "d": document_id},
            )
            for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True)):
                await conn.execute(
                    text(
                        """
                        INSERT INTO rag_chunks (id, tenant_id, product_id, collection, document_id,
                                                chunk_index, content, metadata, embedding)
                        VALUES (:id, :t, :p, :c, :d, :i, :content, CAST(:meta AS json),
                                CAST(:vec AS vector))
                        """
                    ),
                    {
                        "id": uuid4(),
                        "t": ctx.tenant_id,
                        "p": ctx.product_id,
                        "c": collection,
                        "d": document_id,
                        "i": i,
                        "content": chunk,
                        "meta": json.dumps(metadata or {}),
                        "vec": _vec(vec),
                    },
                )
        return len(chunks)

    async def search(self, collection: str, query: str, k: int = 5) -> list[Hit]:
        ctx = require_context()
        (qvec,) = await self._embed([query])
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT document_id, chunk_index, content, metadata, "
                    "1 - (embedding <=> CAST(:q AS vector)) AS score FROM rag_chunks "
                    "WHERE tenant_id=:t AND product_id=:p AND collection=:c "
                    "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
                ),
                {"q": _vec(qvec), "t": ctx.tenant_id, "p": ctx.product_id, "c": collection, "k": k},
            )
            return [Hit(r[0], r[1], r[2], r[3], float(r[4])) for r in rows]

    async def delete_document(self, collection: str, document_id: str) -> None:
        ctx = require_context()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM rag_chunks WHERE tenant_id=:t AND product_id=:p "
                    "AND collection=:c AND document_id=:d"
                ),
                {"t": ctx.tenant_id, "p": ctx.product_id, "c": collection, "d": document_id},
            )
