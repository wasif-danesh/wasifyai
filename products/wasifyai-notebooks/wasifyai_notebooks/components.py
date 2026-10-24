# SPDX-License-Identifier: Apache-2.0
"""The two pieces a notebook needs that are not in the engine's own environment (ADR-0065
decisions 7 and 8), and how the engine finds them.

    search model   `bge-small-en-v1.5`, two files from the Models panel (folder `embeddings`)
    document reader   Docling in an environment of its own, set up by the app: `reader/` under the
                      app's data folder holds `venv/`, `models/` and `installed.json`
"""

import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wasifyai_notebooks.embedding import BGE_SMALL, EmbedderSpec, OnnxEmbedder

# the files of models.yaml, by name and size (their SHA-256 was checked when they were downloaded)
EMBEDDER_FILES = {
    "weights": ("bge-small-en-v1.5-q.onnx", 66465124),
    "tokenizer": ("bge-small-en-v1.5-tokenizer.json", 711396),
}


class Unavailable(Exception):
    """A piece is not set up yet. `code` is stable (the window keys its notice on it)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ReaderInstall:
    python: Path
    models: Path


def _reader_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


class Components:
    """`roots` returns the folders models may be in (the app's own and any read-only ones)."""

    def __init__(
        self,
        roots: Callable[[], Sequence[Path]],
        reader_dir: Path,
        spec: EmbedderSpec = BGE_SMALL,
    ):
        self._roots = roots
        self.reader_dir = Path(reader_dir)
        self.spec = spec
        self._embedder: OnnxEmbedder | None = None

    # ---- the search model ------------------------------------------------------------------

    def embedder_paths(self) -> tuple[Path, Path] | None:
        found: dict[str, Path] = {}
        for key, (name, size) in EMBEDDER_FILES.items():
            for root in self._roots():
                p = Path(root) / "embeddings" / name
                if p.is_file() and p.stat().st_size == size:
                    found[key] = p
                    break
        if len(found) != len(EMBEDDER_FILES):
            return None
        return found["weights"], found["tokenizer"]

    def embedder(self) -> OnnxEmbedder:
        if self._embedder is None:
            paths = self.embedder_paths()
            if paths is None:
                raise Unavailable(
                    "embedder_missing",
                    "The search model is not on this computer yet. "
                    "Get it in the Model hub, then add the "
                    "source again.",
                )
            self._embedder = OnnxEmbedder(self.spec, *paths)
        return self._embedder

    chunk_size: int = 480  # tokens of `tokenizer()` a passage holds at most (chunking.CHUNK_TOKENS)

    def tokenizer(self) -> Any:
        """What counts the size of a passage while a document is cut."""
        from wasifyai_notebooks.chunking import load_tokenizer

        return load_tokenizer(self.tokenizer_path())

    def tokenizer_path(self) -> Path:
        paths = self.embedder_paths()
        if paths is None:
            raise Unavailable(
                "embedder_missing",
                "The search model is not on this computer yet. "
                "Get it in the Model hub, then add the "
                "source again.",
            )
        return paths[1]

    # ---- the document reader ---------------------------------------------------------------

    def reader_install(self) -> ReaderInstall | None:
        marker = self.reader_dir / "installed.json"
        if not marker.is_file():
            return None
        try:
            json.loads(marker.read_text())
        except ValueError:
            return None
        python = _reader_python(self.reader_dir / "venv")
        models = self.reader_dir / "models"
        if not python.is_file() or not models.is_dir():
            return None
        return ReaderInstall(python, models)

    def state(self) -> dict[str, dict[str, object]]:
        install = self.reader_install()
        return {
            "embedder": {
                "ready": self.embedder_paths() is not None,
                "id": self.spec.id,
                "size_bytes": sum(size for _, size in EMBEDDER_FILES.values()),
            },
            "reader": {
                "ready": install is not None,
                "id": "docling",
                # plain text, Markdown, CSV and HTML are read without it
                "needed_for": ["pdf", "docx", "pptx", "xlsx", "images"],
            },
        }


def reader_dir_from(data_dir: Path) -> Path:
    override = os.environ.get("WASIFYAI_READER_DIR")
    return Path(override) if override else Path(data_dir) / "components" / "reader"


class GatewayComponents(Components):
    """The search model is the platform's, asked through the gateway; there are no model files. A
    passage is sized in characters (about 1500 of them, a few hundred tokens in any script), because
    a word count cuts nothing in a language written without spaces."""

    chunk_size = 1500

    def __init__(self, embedder: Any, reader_dir: Path):
        super().__init__(lambda: [], reader_dir, embedder.spec)
        self._gateway = embedder

    def embedder_paths(self) -> tuple[Path, Path] | None:  # type: ignore[override]
        return (Path("gateway"), Path("gateway"))  # nothing to wait for

    def embedder(self) -> Any:
        return self._gateway

    def tokenizer(self) -> Any:
        return "character"

    def state(self) -> dict[str, dict[str, object]]:
        out = super().state()
        out["embedder"] = {"ready": True, "id": self.spec.id, "size_bytes": 0}
        return out
