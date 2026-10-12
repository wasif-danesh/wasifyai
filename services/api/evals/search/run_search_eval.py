"""Measure semantic search before building it (ADR-0041).

Embeds a synthetic multilingual library and queries with each candidate embedder through LiteLLM
(the same path the product uses). Reports recall, the no-match floor and speed for vectors alone,
Postgres full-text, and the two merged by rank. Then it measures the chosen design: exact-word
matches first, then vector neighbours above a similarity floor. Nothing here touches user data:
the full-text part uses a TEMP table that disappears with the connection.

    uv run python services/api/evals/search/run_search_eval.py [--json results.json]

Needs the stack running (make dev) with both embedders pulled (nomic-embed-text and bge-m3)."""

import argparse
import asyncio
import json
import math
import os
import statistics
import time
from pathlib import Path

import httpx
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

HERE = Path(__file__).parent
ROOT = HERE.parents[3]
TOP = 5
RRF_K = 60
POOL = 20
FLOOR = 0.57  # similarity floor for bge-m3: just above the best no-match query (see ADR-0041)
CHOSEN = "creation-embedder"
# alias -> (document prefix, query prefix). nomic-embed-text needs these task prefixes.
MODELS = {"embedder": ("search_document: ", "search_query: "), CHOSEN: ("", "")}

Ranked = list[tuple[int, float]]


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())
    return env


async def embed(http: httpx.AsyncClient, key: str, alias: str, texts: list[str]):
    out: list[list[float]] = []
    for i in range(0, len(texts), 16):
        r = await http.post(
            "http://localhost:4000/v1/embeddings",
            headers={"authorization": f"Bearer {key}"},
            json={"model": alias, "input": texts[i : i + 16]},
        )
        r.raise_for_status()
        out += [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
    return out


def cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def by_vector(q: list[float], docs: list[list[float]]) -> Ranked:
    return sorted(((i, cos(q, d)) for i, d in enumerate(docs)), key=lambda t: -t[1])


def keyword_hits(items: list[dict], query: str) -> list[int]:
    """The keyword half of the design: every word of the query appears in the text, ignoring case,
    with no word-splitting of the text, so it works in any script (Chinese and Japanese have no
    spaces)."""
    words = [w for w in query.lower().split() if w]
    return [
        n for n, it in enumerate(items) if words and all(w in it["text"].lower() for w in words)
    ]


def design(ranked: Ranked, keyword: list[int], floor: float) -> list[int]:
    """What the search returns: exact-word matches first, then vector neighbours above the floor."""
    out = list(keyword)
    return out + [i for i, sim in ranked if sim >= floor and i not in out]


async def fulltext(conn: AsyncConnection, query: str, mode: str) -> list[int]:
    """Postgres full-text, `simple` configuration: any word (`or`) or every word (`and`)."""
    words = [w for w in query.lower().replace("!", " ").split() if len(w) >= 2]
    if not words:
        return []
    q = " | ".join(words) if mode == "or" else " & ".join(words)
    rows = await conn.execute(
        text(
            "SELECT idx FROM docs WHERE tsv @@ to_tsquery('simple', :q) "
            "ORDER BY ts_rank(tsv, to_tsquery('simple', :q)) DESC LIMIT :n"
        ),
        {"q": q, "n": POOL},
    )
    return [r[0] for r in rows]


def fuse(*lists: list[int]) -> list[int]:
    score: dict[int, float] = {}
    for lst in lists:
        for rank, idx in enumerate(lst):
            score[idx] = score.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)
    return [i for i, _ in sorted(score.items(), key=lambda t: -t[1])]


def metrics(ranked: list[int], relevant: set[int]) -> tuple[float, float, float]:
    top = ranked[:TOP]
    hit = 1.0 if any(i in relevant for i in top) else 0.0
    rr = next((1.0 / (n + 1) for n, i in enumerate(ranked) if i in relevant), 0.0)
    return hit, len(relevant & set(top)) / len(relevant), rr


