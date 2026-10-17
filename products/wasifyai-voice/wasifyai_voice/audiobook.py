# SPDX-License-Identifier: Apache-2.0
"""The parts of an audiobook that are not a model (ADR-0066, stage V7): finding the chapters of a
long text, cutting a chapter into pieces a speaking model takes well, and joining the spoken pieces
into one recording with short pauses.

A book is made chapter by chapter, and each chapter is kept as its own track as soon as it is done,
so a failure or a cancel in chapter 7 leaves chapters 1 to 6 where they are."""

import io
import re
import wave
from dataclasses import dataclass

MAX_BOOK_CHARS = 400_000
MAX_CHAPTERS = 200
MAX_CHAPTER_CHARS = 60_000
TARGET_CHAPTER_CHARS = 6_000  # a chapter made by size, when the text has no headings
CHUNK_CHARS = 700  # what a speaking model is given at a time
PARAGRAPH_PAUSE_S = 0.7
CHUNK_PAUSE_S = 0.25
CHAPTER_PAUSE_S = 1.5
SPOKEN_CHARS_PER_SECOND = 13.0  # for an estimate before anything is spoken


class BookError(Exception):
    """`str(e)` is a sentence safe to show; `code` is stable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Chapter:
    title: str
    text: str

    def public(self) -> dict[str, object]:
        return {
            "title": self.title, "text": self.text, "chars": len(self.text),
            "estimated_seconds": round(len(self.text) / SPOKEN_CHARS_PER_SECOND),
        }  # fmt: skip


_NUMBER_WORDS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty"
)
# a line that opens a chapter: "Chapter 3", "CHAPTER THREE: The Storm", "# Title", "Part II",
# "1. Beginning"
_HEADING = re.compile(
    rf"^\s*(?:#{{1,3}}\s+(?P<md>.+?)"
    rf"|(?P<word>(?:chapter|part|book|prologue|epilogue|preface|introduction)"
    rf"(?:\s+(?:\d+|[ivxlc]+|(?:{_NUMBER_WORDS})))?\b[\s:.\-—]*.*)"
    rf"|(?P<num>\d{{1,3}}\.\s+\S.{{0,80}}))\s*$",
    re.I,
)  # fmt: skip


def clean_text(text: str) -> str:
    """The text with its line ends and runs of blank lines made the same, nothing else changed."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _title_of(line: str) -> str:
    return re.sub(r"^\s*#{1,3}\s+", "", line).strip()[:120]


def _by_size(text: str, target: int) -> list[Chapter]:
    """Chapters of about `target` characters, cut between paragraphs."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    out: list[list[str]] = [[]]
    size = 0
    for p in paragraphs:
        if size and size + len(p) > target:
            out.append([])
            size = 0
        out[-1].append(p)
        size += len(p) + 2
    return [Chapter(f"Part {i}", "\n\n".join(group)) for i, group in enumerate(out, 1) if group]


def plan_chapters(text: str, target: int = TARGET_CHAPTER_CHARS) -> list[Chapter]:
    """The chapters of a text: at its headings when it has them, else by size. A heading line is the
    chapter's title and is not spoken as part of it (the title is spoken first, on its own)."""
    text = clean_text(text)
    if not text:
        raise BookError("text_required", "Paste or open the text of the book first.")
    if len(text) > MAX_BOOK_CHARS:
        raise BookError(
            "text_too_long",
            f"That text is longer than {MAX_BOOK_CHARS // 1000} thousand characters. Split it into "
            "two books.",
        )
    lines = text.split("\n")
    marks = [i for i, ln in enumerate(lines) if ln.strip() and _HEADING.match(ln) and len(ln) < 100]
    chapters: list[Chapter] = []
    if len(marks) >= 2 or (len(marks) == 1 and marks[0] == 0):
        if marks[0] > 0 and "\n".join(lines[: marks[0]]).strip():
            chapters.append(Chapter("Beginning", "\n".join(lines[: marks[0]]).strip()))
        for n, start in enumerate(marks):
            end = marks[n + 1] if n + 1 < len(marks) else len(lines)
            body = "\n".join(lines[start + 1 : end]).strip()
            if body:
                chapters.append(Chapter(_title_of(lines[start]), body))
    if not chapters:
        chapters = _by_size(text, target)
    if len(chapters) > MAX_CHAPTERS:
        raise BookError("too_many_chapters", f"A book has at most {MAX_CHAPTERS} chapters.")
    for c in chapters:
        if len(c.text) > MAX_CHAPTER_CHARS:
            chapters = _split_long(chapters)
            break
    if len(chapters) > MAX_CHAPTERS:
        raise BookError("too_many_chapters", f"A book has at most {MAX_CHAPTERS} chapters.")
    return chapters


