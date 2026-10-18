# SPDX-License-Identifier: Apache-2.0
"""The two legs of `retrieval.retrieve` on Postgres.

Same contract and the same blend (`retrieval.rank`); what changes is how each leg finds its
candidates. Keyword: a passage's terms (cut by the tokenizer the SQLite index uses, so a question
and a passage agree on what a word is) are in an array column, and a passage matches when it holds
any term of the question; the candidates are the 20 holding the most of them (a shorter passage
first on a tie, which stands in for BM25's length weighting), and coverage, the fraction of the
question's terms a passage holds, is what scores. Semantic: pgvector cosine distance, an exact scan
of the notebook's (or the ticked sources') passages, so another notebook's passages can never crowd
these out.
"""

from collections.abc import Sequence

from wasifyai_platform_sdk.pg import PgDb, vector_text

from wasifyai_notebooks.retrieval import CANDIDATES, Hit, Mode, rank
from wasifyai_notebooks.tokenizer import terms


def retrieve_pg(
    db: PgDb,
    notebook_id: str,
    query: str,
    vector: Sequence[float],
    *,
    weight: float,
    top_k: int,
    document_ids: Sequence[str] | None,
    mode: Mode,
) -> list[Hit]:
    scope = list(dict.fromkeys(document_ids)) if document_ids is not None else None
    literal = vector_text(vector)
    keyword = _keyword_leg(db, notebook_id, query, scope) if mode != "dense" else {}
    near = _vector_leg(db, notebook_id, literal, scope) if mode != "lexical" else []
    candidates = set(keyword) | set(near)
    if not candidates:
        return []
    rows = db.execute(
        "SELECT c.id, c.document_id, d.title, c.content, c.start_line, c.end_line, "
        "COALESCE(c.embedding <=> CAST(? AS vector), 1.0) AS distance "  # NULL: no direction
        "FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE c.id = ANY(CAST(? AS bigint[]))",
        (literal, sorted(candidates)),
    ).fetchall()
    return rank(rows, keyword, weight, top_k, mode)


def _keyword_leg(
    db: PgDb, notebook_id: str, query: str, scope: list[str] | None
) -> dict[int, float]:
    distinct = terms(query)
    if not distinct:
        return {}
    sql = (
        "SELECT c.id, (SELECT COUNT(*) FROM unnest(CAST(? AS text[])) AS q(t) "
        "WHERE q.t = ANY(c.terms)) AS n "
        "FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE d.notebook_id = ? AND c.terms && CAST(? AS text[]) "
    )
    args: list[object] = [distinct, notebook_id, distinct]
    if scope is not None:
        sql += "AND c.document_id = ANY(CAST(? AS text[])) "
        args.append(scope)
    sql += "ORDER BY n DESC, cardinality(c.terms), c.id LIMIT ?"
    args.append(CANDIDATES)
    return {row[0]: row[1] / len(distinct) for row in db.execute(sql, args)}


def _vector_leg(db: PgDb, notebook_id: str, literal: str, scope: list[str] | None) -> list[int]:
    sql = (
        "SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE d.notebook_id = ? AND c.embedding IS NOT NULL "
    )
    args: list[object] = [notebook_id]
    if scope is not None:
        sql += "AND c.document_id = ANY(CAST(? AS text[])) "
        args.append(scope)
    sql += "ORDER BY c.embedding <=> CAST(? AS vector) LIMIT ?"
    args += [literal, CANDIDATES]
    return [row[0] for row in db.execute(sql, args)]
