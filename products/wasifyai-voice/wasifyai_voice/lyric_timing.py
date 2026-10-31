# ruff: noqa: E501  (prose in the docstrings is easier to read on one line)
"""When each typed line of a song is sung. The words are always what the person typed; what was heard only
gives the times, because a speech model mishears singing (`docs/spikes/creative-cs0.md`). When too little of
what was heard matches, as for a language the model does not know, the lines have no times."""

import re
from difflib import SequenceMatcher
from typing import Any

MIN_MATCH = 0.25  # the share of typed words that must be heard before the times mean anything
MARK = re.compile(r"^\s*[\[(].*[\])]\s*$")  # [Verse], (chorus)
WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.UNICODE)


def lyric_lines(lyrics: str) -> list[str]:
    """The lines that are sung: no empty lines, no section marks."""
    return [s for line in lyrics.splitlines() if (s := line.strip()) and not MARK.match(s)]


def _words(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(text)]


def _heard_words(segments: list[dict[str, Any]]) -> list[tuple[str, float, float]]:
    """Each heard word with its time: spread evenly over its stretch, which is all the model gives."""
    out: list[tuple[str, float, float]] = []
    for s in segments:
        words = _words(str(s.get("text", "")))
        start, end = float(s.get("start", 0)), float(s.get("end", 0))
        step = (end - start) / len(words) if words else 0.0
        out += [(w, start + i * step, start + (i + 1) * step) for i, w in enumerate(words)]
    return out


def timed_lines(lyrics: str, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The typed lines with `start` and `end`, or an empty list when the times cannot be trusted. A line
    that was not heard takes its place between the lines around it."""
    lines = lyric_lines(lyrics)
    typed = [(i, w) for i, line in enumerate(lines) for w in _words(line)]
    heard = _heard_words(segments)
    if not typed or not heard:
        return []
    match = SequenceMatcher(None, [w for _, w in typed], [w for w, _, _ in heard], autojunk=False)
    hit: dict[int, list[tuple[float, float]]] = {}
    matched = 0
    for block in match.get_matching_blocks():
        for k in range(block.size):
            line = typed[block.a + k][0]
            _, start, end = heard[block.b + k]
            hit.setdefault(line, []).append((start, end))
            matched += 1
    if matched / len(typed) < MIN_MATCH:
        return []
    out: list[dict[str, Any]] = []
    for i, text in enumerate(lines):
        times = hit.get(i)
        out.append(
            {
                "text": text,
                "start": round(times[0][0], 2) if times else None,
                "end": round(times[-1][1], 2) if times else None,
            }
        )
    _fill_gaps(out, heard[-1][2])
    return out


def _fill_gaps(rows: list[dict[str, Any]], last: float) -> None:
    """Lines not heard share the time between the heard lines around them."""
    i = 0
    while i < len(rows):
        if rows[i]["start"] is not None:
            i += 1
            continue
        j = i
        while j < len(rows) and rows[j]["start"] is None:
            j += 1
        before = rows[i - 1]["end"] if i else 0.0
        after = rows[j]["start"] if j < len(rows) else last
        step = max(after - before, 0.0) / (j - i)
        for k in range(i, j):
            rows[k]["start"] = round(before + (k - i) * step, 2)
            rows[k]["end"] = round(before + (k - i + 1) * step, 2)
        i = j