def _split_long(chapters: list[Chapter]) -> list[Chapter]:
    out: list[Chapter] = []
    for c in chapters:
        if len(c.text) <= MAX_CHAPTER_CHARS:
            out.append(c)
            continue
        for i, part in enumerate(_by_size(c.text, MAX_CHAPTER_CHARS // 2), 1):
            out.append(Chapter(f"{c.title} ({i})", part.text))
    return out


def check_chapters(raw: list[dict[str, object]] | None) -> list[Chapter]:
    """The chapters a person sent, checked."""
    if not raw:
        raise BookError(
            "chapters_required", "There are no chapters to read. Find the chapters first."
        )
    if len(raw) > MAX_CHAPTERS:
        raise BookError("too_many_chapters", f"A book has at most {MAX_CHAPTERS} chapters.")
    out: list[Chapter] = []
    total = 0
    for i, item in enumerate(raw, 1):
        title = " ".join(str(item.get("title", "")).split())[:120] or f"Chapter {i}"
        text = clean_text(str(item.get("text", "")))
        if not text:
            raise BookError("empty_chapter", f"{title} has no words. Write some or take it out.")
        if len(text) > MAX_CHAPTER_CHARS:
            raise BookError("chapter_too_long", f"{title} is too long. Split it into two chapters.")
        total += len(text)
        out.append(Chapter(title, text))
    if total > MAX_BOOK_CHARS:
        raise BookError("text_too_long", "That is more text than one book can hold here.")
    return out


# ---- pieces ---------------------------------------------------------------------------------

_SENTENCE = re.compile(r"(?<=[.!?…。！？])[\"'”’)\]]*\s+|(?<=[。！？])")


@dataclass(frozen=True)
class Piece:
    text: str
    pause_s: float  # silence after it


def split_pieces(text: str, limit: int = CHUNK_CHARS) -> list[Piece]:
    """A chapter as pieces of at most `limit` characters, cut at sentence ends, with the pause that
    follows each: longer at the end of a paragraph, short between pieces of one paragraph."""
    pieces: list[Piece] = []
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        flat = " ".join(paragraph.split())
        sentences = [s.strip() for s in _SENTENCE.split(flat) if s and s.strip()]
        current = ""
        group: list[str] = []
        for s in sentences:
            while len(s) > limit:  # a sentence longer than a piece: cut at a space or comma
                cut = max(s.rfind(", ", 0, limit), s.rfind(" ", 0, limit))
                cut = cut if cut > limit // 3 else limit
                head, s = s[:cut].strip(), s[cut:].strip()
                if current:
                    group.append(current)
                    current = ""
                group.append(head)
            if current and len(current) + 1 + len(s) > limit:
                group.append(current)
                current = s
            else:
                current = f"{current} {s}".strip()
        if current:
            group.append(current)
        for i, g in enumerate(group):
            pieces.append(Piece(g, PARAGRAPH_PAUSE_S if i == len(group) - 1 else CHUNK_PAUSE_S))
    return pieces


# ---- joining --------------------------------------------------------------------------------


def _read(wav: bytes) -> tuple[tuple[int, int, int], bytes]:
    with wave.open(io.BytesIO(wav)) as w:
        return (w.getnchannels(), w.getsampwidth(), w.getframerate()), w.readframes(w.getnframes())


def join_wavs(parts: list[tuple[bytes, float]]) -> tuple[bytes, float]:
    """One WAV from spoken pieces, each followed by its pause in seconds: (the WAV, its length). The
    pieces must be the same format, which they are when one model spoke them."""
    if not parts:
        raise BookError("nothing_spoken", "Nothing was spoken.")
    fmt, _ = _read(parts[0][0])
    channels, width, rate = fmt
    if width != 2:
        raise BookError("unsupported_audio", "The speech was not 16-bit audio.")
    out = io.BytesIO()
    frames = 0
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        for wav, pause in parts:
            got, data = _read(wav)
            if got != fmt:
                raise BookError("mixed_audio", "The pieces of speech were not in the same format.")
            w.writeframes(data)
            silence = b"\x00" * (channels * width * round(max(0.0, pause) * rate))
            w.writeframes(silence)
            frames += len(data) // (channels * width) + len(silence) // (channels * width)
    return out.getvalue(), frames / rate
