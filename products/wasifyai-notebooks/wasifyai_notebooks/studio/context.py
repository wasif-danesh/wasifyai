# SPDX-License-Identifier: Apache-2.0
# The way a selection is cut to a budget (whole if it fits, an even share each, else the best
# passages) follows SurfSense's `worker/studio/shared/gather.py` (Apache-2.0, commit
# 622c1ded8), written for this store. See ../../PROVENANCE.md.
"""The text a Studio format is written from: the ticked sources, cut to the model's window."""

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise

from wasifyai_notebooks.retrieval import Hit, retrieve

# Below this even share a document says nothing, so the scope's best passages are taken instead
# (about one 480-token passage and a little).
MIN_SHARE_CHARS = 1_500
DEFAULT_QUERY = "the main points, findings, figures and conclusions"
GAP = "\n\n[...]\n\n"
RESERVE_TOKENS = 2_500  # the system prompt and the reply
CHARS_PER_TOKEN = 3


def budget_chars(context_tokens: int) -> int:
    """What of a window goes to the sources: the rest of it after the prompt and the reply."""
    return max(4_000, (context_tokens - RESERVE_TOKENS) * CHARS_PER_TOKEN)


@dataclass(frozen=True)
class Source:
    document_id: str
    title: str
    content: str


Embed = Callable[[str], Sequence[float]]


def grounding(sources: Sequence[Source]) -> str:
    """One block per source, as the model reads it."""
    if not sources:
        return "No sources were provided."
    return "\n\n".join(f"# {s.title}\n\n{s.content}" for s in sources)


def gather(
    db: sqlite3.Connection,
    notebook_id: str,
    document_ids: Sequence[str],
    *,
    budget: int,
    query: str | None = None,
    embed: Embed | None = None,
    weight: float = 0.65,
) -> list[Source]:
    """The sources' text within `budget` characters.

    A selection that fits is sent whole. One that does not gives each source an even share, taken as
    its start or, with a `query`, as its best matching passages; when the share would fall below
    `MIN_SHARE_CHARS` the selection's best passages for the query are taken instead, and only
    sources that hold one are returned.
    """
    wanted = list(dict.fromkeys(document_ids))
    if not wanted:
        return []
    rows = {
        r[0]: (r[1], r[2] or "")
        for r in db.execute(
            "SELECT id, title, content FROM documents WHERE notebook_id = ? "
            f"AND status = 'ready' AND id IN ({','.join('?' * len(wanted))})",
            (notebook_id, *wanted),
        )
    }
    ids = [i for i in dict.fromkeys(document_ids) if i in rows and rows[i][1].strip()]
    if not ids:
        return []
    total = sum(len(rows[i][1]) for i in ids)
    if total <= budget:
        return [Source(i, rows[i][0], rows[i][1]) for i in ids]

    steer = query.strip() if query and query.strip() else None
    search_for = steer or DEFAULT_QUERY

    def vector(text: str) -> Sequence[float] | None:
        return embed(text) if embed is not None else None

    if budget // len(ids) < MIN_SHARE_CHARS:
        vec = vector(search_for)
        if vec is None:
            return _starts(rows, ids, budget)
        hits = retrieve(
            db, notebook_id, search_for, vec, weight=weight,
            top_k=max(1, budget // MIN_SHARE_CHARS), document_ids=ids,
        )  # fmt: skip
        return _from_hits(rows, ids, hits, budget)

    shares = _shares([len(rows[i][1]) for i in ids], budget)
    out: list[Source] = []
    vec = vector(steer) if steer else None
    for i, share in zip(ids, shares, strict=True):
        title, content = rows[i]
        if len(content) <= share:
            out.append(Source(i, title, content))
            continue
        text = content[:share]
        if vec is not None and steer:
            hits = retrieve(
                db, notebook_id, steer, vec, weight=weight,
                top_k=max(1, share // MIN_SHARE_CHARS + 1), document_ids=[i],
            )  # fmt: skip
            picked = _fit(hits, share)
            if picked:
                text = _joined(picked)
        out.append(Source(i, title, text))
    return out


def _shares(lengths: list[int], budget: int) -> list[int]:
    """The budget split evenly, a short document's unused part going to the rest."""
    shares = [0] * len(lengths)
    remaining, left = budget, len(lengths)
    for index in sorted(range(len(lengths)), key=lengths.__getitem__):
        shares[index] = min(lengths[index], remaining // left)
        remaining -= shares[index]
        left -= 1
    return shares


def _starts(rows: dict[str, tuple[str, str]], ids: list[str], budget: int) -> list[Source]:
    shares = _shares([len(rows[i][1]) for i in ids], budget)
    return [Source(i, rows[i][0], rows[i][1][:s]) for i, s in zip(ids, shares, strict=True)]


def _fit(hits: Sequence[Hit], share: int) -> list[Hit]:
    chosen: list[Hit] = []
    used = 0
    for h in hits:
        cost = len(h.content) + (len(GAP) if chosen else 0)
        if used + cost > share:
            continue
        chosen.append(h)
        used += cost
    return sorted(chosen, key=lambda h: h.chunk_id)  # reading order within a source


def _joined(chosen: Sequence[Hit]) -> str:
    text = chosen[0].content
    for before, hit in pairwise(chosen):
        text += ("\n\n" if hit.chunk_id == before.chunk_id + 1 else GAP) + hit.content
    return text


def _from_hits(
    rows: dict[str, tuple[str, str]], ids: list[str], hits: Sequence[Hit], budget: int
) -> list[Source]:
    by_doc: dict[str, list[Hit]] = {}
    used = 0
    for h in hits:
        cost = len(h.content) + len(GAP)
        if used + cost > budget:
            continue
        by_doc.setdefault(h.document_id, []).append(h)
        used += cost
    out = []
    for i in ids:
        chosen = sorted(by_doc.get(i, []), key=lambda h: h.chunk_id)
        if chosen:
            out.append(Source(i, rows[i][0], _joined(chosen)))
    return out
