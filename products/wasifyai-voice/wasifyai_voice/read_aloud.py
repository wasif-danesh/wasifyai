# SPDX-License-Identifier: Apache-2.0
"""Read aloud: a chat reply spoken by the speech model, and thrown away (ADR-0083, decision 5; CU3).

The window sends the text of one reply. This turns it into plain words (a speech model must not say
"asterisk asterisk", read a web address out letter by letter or recite a code block), cuts them into
passages at the ends of sentences, and the route speaks one passage per request. The window asks for
the next passage while the first one plays, so sound starts after one passage and not after the
whole reply. Nothing is stored: the text is held for the request, the audio goes back in the
answer, and neither is logged.

Every limit is here, in one place, and every refusal is a sentence."""

import re
import unicodedata
from dataclasses import dataclass

MAX_RAW_CHARS = 40_000  # a long answer as the model wrote it, markdown and all
PASSAGE_CHARS = 600  # about forty seconds of speech
FIRST_PASSAGE_CHARS = (
    300  # the first is shorter, so sound starts sooner (unless one sentence is longer)
)
MAX_PASSAGES = (
    8  # about five minutes: a longer reply is read from its start, and the window says so
)
MAX_READ_CHARS = FIRST_PASSAGE_CHARS + PASSAGE_CHARS * (MAX_PASSAGES - 1)

# marks that end a sentence in the scripts the app may meet (Latin, Devanagari and Bengali danda,
# CJK, Arabic)
_SENTENCE_END = r"[.!?…。！？।॥؟]"
_SPLIT = re.compile(rf"(?<={_SENTENCE_END})\s+|(?<={_SENTENCE_END}[\"')\]»”’])\s+|\n+")

# characters that change how text is shown or is read by a program, not what it says: invisible
# formatting, bidirectional overrides, the byte-order mark. The joiners used inside Bengali, Hindi
# and Persian words (U+200C, U+200D) are part of the words and stay.
_KEEP_FORMAT = {"‌", "‍"}


