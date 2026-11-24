"""A file name a person gave, made safe to show and keep as a title.

The browser sends the name as the person's computer has it, and anyone can send any name:
folders in front ("../../etc/passwd.wav"), control characters, and the marks that turn text right
to left, which make "photo<U+202E>gnp.exe" read "photoexe.png" (test E, 2026-11-21: a recording
kept both). The last part of the path is kept, every character that is not printable (control and
format characters, these marks included) is dropped, and the length is bounded. Letters of every
language stay.
"""

DEFAULT_CHARS = 200


def shown_name(raw: str | None, fallback: str = "file", limit: int = DEFAULT_CHARS) -> str:
    """The name to show: its last part, printable characters only, at most `limit` long."""
    base = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(c for c in base if c.isprintable()).strip()
    return base[:limit] or fallback


def shown_stem(raw: str | None, fallback: str = "file", limit: int = 120) -> str:
    """The name without its extension ("Holiday" for "Holiday.wav"), as a title."""
    name = shown_name(raw, "", DEFAULT_CHARS)
    stem = name.rsplit(".", 1)[0] if "." in name[1:] else name
    return stem.strip()[:limit] or fallback
