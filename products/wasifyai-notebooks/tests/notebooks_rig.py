"""Test doubles for the notebooks product: a small embedder that needs no model, components that
need no download, and a reader that needs no Docling."""

import asyncio
import hashlib
import math
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest
from wasifyai_notebooks.components import Components, ReaderInstall, Unavailable
from wasifyai_notebooks.embedding import EmbedderSpec, Pooling, Purpose
from wasifyai_notebooks.reading import ReadResult

SPEC = EmbedderSpec(
    id="fake-hash-64", dimension=64, pooling=Pooling.CLS, normalize=True, max_tokens=512,
    semantic_weight=0.65,
)  # fmt: skip
_WORD = re.compile(r"\w+")


class HashEmbedder:
    """Words hashed into 64 buckets: texts that share words are close. Not semantic."""

    spec = SPEC

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]:
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * SPEC.dimension
            for w in _WORD.findall(t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % SPEC.dimension] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class FakeComponents(Components):
    def __init__(self, tmp: Path, *, embedder_ready: bool = True, reader_ready: bool = False):
        super().__init__(lambda: [tmp / "models"], tmp / "reader", SPEC)
        self.ready = embedder_ready
        self.reader_ready = reader_ready
        self.fake = HashEmbedder()

    def embedder_paths(self):  # type: ignore[override]
        return (Path("w"), Path("t")) if self.ready else None

    def embedder(self):  # type: ignore[override]
        if not self.ready:
            raise Unavailable("embedder_missing", "The search model is not on this computer yet.")
        return self.fake

    def tokenizer_path(self) -> Path:
        return Path("t")

    def reader_install(self):  # type: ignore[override]
        return ReaderInstall(Path("python"), Path("models")) if self.reader_ready else None


class FakeReader:
    """Returns canned Markdown by file name; raises for a name it was told to."""

    def __init__(self, texts: dict[str, str] | None = None):
        self.texts = texts or {}
        self.reads: list[str] = []
        self.gate: asyncio.Event | None = None  # an event a test can hold a read on

    async def read(self, path: Path, suffix: str) -> ReadResult:
        self.reads.append(path.name)
        if self.gate is not None:
            await self.gate.wait()
        if path.name in self.texts:
            return ReadResult(self.texts[path.name], 3)
        return ReadResult(path.read_text(errors="replace"))  # noqa: ASYNC240


def pg_dsn() -> str:
    """The Postgres the store tests run against: `DATABASE_URL` (as CI and `make dev` set it) or the
    compose stack's default. The test skips when nothing answers there."""
    url = os.environ.get("DATABASE_URL", "postgresql://wasifyai:wasifyai@localhost:5432/wasifyai")
    dsn = url.replace("+asyncpg", "").replace("+psycopg", "")
    u = urlparse(dsn)
    try:
        socket.create_connection((u.hostname or "localhost", u.port or 5432), timeout=1).close()
    except OSError:
        pytest.skip("Postgres not reachable")
    return dsn