class ReadAloudError(Exception):
    """`code` is stable; `str(e)` is a sentence safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Passages:
    items: tuple[str, ...]
    truncated: bool  # the reply was longer than the most that is read in one go


def _clean_chars(text: str) -> str:
    out = []
    for ch in unicodedata.normalize("NFC", text):
        cat = unicodedata.category(ch)
        if ch in "\n\t":
            out.append(ch)
        elif cat == "Cc" or cat == "Cs" or cat == "Co" or cat == "Cn":
            out.append(" ")
        elif cat == "Cf" and ch not in _KEEP_FORMAT:
            continue
        elif cat in ("Zl", "Zp"):
            out.append("\n")
        else:
            out.append(ch)
    return "".join(out)


_FENCE = re.compile(r"(?ms)^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*\1[`~]*[ \t]*$|\Z)")
_BLOCK_MATH = re.compile(r"(?s)\$\$.*?\$\$")
_HTML_COMMENT = re.compile(r"(?s)<!--.*?-->")
_HTML_BLOCK = re.compile(r"(?is)<(script|style|iframe|object|embed|svg|math)\b.*?(?:</\1\s*>|\Z)")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>\n]{0,200}>")
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
_LINK = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")
_REF_LINK = re.compile(r"\[([^\]\n]+)\]\[[^\]\n]*\]")
_REF_DEF = re.compile(r"(?m)^[ \t]*\[[^\]\n]+\]:[ \t]*\S.*$")
_CITATION = re.compile(r"\[\d{1,3}(?:\s*,\s*\d{1,3})*\]")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>()\[\]]+")
_AUTOLINK = re.compile(r"<(?:https?://|mailto:)[^>\s]+>")
_INLINE_CODE = re.compile(r"(`+)(.+?)\1")
_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+")
_QUOTE = re.compile(r"(?m)^[ \t]*(?:>[ \t]?)+")
_BULLET = re.compile(r"(?m)^[ \t]*(?:[-*+•]|\d{1,3}[.)])[ \t]+")
_RULE = re.compile(r"(?m)^[ \t]*(?:[-*_=][ \t]*){3,}$")
_TABLE_RULE = re.compile(r"(?m)^[ \t]*\|?(?:[ \t]*:?-{2,}:?[ \t]*\|)+[ \t]*:?-{0,}:?[ \t]*$")
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3}|~~)(?=\S)(.+?)(?<=\S)\1")
_SPACES = re.compile(r"[ \t ]+")


def _table_row(line: str) -> str:
    """A table row read as its cells, separated by commas; a stray bar is a space."""
    if line.lstrip().startswith("|"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        return ", ".join(c for c in cells if c)
    return line.replace("|", " ")


def plain_words(text: str) -> str:
    """The words of a markdown reply, as a person would say them. Code blocks, pictures' addresses,
    links' addresses, tags, citations like [1] and table rules are dropped; the text of a link, a
    heading, an emphasis and a table cell stays. Anything that is not text (a control character, a
    bidirectional override) is gone before anything else is looked at."""
    s = _clean_chars(str(text or ""))
    s = _FENCE.sub("\n", s)
    s = _BLOCK_MATH.sub(" ", s)
    s = _HTML_COMMENT.sub(" ", s)
    s = _HTML_BLOCK.sub(" ", s)
    s = _REF_DEF.sub("", s)
    s = _IMAGE.sub(lambda m: m.group(1), s)
    s = _LINK.sub(lambda m: m.group(1), s)
    s = _REF_LINK.sub(lambda m: m.group(1), s)
    s = _AUTOLINK.sub(" ", s)
    s = _URL.sub(" ", s)
    s = _INLINE_CODE.sub(lambda m: m.group(2), s)
    s = _HTML_TAG.sub(" ", s)
    s = _CITATION.sub("", s)
    s = _TABLE_RULE.sub("", s)
    s = _RULE.sub("", s)
    s = _HEADING.sub("", s)
    s = _QUOTE.sub("", s)
    s = _BULLET.sub("", s)
    for _ in range(3):  # nested emphasis: ***bold _and_ more***
        s = _EMPHASIS.sub(lambda m: m.group(2), s)
    s = "\n".join(_table_row(line) for line in s.split("\n"))
    s = re.sub(r"[*_~`#\\]+", " ", s)  # whatever markup is left over
    lines = [
        re.sub(r" +([.,;:!?])", r"\1", _SPACES.sub(" ", line)).strip() for line in s.split("\n")
    ]
    # a line that does not end a sentence (a heading, a list item) gets a full stop: a pause
    done = [
        line if re.search(_SENTENCE_END + r"[\"')\]»”’]?$|[:;,]$", line) else f"{line}."
        for line in lines
        if re.search(r"\w", line)
    ]
    return "\n".join(done).strip()


def _cut(sentence: str) -> list[str]:
    """A sentence longer than a passage, cut at spaces (or, with none, wherever it must be)."""
    out: list[str] = []
    while len(sentence) > PASSAGE_CHARS:
        at = sentence.rfind(" ", 0, PASSAGE_CHARS)
        at = at if at > PASSAGE_CHARS // 2 else PASSAGE_CHARS
        out.append(sentence[:at].strip())
        sentence = sentence[at:].strip()
    if sentence:
        out.append(sentence)
    return out


def passages(text: str) -> Passages:
    """The reply cut into passages at the ends of sentences: at most `PASSAGE_CHARS` each (the first
    packed to `FIRST_PASSAGE_CHARS` where it can be), and at most `MAX_PASSAGES` of them. Raises
    `ReadAloudError` when the text is too long to look at, or has nothing in it to say."""
    if len(text or "") > MAX_RAW_CHARS:
        raise ReadAloudError(
            "too_long", "That reply is too long to read aloud here. Copy the part you want."
        )
    words = plain_words(text)
    if not words:
        raise ReadAloudError(
            "nothing_to_read",
            "There is nothing in this reply to read aloud (it is only code or a picture).",
        )
    pieces: list[str] = []
    for sentence in (s.strip() for s in _SPLIT.split(words)):
        if sentence:
            pieces.extend(_cut(sentence))
    out: list[str] = []
    current = ""
    for piece in pieces:
        limit = PASSAGE_CHARS if out else FIRST_PASSAGE_CHARS
        if current and len(current) + 1 + len(piece) > limit:
            out.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        out.append(current)
    return Passages(tuple(out[:MAX_PASSAGES]), truncated=len(out) > MAX_PASSAGES)
