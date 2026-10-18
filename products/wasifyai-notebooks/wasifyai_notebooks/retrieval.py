# SPDX-License-Identifier: Apache-2.0
# Adapted from SurfSense (Apache-2.0), surfsense_local/backend/shared/search.py, commit 622c1ded8:
# the same two legs, coverage score and blend, on `sqlite3` instead of SQLAlchemy.
# See ../PROVENANCE.md.
"""Rank a notebook's passages against a question.

A keyword leg (FTS5 BM25) and a semantic leg (sqlite-vec nearest neighbours) each propose
candidates; a weighted blend of both decides the order. Both legs score on absolute 0..1
scales, so a leg with nothing to say adds nothing. Measured on the E0 corpus
(docs/spikes/surfsense-investigation.md section 9): hybrid 22 of 24 at rank 1, dense 17, lexical 19.
"""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import sqlite_vec

from wasifyai_notebooks.tokenizer import terms

# Each leg proposes this many for recall; the blend orders the union.
CANDIDATES = 20

Mode = Literal["hybrid", "dense", "lexical"]


@dataclass(frozen=True)
class Hit:
    """A passage a question reached, and where it sits."""

    chunk_id: int
    document_id: str
    title: str
    content: str
    start_line: int | None
    end_line: int | None
    score: float  # cosine similarity: how close the passage is, not where it ranks
    blended: float = 0.0  # the ranking score (0..1), comparable across notebooks


def retrieve(
    db: sqlite3.Connection,
    notebook_id: str,
    query: str,
    vector: Sequence[float],
    *,
    weight: float,
    top_k: int = 5,
    document_ids: Sequence[str] | None = None,
    mode: Mode = "hybrid",
) -> list[Hit]:
    """The best `top_k` passages of a notebook.

    `document_ids` narrows the search (the ticked sources); `None` searches the whole notebook and
    an empty list returns nothing. The narrowing is applied inside each leg, so a small scope is
    never starved by the rest.
    """
    if not query.strip() or (document_ids is not None and not document_ids):
        return []
    if getattr(db, "dialect", "sqlite") == "postgres":
        from wasifyai_notebooks.pgretrieval import retrieve_pg

        return retrieve_pg(
            cast(Any, db), notebook_id, query, vector, weight=weight, top_k=top_k,
            document_ids=document_ids, mode=mode,
        )  # fmt: skip
    scope = json.dumps(list(dict.fromkeys(document_ids))) if document_ids is not None else None
    blob = sqlite_vec.serialize_float32(list(vector))

    keyword = _keyword_leg(db, notebook_id, query, scope) if mode != "dense" else {}
    near = _vector_leg(db, notebook_id, blob, scope) if mode != "lexical" else []
    candidates = set(keyword) | set(near)
    if not candidates:
        return []
    return _best(db, candidates, keyword, blob, weight, top_k, mode)


def _matching(
    db: sqlite3.Connection,
    notebook_id: str,
    match: str,
    scope: str | None,
    within: Sequence[int] | None = None,
) -> list[int]:
    """The notebook's chunks matching an FTS5 expression, best BM25 first."""
    sql = (
        "SELECT c.id FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE chunks_fts MATCH ? AND d.notebook_id = ? "
    )
    args: list[object] = [match, notebook_id]
    if scope is not None:
        sql += "AND c.document_id IN (SELECT value FROM json_each(?)) "
        args.append(scope)
    if within is not None:
        sql += "AND c.id IN (SELECT value FROM json_each(?)) "
        args.append(json.dumps(list(within)))
    sql += "ORDER BY bm25(chunks_fts) LIMIT ?"
    args.append(CANDIDATES)
    return [row[0] for row in db.execute(sql, args)]


def _keyword_leg(
    db: sqlite3.Connection, notebook_id: str, query: str, scope: str | None
) -> dict[int, float]:
    distinct = terms(query)
    if not distinct:
        return {}
    # Quote each term against FTS5's grammar; OR keeps recall wide.
    candidates = _matching(db, notebook_id, " OR ".join(f'"{t}"' for t in distinct), scope)
    if not candidates:
        return {}
    # How much of the question a chunk answers lexically, which BM25 cannot say: its scores only
    # rank one query's candidates against each other.
    covered = dict.fromkeys(candidates, 0)
    for term in distinct:
        for chunk_id in _matching(db, notebook_id, f'"{term}"', scope, within=candidates):
            covered[chunk_id] += 1
    return {chunk_id: n / len(distinct) for chunk_id, n in covered.items()}


def _vector_leg(
    db: sqlite3.Connection, notebook_id: str, blob: bytes, scope: str | None
) -> list[int]:
    # Filtered inside the KNN, in its own CTE as vec0 wants, so another notebook's chunks (or an
    # unticked source's) can never crowd these out.
    if scope is not None:
        within = "SELECT c.id FROM chunks c WHERE c.document_id IN (SELECT value FROM json_each(?))"
        args: list[object] = [blob, CANDIDATES, scope, notebook_id]
    else:
        within = (
            "SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id "
            "WHERE d.notebook_id = ?"
        )
        args = [blob, CANDIDATES, notebook_id, notebook_id]
    sql = (
        "WITH knn AS (SELECT rowid, distance FROM chunk_vectors "
        f"WHERE embedding MATCH ? AND k = ? AND rowid IN ({within})) "
        "SELECT c.id FROM knn JOIN chunks c ON c.id = knn.rowid "
        "JOIN documents d ON d.id = c.document_id WHERE d.notebook_id = ?"
    )
    return [row[0] for row in db.execute(sql, args)]


def _best(
    db: sqlite3.Connection,
    candidates: set[int],
    keyword: dict[int, float],
    blob: bytes,
    weight: float,
    top_k: int,
    mode: Mode,
) -> list[Hit]:
    """Every candidate is scored on its own cosine, because a leg returns only its nearest 20 and a
    chunk outside them is unmeasured, not unrelated."""
    rows = db.execute(
        "SELECT c.id, c.document_id, d.title, c.content, c.start_line, c.end_line, "
        "COALESCE(vec_distance_cosine(v.embedding, ?), 1.0) AS distance "  # NULL: no direction
        "FROM chunks c JOIN chunk_vectors v ON v.rowid = c.id "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE c.id IN (SELECT value FROM json_each(?))",
        (blob, json.dumps(sorted(candidates))),
    ).fetchall()

    return rank(rows, keyword, weight, top_k, mode)


def rank(
    rows: Sequence[Sequence[Any]],
    keyword: dict[int, float],
    weight: float,
    top_k: int,
    mode: Mode,
) -> list[Hit]:
    """Order candidates by the blend. A row is `(chunk id, document id, title, content, start line,
    end line, cosine distance)`; shared by every database."""

    def blended(row: Sequence[Any]) -> float:
        cosine = max(0.0, 1.0 - row[6])  # a passage pointing the other way is no evidence
        if mode == "dense":
            return cosine
        lexical = keyword.get(row[0], 0.0)
        if mode == "lexical":
            return lexical
        return weight * cosine + (1.0 - weight) * lexical

    ordered = sorted(rows, key=lambda r: (-blended(r), r[6]))
    return [
        Hit(r[0], r[1], r[2], r[3], r[4], r[5], 1.0 - r[6], blended(r)) for r in ordered[:top_k]
    ]