def summarise(rows: list[tuple[float, float, float]]) -> dict[str, float]:
    return {
        "hit@5": round(statistics.mean(r[0] for r in rows), 3),
        "recall@5": round(statistics.mean(r[1] for r in rows), 3),
        "mrr": round(statistics.mean(r[2] for r in rows), 3),
    }


def per_language(queries: list[dict], rows: list) -> dict[str, float]:
    groups: dict[str, list] = {}
    for q, row in zip(queries, rows, strict=True):
        groups.setdefault(q["lang"], []).append(row)
    return {k: summarise(v)["hit@5"] for k, v in sorted(groups.items())}


async def main() -> dict:
    env = load_env()
    key = env["LITELLM_API_KEY"]
    data = yaml.safe_load((HERE / "corpus.yaml").read_text())
    items = [dict(i, concept=c["id"]) for c in data["concepts"] for i in c["items"]]
    queries = [dict(q, concept=c["id"]) for c in data["concepts"] for q in c["queries"]]
    nomatch, exact = data["nomatch"], data["exact"]
    ids = {c["id"] for c in data["concepts"]}
    relevant = {c: {n for n, i in enumerate(items) if i["concept"] == c} for c in ids}
    item_langs = {c: {i["lang"] for i in items if i["concept"] == c} for c in ids}
    report: dict = {"items": len(items), "queries": len(queries), "nomatch": len(nomatch)}

    engine = create_async_engine(
        "postgresql+asyncpg://wasifyai:"
        f"{env.get('POSTGRES_PASSWORD', 'wasifyai')}@localhost:5432/wasifyai"
    )
    async with httpx.AsyncClient(timeout=120) as http, engine.connect() as conn:
        await conn.execute(text("CREATE TEMP TABLE docs (idx int, tsv tsvector)"))
        for n, it in enumerate(items):
            await conn.execute(
                text("INSERT INTO docs VALUES (:i, to_tsvector('simple', :b))"),
                {"i": n, "b": it["text"]},
            )
        fts_or = [await fulltext(conn, q["text"], "or") for q in queries]
        fts_rows = [
            metrics(f, relevant[q["concept"]]) for f, q in zip(fts_or, queries, strict=True)
        ]
        report["fulltext_only"] = {
            **summarise(fts_rows),
            "hit@5_by_query_language": per_language(queries, fts_rows),
        }

        for alias, (dp, qp) in MODELS.items():
            t0 = time.perf_counter()
            docs = await embed(http, key, alias, [dp + i["text"] for i in items])
            doc_seconds = time.perf_counter() - t0
            qv = await embed(http, key, alias, [qp + q["text"] for q in queries])
            nv = await embed(http, key, alias, [qp + q["text"] for q in nomatch])
            single = []
            for q in queries[:8]:  # one query at a time: what a real search request costs
                t = time.perf_counter()
                await embed(http, key, alias, [qp + q["text"]])
                single.append(time.perf_counter() - t)

            ranked = [by_vector(v, docs) for v in qv]
            rows = [
                metrics([i for i, _ in r], relevant[q["concept"]])
                for r, q in zip(ranked, queries, strict=True)
            ]
            merged = [
                metrics(fuse([i for i, _ in r][:POOL], f), relevant[q["concept"]])
                for r, f, q in zip(ranked, fts_or, queries, strict=True)
            ]
            same = [
                x
                for x, q in zip(rows, queries, strict=True)
                if q["lang"] in item_langs[q["concept"]]
            ]
            cross = [
                x
                for x, q in zip(rows, queries, strict=True)
                if q["lang"] not in item_langs[q["concept"]]
            ]
            matched_top1 = [r[0][1] for r in ranked]
            nomatch_top1 = [by_vector(v, docs)[0][1] for v in nv]
            best_relevant = [
                max(cos(v, docs[i]) for i in relevant[q["concept"]])
                for v, q in zip(qv, queries, strict=True)
            ]
            floor = max(nomatch_top1) + 1e-6
            report[alias] = {
                "dims": len(docs[0]),
                "vector": summarise(rows),
                "vector_plus_fulltext_merged_by_rank": summarise(merged),
                "vector_same_language_queries": {"n": len(same), **summarise(same)},
                "vector_cross_language_queries": {"n": len(cross), **summarise(cross)},
                "vector_hit@5_by_query_language": per_language(queries, rows),
                "top1_similarity_matched": {
                    "min": round(min(matched_top1), 3),
                    "median": round(statistics.median(matched_top1), 3),
                },
                "top1_similarity_nomatch": {
                    "max": round(max(nomatch_top1), 3),
                    "median": round(statistics.median(nomatch_top1), 3),
                },
                "floor_for_zero_false_positives": round(floor, 3),
                "matched_queries_kept_by_that_floor": round(
                    sum(s > floor for s in best_relevant) / len(best_relevant), 3
                ),
                "seconds_to_embed_60_documents": round(doc_seconds, 2),
                "median_seconds_per_single_query": round(statistics.median(single), 3),
            }
            if alias == CHOSEN:
                report["final_design_bge_m3"] = await final_design(
                    conn, http, key, items, docs, queries, qv, ranked, nomatch, nv, exact, relevant
                )
        await conn.rollback()  # the temp table goes away with it
    await engine.dispose()
    return report


