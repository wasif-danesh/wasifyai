# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""The Story skill (ADR-0090, stage CS5): pure functions. A story is the person's own text, read by a narrator. Words in
quotes are said by the person of the cast named in the same sentence, in their saved voice; everything else is narrated.
Each part is spoken on its own and the parts are joined with a pause after each, so the times of every line are known
exactly. From then on a story is like a song: the narration is the sound, its lines are the captions and the cuts fall
where the lines start."""

import re
from typing import Any

PAUSE_IN_SENTENCE = 0.2  # between a quote and the words around it
PAUSE_SENTENCE = 0.45
PAUSE_PARAGRAPH = 0.9
PAUSE_END = 1.0
MAX_PART = 600  # characters a part is spoken in; a longer sentence is split at a comma or a space
SENTENCE = re.compile(r"(?<=[.!?…。！？।])[\"'”’)]*\s+")
QUOTE = re.compile(r"[\"“„«]([^\"”“«»]+)[\"”»]")


def _named(person: dict[str, Any], text: str) -> bool:
    return re.search(rf"\b{re.escape(person['name'])}\b", text, re.IGNORECASE) is not None


def _short(text: str) -> list[str]:
    """A part short enough to speak, split at commas, then spaces."""
    out: list[str] = []
    rest = text.strip()
    while len(rest) > MAX_PART:
        cut = rest.rfind(", ", 0, MAX_PART)
        cut = cut + 1 if cut > MAX_PART // 3 else rest.rfind(" ", 0, MAX_PART)
        cut = cut if cut > 0 else MAX_PART
        out.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    return [*out, rest] if rest else out


def sentences(paragraph: str) -> list[str]:
    """A paragraph's sentences, each with its closing quote."""
    found: list[str] = []
    at = 0
    for m in SENTENCE.finditer(paragraph):
        found.append(paragraph[at : m.end()].strip())
        at = m.end()
    found.append(paragraph[at:].strip())
    return [s for s in found if s]


def _spoken(text: str) -> bool:
    """A piece with something to say, not only commas and quote marks."""
    return re.search(r"\w", text) is not None


def parts_of(text: str, cast: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The story as the parts to speak, in order: `text`, `who` (a cast name, or None for the narrator) and the pause after."""
    out: list[dict[str, Any]] = []
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    for n, paragraph in enumerate(paragraphs):
        said = sentences(" ".join(paragraph.split()))
        for k, sentence in enumerate(said):
            outside = QUOTE.sub(" ", sentence)
            speaker = next(
                (p["name"] for p in cast if not p.get("photos_only") and _named(p, outside)), None
            )
            pieces: list[tuple[str, str | None]] = []
            at = 0
            for m in QUOTE.finditer(sentence):
                pieces.append((sentence[at : m.start()], None))
                pieces.append((m.group(1), speaker))
                at = m.end()
            pieces.append((sentence[at:], None))
            merged: list[tuple[str, str | None]] = []
            for words, who in pieces:
                words = words.strip(" ,;:—–-")
                if not _spoken(words):
                    continue
                if merged and merged[-1][1] == who:
                    merged[-1] = (f"{merged[-1][0]} {words}", who)
                else:
                    merged.append((words, who))
            for j, (words, who) in enumerate(merged):
                chunks = _short(words)
                for c, chunk in enumerate(chunks):
                    last_chunk = c == len(chunks) - 1
                    if not last_chunk or j < len(merged) - 1:
                        pause = PAUSE_IN_SENTENCE
                    elif k < len(said) - 1:
                        pause = PAUSE_SENTENCE
                    elif n < len(paragraphs) - 1:
                        pause = PAUSE_PARAGRAPH
                    else:
                        pause = PAUSE_END
                    out.append({"text": chunk, "who": who, "pause": pause, "paragraph": n})
    return out


def facts_of(
    parts: list[dict[str, Any]], times: list[list[float]], seconds: float
) -> dict[str, Any]:
    """What a song's analysis would say, for a narration: its lines with exact times, a section a paragraph, and the
    line starts as the places a cut may fall."""
    lines = [
        {"text": p["text"], "start": t[0], "end": t[1], "who": p["who"]}
        for p, t in zip(parts, times, strict=True)
    ]
    sections: list[dict[str, Any]] = []
    for p, t in zip(parts, times, strict=True):
        if sections and sections[-1]["paragraph"] == p["paragraph"]:
            sections[-1]["end"] = t[1]
        else:
            sections.append(
                {
                    "start": t[0],
                    "end": t[1],
                    "energy": 0.5,
                    "label": "mid",
                    "paragraph": p["paragraph"],
                }
            )
    for a, b in zip(sections, sections[1:], strict=False):
        a["end"] = b["start"]
    if sections:
        sections[0]["start"] = 0.0
        sections[-1]["end"] = seconds
    starts = sorted({round(t[0], 3) for t in times if t[0] > 0})
    return {
        "seconds": seconds, "bpm": 0, "beats": starts, "downbeats": [],
        "sections": [{k: v for k, v in s.items() if k != "paragraph"} for s in sections],
        "lines": lines, "lines_timed": True, "story": True,
    }  # fmt: skip


def speaker_at(lines: list[dict[str, Any]], start: float, end: float) -> str | None:
    """Who of the cast speaks during this shot, for the longest time, if anyone does."""
    best, most = None, 0.0
    for row in lines:
        if row.get("who") and row.get("start") is not None:
            overlap = min(end, row["end"]) - max(start, row["start"])
            if overlap > most:
                best, most = row["who"], overlap
    return best if most >= 0.5 else None
