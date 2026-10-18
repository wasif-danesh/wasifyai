# SPDX-License-Identifier: Apache-2.0
"""Search every notebook of one person at once, for the assistant's `search_notebooks` tool.

The same hybrid retrieval as a notebook's own chat, run per notebook and merged by the blended
score (both legs score on absolute 0..1 scales, so scores compare across notebooks). The assistant
gets passages with the notebook and source they came from; the notebook's chat stays the place for
cited answers.
"""

import asyncio
from typing import Any

from wasifyai_platform_sdk import ToolUnavailable

from wasifyai_notebooks.components import Unavailable
from wasifyai_notebooks.retrieval import retrieve
from wasifyai_notebooks.runtime import Runtime

MAX_NOTEBOOKS = 40  # the most recently used notebooks that have a source ready
PER_NOTEBOOK = 3
PER_DOCUMENT = 2  # one long source should not fill every slot
PASSAGE_CHARS = 700


def _trim(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= PASSAGE_CHARS else flat[: PASSAGE_CHARS - 1].rstrip() + "…"


def _search(
    rt: Runtime, tenant: str, user: str, query: str, vector: list[float], weight: float, limit: int
) -> list[dict[str, Any]]:
    notebooks = [n for n in rt.store.list_notebooks(tenant, user) if n["ready"] > 0]
    found: list[tuple[float, dict[str, Any]]] = []
    with rt.store.connect() as db:
        for nb in notebooks[:MAX_NOTEBOOKS]:
            hits = retrieve(db, nb["id"], query, vector, weight=weight, top_k=PER_NOTEBOOK)
            for h in hits:
                found.append(
                    (
                        h.blended,
                        {
                            "notebook_id": nb["id"],
                            "notebook": nb["title"],
                            "document_id": h.document_id,
                            "title": h.title,
                            "text": _trim(h.content),
                        },
                    )
                )
    found.sort(key=lambda f: -f[0])
    taken: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for _, row in found:
        if taken.get(row["document_id"], 0) >= PER_DOCUMENT:
            continue
        taken[row["document_id"]] = taken.get(row["document_id"], 0) + 1
        out.append(row)
        if len(out) == limit:
            break
    return out


async def search_across(
    rt: Runtime, tenant: str, user: str, query: str, limit: int = 5
) -> list[dict[str, Any]]:
    """The best passages across the person's notebooks, best first. Raises `ToolUnavailable` when
    the search model is not on this computer."""
    query = query.strip()
    if not query:
        return []
    try:
        embedder = rt.components.embedder()
    except Unavailable as e:
        raise ToolUnavailable(e.message) from None
    vector = await asyncio.to_thread(rt.query_vector, embedder, tenant, user, query, "assistant")
    return await asyncio.to_thread(
        _search, rt, tenant, user, query, vector, embedder.spec.semantic_weight, limit
    )