async def final_design(
    conn, http, key, items, docs, queries, qv, ranked, nomatch, nv, exact, relevant
):
    """The chosen design measured end to end: exact words first, then vectors above the floor."""
    sentence = [
        metrics(design(r, keyword_hits(items, q["text"]), FLOOR), relevant[q["concept"]])
        for r, q in zip(ranked, queries, strict=True)
    ]
    ev = await embed(http, key, CHOSEN, [e["text"] for e in exact])
    present = [(e, v) for e, v in zip(exact, ev, strict=True) if e["target"]]
    absent = [(e, v) for e, v in zip(exact, ev, strict=True) if not e["target"]]

    def targets(e):
        return {n for n, it in enumerate(items) if e["target"].lower() in it["text"].lower()}

    vec_first = above = fts_and = keyword = in_top5 = 0
    for e, v in present:
        r, want = by_vector(v, docs), targets(e)
        vec_first += r[0][0] in want
        above += r[0][1] >= FLOOR
        fts_and += set(await fulltext(conn, e["text"], "and")) == want
        kw = keyword_hits(items, e["text"])
        keyword += set(kw) == want
        in_top5 += bool(want & set(design(r, kw, FLOOR)[:TOP]))
    absent_false = sum(
        bool(design(by_vector(v, docs), keyword_hits(items, e["text"]), FLOOR)) for e, v in absent
    )
    nomatch_false = sum(
        bool(design(by_vector(v, docs), keyword_hits(items, q["text"]), FLOOR))
        for q, v in zip(nomatch, nv, strict=True)
    )
    n = len(present)
    return {
        "floor": FLOOR,
        "sentence_queries": {"n": len(queries), **summarise(sentence)},
        "exact_words": {
            "words_in_library": n,
            "vector_ranks_it_first": f"{vec_first}/{n}",
            "vector_top1_similarity_reaches_floor": f"{above}/{n}",
            "postgres_fulltext_finds_exactly_it": f"{fts_and}/{n}",
            "keyword_check_finds_exactly_it": f"{keyword}/{n}",
            "final_design_has_it_in_top5": f"{in_top5}/{n}",
            "absent_words_that_returned_something": f"{absent_false}/{len(absent)}",
        },
        "nomatch_sentence_queries_that_returned_something": f"{nomatch_false}/{len(nomatch)}",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    out = ap.parse_args().json
    result = json.dumps(asyncio.run(main()), indent=2, ensure_ascii=False)
    print(result)
    if out:
        Path(out).write_text(result)
