"""A transcript as plain text, SRT or WebVTT (ADR-0043). Pure functions over the stored segments."""

import unicodedata
from typing import Any
from urllib.parse import quote

Segment = dict[str, Any]  # {"start": seconds, "end": seconds, "text": str}


def _stamp(seconds: float, sep: str) -> str:
    ms = round(max(0.0, seconds) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{sep}{ms:03}"


def _lines(segments: list[Segment]) -> list[tuple[float, float, str]]:
    return [
        (float(s["start"]), float(s["end"]), " ".join(str(s["text"]).split()))
        for s in segments
        if str(s["text"]).strip()
    ]


def to_srt(segments: list[Segment]) -> str:
    out = []
    for n, (a, b, text) in enumerate(_lines(segments), 1):
        out.append(f"{n}\n{_stamp(a, ',')} --> {_stamp(b, ',')}\n{text}\n")
    return "\n".join(out)


def to_vtt(segments: list[Segment]) -> str:
    out = ["WEBVTT\n"]
    for a, b, text in _lines(segments):
        out.append(f"{_stamp(a, '.')} --> {_stamp(b, '.')}\n{text}\n")
    return "\n".join(out)


def to_text(text: str) -> str:
    return text.strip() + "\n"


def title_of(text: str, limit: int = 60) -> str:
    """The first words of the transcript: what it is called. The file's name is never kept."""
    words = " ".join(text.split())
    if len(words) <= limit:
        return words
    cut = words[:limit].rsplit(" ", 1)[0] or words[:limit]
    return cut.rstrip(" ,.;:-") + "…"


def file_name(title: str, ext: str) -> str:
    """A safe, readable file name: letters, marks and digits of any script, joined by hyphens."""
    kept = "".join(c if unicodedata.category(c)[0] in "LMN" else " " for c in title.lower())
    slug = "-".join(kept.split())[:48].strip("-")
    return f"{slug or 'transcript'}.{ext}"


def content_disposition(title: str, ext: str) -> str:
    """The header that makes a browser save the file: an ASCII name for old clients and the real
    name (UTF-8, percent-encoded) for the rest, so a Bengali title stays Bengali (RFC 6266)."""
    name = file_name(title, ext)
    stem = name.rsplit(".", 1)[0]
    plain = "".join(c for c in stem if c.isascii() and (c.isalnum() or c == "-")).strip("-")
    ascii_name = f"{plain or 'transcript'}.{ext}"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
