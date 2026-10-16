# SPDX-License-Identifier: Apache-2.0
# The excerpt block, the label resolution and the history budget follow SurfSense (Apache-2.0),
# surfsense_local/backend/modules/chat/{prompt,budget}.py, commit 622c1ded8. The two label rules
# (refusals carry none, a label needs words in common with its passage) are new, from the E0
# measurements. See ../PROVENANCE.md.
"""What a notebook answer is made from, and what is checked after the model has written it.

Retrieval happens before the model is asked (ADR-0065 decision 10): the passages go into the
user message, numbered `[n]` and grouped under their document, with the question labelled; the
model cites. Afterwards labels that point nowhere are dropped, and labels that cannot be
true (on a sentence that says the sources do not hold the answer, or on words the passage does
not contain) are removed, because small models put them there (E0: 2 of 5 refusals).
"""

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from wasifyai_notebooks.retrieval import Hit

Tier = Literal["compact", "capable"]
PROMPTS = Path(__file__).with_name("prompts")

_HEADER = (
    "These are excerpts from the user's notebook, selected for this question.\n"
    "A document is a full source; each <document> below is in excerpt view, so you are seeing "
    "only the passages that matched this question, not the whole source. Cite a passage with "
    "its [n]."
)

# A passage that contains these could otherwise close a source early and forge its own.
_TAGS = re.compile(r"</?(?:source|context|document|retrieved_context)\b[^>]*>", re.IGNORECASE)
_CODE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")
_LABEL = re.compile(r"\[(?:citation:\s*)?(\d+)\s*\]")
_PLACEHOLDER = re.compile(r"[ \t]?\[\s*n\s*\]", re.IGNORECASE)


@dataclass(frozen=True)
class Citation:
    """A passage the model may cite, with its text as it was when the answer was written."""

    n: int
    chunk_id: int
    document_id: str
    title: str
    start_line: int | None
    end_line: int | None
    text: str

    def public(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "title": self.title,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "text": self.text,
        }


@dataclass(frozen=True)
class Grounding:
    instruction: str  # the system message
    excerpts: str | None  # goes before the question in the user message
    citations: list[Citation]


def load_prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text().strip()


def build_context(hits: Sequence[Hit], tier: Tier) -> Grounding:
    """Number the hits 1..N in rank order and group them under their documents."""
    if not hits:
        return Grounding(load_prompt("no_sources"), None, [])
    citations = [
        Citation(i, h.chunk_id, h.document_id, h.title, h.start_line, h.end_line, h.content)
        for i, h in enumerate(hits, start=1)
    ]
    grouped: dict[str, list[Citation]] = defaultdict(list)
    order: list[str] = []
    for c in citations:
        if c.document_id not in grouped:
            order.append(c.document_id)
        grouped[c.document_id].append(c)
    blocks = []
    for document_id in order:
        group = grouped[document_id]
        lines = [f'<document title="{_attr(group[0].title)}" view="excerpt">']
        for c in group:
            body = _TAGS.sub("", c.text).strip().replace("\n", "\n" + " " * 6)
            lines.append(f"  [{c.n}] {body}")
        lines.append("</document>")
        blocks.append("\n".join(lines))
    excerpts = f"<retrieved_context>\n{_HEADER}\n" + "\n".join(blocks) + "\n</retrieved_context>"
    return Grounding(load_prompt(tier), excerpts, citations)


def user_message(grounding: Grounding, question: str) -> str:
    """The excerpts ride with the question: a local server reuses a prompt only up to its first
    changed token and what is retrieved changes with every question, so they go after the history.
    The question is labelled; unlabelled after the passages a 1.7B model answered about the last
    passage's subject (SurfSense measured it)."""
    if grounding.excerpts is None:
        return question
    return f"{grounding.excerpts}\n\nQuestion: {question}"


