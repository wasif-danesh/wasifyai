# SPDX-License-Identifier: Apache-2.0
"""A transcript as a file: plain text, SubRip (.srt) or WebVTT (.vtt)."""

from typing import Any

FORMATS = {
    "txt": ("text/plain; charset=utf-8", "txt"),
    "srt": ("application/x-subrip; charset=utf-8", "srt"),
    "vtt": ("text/vtt; charset=utf-8", "vtt"),
}


def _stamp(seconds: float, comma: bool) -> str:
    ms = round(max(0.0, seconds) * 1000)
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{',' if comma else '.'}{ms:03d}"


def render(transcript: dict[str, Any], fmt: str) -> str:
    segments = transcript.get("segments") or []
    if fmt == "txt" or not segments:
        return str(transcript["text"]).strip() + "\n"
    if fmt == "srt":
        return "\n".join(
            f"{i}\n{_stamp(s['start'], True)} --> {_stamp(s['end'], True)}\n{s['text']}\n"
            for i, s in enumerate(segments, 1)
        )
    if fmt == "vtt":
        body = "\n".join(
            f"{_stamp(s['start'], False)} --> {_stamp(s['end'], False)}\n{s['text']}\n"
            for s in segments
        )
        return "WEBVTT\n\n" + body
    raise ValueError(fmt)


def file_name(title: str, ext: str) -> str:
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in title).strip(" ._")[:80]
    return f"{safe or 'transcript'}.{ext}"
