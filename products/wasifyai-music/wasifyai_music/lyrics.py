"""Lyrics handling: ACE-Step expects section tags on their own lines (`[verse]`, `[chorus]`,
`[bridge]`), and the UI wants the lyrics to appear as they are written."""

import json
import re

from pydantic import ValidationError

from wasifyai_music.schemas import SongDraft

_TAG_LINE = re.compile(r"^\s*\[\s*([A-Za-z][A-Za-z -]*?)\s*(?:\d+)?\s*\]\s*$")
_ALIASES = {
    "hook": "chorus",
    "refrain": "chorus",
    "prechorus": "pre-chorus",
    "pre chorus": "pre-chorus",
}
_SECTIONS = {
    "verse", "chorus", "bridge", "intro", "outro",
    "pre-chorus", "pre chorus", "prechorus", "hook", "refrain",
}  # fmt: skip
# A section tag followed by the first line on the same line: "[verse]The big moon hangs low".
# Models write this often. Only real section names are split, so "[laughs] hello" is left alone.
_INLINE_TAG = re.compile(r"^\s*\[\s*([A-Za-z][A-Za-z -]*?)\s*(?:\d+)?\s*\]\s*(\S.*)$")
MIN_LYRIC_LINES = 6
# Measured with the real model: a line takes about 4 seconds to sing, and 16 lines fill a
# 60-second song. Much beyond that is cut off, so it is refused rather than silently lost.
MAX_LYRIC_LINES = 20


class DraftInvalid(ValueError):
    """The model's answer cannot be used. `feedback` is told to the model on the next attempt."""

    def __init__(self, message: str, feedback: str):
        super().__init__(message)
        self.feedback = feedback


def _canonical(name: str) -> str:
    name = name.strip().lower()
    return _ALIASES.get(name, name)


def normalise_lyrics(text: str) -> str:
    """Canonical section tags (`[Verse 1]` becomes `[verse]`), tags on their own line, no code
    fences, tidy blank lines."""
    text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip())
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if (inline := _INLINE_TAG.match(raw)) and inline.group(1).strip().lower() in _SECTIONS:
            out.append(f"[{_canonical(inline.group(1))}]")
            raw = inline.group(2)
        line = raw.rstrip()
        if m := _TAG_LINE.match(line):
            line = f"[{_canonical(m.group(1))}]"
        out.append(line.strip() if line.startswith("[") else line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def lyric_problems(lyrics: str) -> list[str]:
    tags = [m.group(0).strip() for ln in lyrics.split("\n") if (m := _TAG_LINE.match(ln))]
    problems = []
    if "[verse]" not in tags:
        problems.append("include at least one [verse] section tag on its own line")
    if "[chorus]" not in tags:
        problems.append("include at least one [chorus] section tag on its own line")
    sung = [ln for ln in lyrics.split("\n") if ln.strip() and not _TAG_LINE.match(ln)]
    if len(sung) < MIN_LYRIC_LINES:
        problems.append(f"have at least {MIN_LYRIC_LINES} lines of lyrics")
    if len(sung) > MAX_LYRIC_LINES:
        problems.append(
            f"have at most {MAX_LYRIC_LINES} lines of lyrics (a 60-second song fits about 16)"
        )
    return problems


def merge_tags(*parts: str | None) -> str:
    """Combine comma-separated music tags, keeping the first spelling of each and dropping repeats
    (the request's genre and mood, then the model's style)."""
    seen: dict[str, str] = {}
    for part in parts:
        for tag in (part or "").split(","):
            tag = tag.strip()
            if tag:
                seen.setdefault(tag.lower(), tag)
    return ", ".join(seen.values())


def parse_draft(raw: str) -> SongDraft:
    """Parse and validate a `text.lyrics` reply, or raise DraftInvalid with feedback."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise DraftInvalid(
            "not JSON", "Your reply was not valid JSON. Reply with the JSON object only."
        ) from e
    try:
        draft = SongDraft.model_validate(data)
    except ValidationError as e:
        fields = sorted({str(err["loc"][0]) for err in e.errors() if err["loc"]})
        raise DraftInvalid(
            f"invalid fields {fields}", f"Fix these fields: {', '.join(fields)}."
        ) from e
    draft.lyrics = normalise_lyrics(draft.lyrics)
    if problems := lyric_problems(draft.lyrics):
        raise DraftInvalid("; ".join(problems), "The lyrics must " + " and ".join(problems) + ".")
    return draft


_ESCAPES = {"n": "\n", "t": "\t", "r": "", '"': '"', "\\": "\\", "/": "/", "b": "", "f": ""}


class LyricsStreamer:
    """Feed it the raw JSON stream of a SongDraft; it returns only the new characters of the
    `lyrics` value, decoded, so the UI can show lyrics appearing while JSON is being generated.
    Handles escapes split across chunks. Assumes a flat object of string values."""

    def __init__(self, field: str = "lyrics") -> None:
        self._field = field
        self._in_string = False
        self._escape = ""  # pending escape sequence ("\\" or "\\u12")
        self._buf = ""  # characters of the string being read
        self._expect_key = True
        self._key = ""
        self._emit = False

    def feed(self, chunk: str) -> str:
        out: list[str] = []
        for ch in chunk:
            if not self._in_string:
                if ch == '"':
                    self._in_string, self._buf = True, ""
                    self._emit = (not self._expect_key) and self._key == self._field
                elif ch == ":":
                    self._expect_key = False
                elif ch == ",":
                    self._expect_key = True
                continue
            if self._escape:
                self._escape += ch
                if self._escape.startswith("\\u"):
                    if len(self._escape) < 6:
                        continue
                    decoded = chr(int(self._escape[2:6], 16))
                else:
                    decoded = _ESCAPES.get(ch, ch)
                self._escape = ""
                self._add(decoded, out)
            elif ch == "\\":
                self._escape = "\\"
            elif ch == '"':
                self._in_string = False
                if self._expect_key:
                    self._key = self._buf
            else:
                self._add(ch, out)
        return "".join(out)

    def _add(self, ch: str, out: list[str]) -> None:
        self._buf += ch
        if self._emit:
            out.append(ch)
