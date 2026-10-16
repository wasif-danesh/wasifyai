# SPDX-License-Identifier: Apache-2.0
"""What an upload must be before it is stored (ADR-0035, ADR-0060 decision 3, ADR-0065 decision 6).

The extension is a claim; the bytes must agree with it. Nothing here opens a document with a parser:
that happens later, in a process of its own.
"""

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 100 * 1024 * 1024  # per file (ADR-0060 decision 3)
MAX_ZIP_ENTRIES = 10_000  # an OOXML file is a zip; a bomb has far more parts than a document
MAX_UNPACKED = 2 * 1024**3
MAX_TITLE = 500

# extension -> (kind of bytes, MIME type stored; the server's, never the client's)
ALLOWED: dict[str, tuple[str, str]] = {
    ".pdf": ("pdf", "application/pdf"),
    ".docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".pptx": ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ".xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".html": ("text", "text/html"),
    ".htm": ("text", "text/html"),
    ".csv": ("text", "text/csv"),
    ".md": ("text", "text/markdown"),
    ".markdown": ("text", "text/markdown"),
    ".txt": ("text", "text/plain"),
    ".text": ("text", "text/plain"),
    ".png": ("png", "image/png"),
    ".jpg": ("jpeg", "image/jpeg"),
    ".jpeg": ("jpeg", "image/jpeg"),
    ".tif": ("tiff", "image/tiff"),
    ".tiff": ("tiff", "image/tiff"),
    ".bmp": ("bmp", "image/bmp"),
    ".webp": ("webp", "image/webp"),
}

# the part that makes a zip a Word, PowerPoint or Excel file
_MAIN_PART = {
    "docx": "word/document.xml",
    "pptx": "ppt/presentation.xml",
    "xlsx": "xl/workbook.xml",
}

_SUFFIX = re.compile(r"^\.[A-Za-z0-9]{1,16}$")


@dataclass(frozen=True)
class Checked:
    suffix: str
    mime: str


class Refused(Exception):
    """A file that will not be stored, with a sentence safe to show to the person."""


def suffix_of(filename: str) -> str:
    """The validated extension of a client's file name, lower case."""
    suffix = Path(filename.replace("\\", "/").rsplit("/", 1)[-1]).suffix.lower()
    if not _SUFFIX.match(suffix) or suffix not in ALLOWED:
        listed = ", ".join(sorted({s.lstrip(".") for s in ALLOWED}))
        raise Refused(f"This kind of file cannot be added. These can: {listed}.")
    return suffix


def check_file(path: Path, filename: str) -> Checked:
    """Refuse a file whose bytes do not match its extension, or that is too large or unsafe."""
    suffix = suffix_of(filename)
    kind, mime = ALLOWED[suffix]
    size = path.stat().st_size
    if size == 0:
        raise Refused("The file is empty.")
    if size > MAX_BYTES:
        raise Refused(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    with path.open("rb") as f:
        head = f.read(65536)
    if not _agrees(kind, head, path):
        raise Refused("The file does not look like what its name says.")
    return Checked(suffix, mime)


def _agrees(kind: str, head: bytes, path: Path) -> bool:
    if kind == "pdf":
        return b"%PDF-" in head[:1024]
    if kind in _MAIN_PART:
        return _office_zip(path, _MAIN_PART[kind])
    if kind == "text":
        return _is_text(head)
    if kind == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if kind == "jpeg":
        return head.startswith(b"\xff\xd8\xff")
    if kind == "tiff":
        return head[:4] in (b"II*\x00", b"MM\x00*")
    if kind == "bmp":
        return head.startswith(b"BM")
    if kind == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return False


def _is_text(head: bytes) -> bool:
    """UTF-8 with no NUL and few control bytes. A cut multibyte character at the end is allowed."""
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        if e.start < len(head) - 4:
            return False
    controls = sum(1 for b in head if b < 32 and b not in (9, 10, 13, 12))
    return controls <= max(1, len(head) // 100)


def _office_zip(path: Path, main_part: str) -> bool:
    if not zipfile.is_zipfile(path):
        return False
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise Refused("The file has too many parts to be a normal document.")
        if sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise Refused("The file unpacks to far more than a normal document.")
        names = {i.filename for i in infos}
    return "[Content_Types].xml" in names and main_part in names


def safe_name(filename: str) -> str:
    """The last path part, with only characters every file system takes. Used for the stored copy
    and the title; never for a path outside the document's own folder."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    base = re.sub(r"[^\w .()\-]", "_", base, flags=re.UNICODE).strip(" .")
    return (base or "document")[:120]
