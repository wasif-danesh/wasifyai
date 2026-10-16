# SPDX-License-Identifier: Apache-2.0
"""Turning a stored file into Markdown (ADR-0065 decision 7).

Plain text, Markdown, CSV and HTML are read here, with no component. Everything else goes to the
document reader, a Docling environment run as a subprocess with a timeout (ADR-0060 decision 3:
parsers never run in the engine's own process, so a hostile or huge file cannot take it down).
"""

import asyncio
import csv
import io
import json
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

from wasifyai_notebooks.components import Components, Unavailable

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".text", ".csv", ".html", ".htm"}
MAX_TEXT_CHARS = 5_000_000  # extracted text is capped (ADR-0060 decision 3)
MAX_CSV_ROWS = 5000
READ_TIMEOUT_S = 15 * 60


@dataclass(frozen=True)
class ReadResult:
    markdown: str
    pages: int | None = None


class ReadError(Exception):
    """The file could not be read; `str(e)` is a sentence safe to show."""


class Reader(Protocol):
    async def read(self, path: Path, suffix: str) -> ReadResult: ...


def needs_reader(suffix: str) -> bool:
    return suffix.lower() not in TEXT_SUFFIXES


class _Text(HTMLParser):
    """Visible text of an HTML page, with headings as Markdown headings."""

    SKIP = {"script", "style", "noscript", "template", "head"}
    BLOCK = {"p", "div", "li", "br", "tr", "section", "article", "ul", "ol", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0
        self._title = False
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "title":
            self._title = True
        if tag in self.SKIP and tag != "head":
            self._skip += 1
        if len(tag) == 2 and tag[0] == "h" and tag[1] in "123456":
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._title = False
        if tag in self.SKIP and tag != "head":
            self._skip = max(0, self._skip - 1)
        if len(tag) == 2 and tag[0] == "h" and tag[1] in "123456":
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_markdown(source: str) -> str:
    p = _Text()
    p.feed(source)
    text = "".join(p.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    body = "\n".join(out).strip()
    has_h1 = any(line.startswith("# ") for line in out)
    return f"# {p.title.strip()}\n\n{body}" if p.title.strip() and not has_h1 else body


def csv_to_markdown(source: str) -> str:
    rows = list(csv.reader(io.StringIO(source)))[: MAX_CSV_ROWS + 1]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    cells = [
        [c.replace("|", "\\|").replace("\n", " ") for c in r + [""] * (width - len(r))]
        for r in rows
    ]
    head, *body = cells
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * width) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


class BuiltinReader:
    async def read(self, path: Path, suffix: str) -> ReadResult:
        suffix = suffix.lower()
        raw = await asyncio.to_thread(path.read_bytes)
        text = raw.decode("utf-8-sig", errors="replace")[:MAX_TEXT_CHARS]
        if suffix in (".html", ".htm"):
            text = html_to_markdown(text)
        elif suffix == ".csv":
            text = csv_to_markdown(text)
        return ReadResult(text)


class DoclingReader:
    """Reads through `docling_worker.py --serve` in the reader environment.

    The process starts on the first file and ends after `idle_s` with nothing to read, so its 2 to
    4 GB is returned when a batch is done. One file at a time; a file that runs past `timeout_s`
    kills the process (the next file starts a new one).
    """

    def __init__(
        self,
        components: Components,
        timeout_s: float = READ_TIMEOUT_S,
        script: Path | None = None,
        idle_s: float = 60.0,
    ):
        self._components = components
        self._timeout = timeout_s
        self._script = script or Path(__file__).with_name("docling_worker.py")
        self._idle = idle_s
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0
        self._idle_task: asyncio.Task | None = None

    async def _start(self) -> asyncio.subprocess.Process:
        install = self._components.reader_install()
        if install is None:
            raise Unavailable(
                "reader_missing",
                "Reading this kind of file needs the document reader. Set it up in Settings, then "
                "read the source again.",
            )
        proc = await asyncio.create_subprocess_exec(
            str(install.python), "-I", str(self._script), "--serve",
            "--models", str(install.models),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        assert proc.stdout is not None
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=self._timeout)
        except TimeoutError:
            await self._kill(proc)
            raise ReadError("The document reader did not start in time.") from None
        hello = json.loads(line) if line else {}
        if not hello.get("ok"):
            await self._kill(proc)
            detail = str(hello.get("error", "it stopped at start"))[:200]
            raise ReadError(f"The document reader could not start ({detail}).")
        return proc

    @staticmethod
    async def _kill(proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()

    async def read(self, path: Path, suffix: str) -> ReadResult:
        async with self._lock:
            if self._idle_task:
                self._idle_task.cancel()
                self._idle_task = None
            if self._proc is None or self._proc.returncode is not None:
                self._proc = await self._start()
            proc = self._proc
            assert proc.stdin is not None and proc.stdout is not None
            self._next_id += 1
            request_id = self._next_id
            with tempfile.TemporaryDirectory(prefix="wasifyai-read-") as tmp:
                out = Path(tmp) / "out.json"
                request = {"id": request_id, "file": str(path), "out": str(out)}
                try:
                    proc.stdin.write((json.dumps(request) + "\n").encode())
                    await proc.stdin.drain()
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=self._timeout)
                except TimeoutError as e:
                    await self._drop()
                    raise ReadError("Reading this file took too long and was stopped.") from e
                except (BrokenPipeError, ConnectionResetError) as e:
                    await self._drop()
                    raise ReadError(
                        "The document reader stopped. Try reading the file again."
                    ) from e
                except asyncio.CancelledError:
                    await self._drop()
                    raise
                if not line:
                    await self._drop()
                    raise ReadError("The document reader stopped. Try reading the file again.")
                answer = json.loads(line)
                if not answer.get("ok") or not out.is_file():
                    detail = str(answer.get("error", ""))[:200]
                    raise ReadError(f"The file could not be read ({detail}).")
                data = json.loads(out.read_text())
            self._idle_task = asyncio.create_task(self._close_when_idle())
        return ReadResult(str(data["markdown"])[:MAX_TEXT_CHARS], data.get("pages"))

    async def _drop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            await self._kill(proc)

    async def _close_when_idle(self) -> None:
        await asyncio.sleep(self._idle)
        async with self._lock:
            await self._drop()

    async def close(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
        async with self._lock:
            await self._drop()


class RoutingReader:
    """The built-in reader for text, the document reader for the rest."""

    def __init__(self, components: Components, docling: Reader | None = None):
        self._builtin = BuiltinReader()
        self._docling = docling or DoclingReader(components)

    async def read(self, path: Path, suffix: str) -> ReadResult:
        reader = self._docling if needs_reader(suffix) else self._builtin
        return await reader.read(path, suffix)

    async def close(self) -> None:
        close = getattr(self._docling, "close", None)
        if close is not None:
            await close()


__all__ = [
    "BuiltinReader",
    "DoclingReader",
    "ReadError",
    "ReadResult",
    "Reader",
    "RoutingReader",
    "Unavailable",
    "csv_to_markdown",
    "html_to_markdown",
    "needs_reader",
]