def _attr(value: str) -> str:
    collapsed = " ".join(str(value).split())
    return (
        collapsed.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---- after the model has written ---------------------------------------------------------------


def _outside_code(text: str, transform) -> str:
    parts: list[str] = []
    last = 0
    for region in _CODE.finditer(text):
        parts.append(transform(text[last : region.start()]))
        parts.append(region.group(0))
        last = region.end()
    parts.append(transform(text[last:]))
    return "".join(parts)


_REFUSAL = re.compile(
    r"(?:\b(?:sources?|documents?|notebook|context|excerpts?|passages?|material)\b"
    r"[^.!?\n]{0,40}\b(?:don't|do not|doesn't|does not|did not|didn't|not\s+(?:cover|mention|"
    r"contain|include|provide|specify|say|state|hold|give|list|address))"
    r"|\bnot\s+(?:mentioned|covered|included|specified|stated|provided|available|found|listed)\b"
    r"[^.!?\n]{0,40}\b(?:sources?|documents?|notebook|context|excerpts?|passages?)\b"
    r"|\bgeneral knowledge\b|\bno (?:information|mention) (?:about|of|on|in)\b"
    r"|\b(?:none|neither) of the (?:sources?|documents?|excerpts?|passages?)\b"
    r"|\bno (?:sources?|documents?|excerpts?|passages?)\b"
    r"|\bcannot be answered\b)",
    re.IGNORECASE,
)

_STOP = frozenset(
    "this that with from have been were what which their there about would could should "
    "where when into also than then them they your yours does doing done much many more most "
    "some such only over after before between because while these those other each every".split()
)
_WORD = re.compile(r"[^\W_]{4,}|\d{2,}", re.UNICODE)


def _sentences(text: str) -> list[str]:
    """Pieces that join back to `text`: a sentence with its trailing labels, or a line."""
    pieces = re.split(r"(?<=[.!?])(?=\s)|(?<=\n)", text)
    out: list[str] = []
    for piece in pieces:
        if out and re.match(r"\s*(?:\[\d+\])", piece):
            # labels placed after the full stop belong to the sentence before
            m = re.match(r"\s*(?:\[\d+\])+", piece)
            assert m is not None
            out[-1] += m.group(0)
            rest = piece[m.end() :]
            if rest:
                out.append(rest)
        elif piece:
            out.append(piece)
    return out


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if w.lower() not in _STOP}


@dataclass(frozen=True)
class Checked:
    text: str
    removed: int  # labels taken off sentences the sources cannot support


def check_labels(answer: str, citations: Sequence[Citation]) -> Checked:
    """Take labels off a sentence that says the sources do not hold the answer, and off one that
    shares no word with the passages it cites. Labels that point at no passage are dropped."""
    by_n = {c.n: c for c in citations}
    removed = 0

    def per_span(span: str) -> str:
        nonlocal removed
        out = []
        for sentence in _sentences(span):
            labels = [int(n) for n in _LABEL.findall(sentence)]
            if not labels:
                out.append(sentence)
                continue
            body = _LABEL.sub("", sentence)
            drop = bool(_REFUSAL.search(body))
            if not drop:
                known = [n for n in labels if n in by_n]
                words = _words(body)
                if known and words:
                    evidence = " ".join(by_n[n].text for n in known).lower()
                    drop = not any(w in evidence for w in words)
            if drop:
                removed += len(labels)
                sentence = re.sub(r"\s*(?:\[(?:citation:\s*)?\d+\s*\])+", "", sentence)
            out.append(sentence)
        return "".join(out)

    return Checked(_outside_code(answer, per_span), removed)


def resolve_citations(answer: str, citations: Sequence[Citation]) -> tuple[str, list[Citation]]:
    """Which passages the answer cites, in the order cited; numbers that are not passages are
    removed from the text. Citation-shaped text inside code stays literal."""
    by_n = {c.n: c for c in citations}
    order: list[int] = []

    def collect(span: str) -> str:
        for m in _LABEL.finditer(span):
            n = int(m.group(1))
            if n in by_n and n not in order:
                order.append(n)
        return span

    _outside_code(answer, collect)

    def rewrite(span: str) -> str:
        # `[n]` is the prompt's own example, which a small model sometimes copies as a label (E2)
        span = _PLACEHOLDER.sub("", span)
        return _LABEL.sub(lambda m: f"[{int(m.group(1))}]" if int(m.group(1)) in by_n else "", span)

    return _outside_code(answer, rewrite), [by_n[n] for n in order]


# ---- the window ----------------------------------------------------------------------------------

ANSWER_RESERVE = 1024  # claimed first: llama.cpp stops a reply wherever the window runs out
SYSTEM_PRICE = 450  # the longest prompt
EXCERPT_PRICE = 5 * 480
QUESTION_MAX_CHARS = 4000
SMALL_MODEL_BYTES = 1_500_000_000  # under this a model is given the `compact` prompt


def price(text: str) -> int:
    """Tokens, estimated at four characters each, plus the message's own overhead."""
    return len(text) // 4 + 4


def history_budget(context: int, question: str) -> int:
    return max(0, context - ANSWER_RESERVE - SYSTEM_PRICE - EXCERPT_PRICE - price(question))


def fit_history(turns: Sequence[tuple[str, str]], budget: int) -> list[tuple[str, str]]:
    """The newest whole exchanges (user then assistant) that fit `budget`. Earlier turns reach the
    model as text only, without their passages."""
    chosen: list[tuple[str, str]] = []
    spent = 0
    i = len(turns)
    while i > 0:
        j = i - 1
        while j > 0 and turns[j][0] != "user":
            j -= 1
        block = list(turns[j:i])
        cost = sum(price(t) for _, t in block)
        if spent + cost > budget:
            break
        chosen = block + chosen
        spent += cost
        i = j
    return chosen


def tier_for(model_bytes: int | None) -> Tier:
    """The shorter prompt for the smallest local models, the fuller one otherwise."""
    return "compact" if model_bytes is not None and model_bytes < SMALL_MODEL_BYTES else "capable"
