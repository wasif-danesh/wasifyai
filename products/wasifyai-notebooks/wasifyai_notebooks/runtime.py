# SPDX-License-Identifier: Apache-2.0
"""What the notebooks need at run time: the store, the pieces it depends on, the reading worker.

Built once, from the engine's app state (the data folder, the model folders, the products folder),
and shared by the routes and the chat graph, so both see the same library.
"""

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wasifyai_notebooks.components import Components, reader_dir_from
from wasifyai_notebooks.ingest import IngestWorker
from wasifyai_notebooks.reader_install import ReaderInstaller, load_weights, uv_target
from wasifyai_notebooks.reading import Reader, RoutingReader
from wasifyai_notebooks.store import NotebookStore

PRODUCT_ID = "wasifyai-notebooks"


class NotAvailable(Exception):
    """Notebooks are not served by this deployment (no app data folder)."""


@dataclass
class Runtime:
    """The library of one engine."""

    store: NotebookStore
    components: Components
    worker: IngestWorker
    files_dir: Path
    tmp_dir: Path
    installer: ReaderInstaller | None = None
    installer_problem: str = ""

    @classmethod
    def build(
        cls,
        data_dir: Path,
        roots: Callable[[], list[Path]],
        reader: Reader | None = None,
        products_dir: Path | None = None,
    ) -> "Runtime":
        root = Path(data_dir) / "notebooks"
        components = Components(roots, reader_dir_from(data_dir))
        store = NotebookStore(
            root, dimension=components.spec.dimension, embedder_id=components.spec.id
        )
        files = root / "files"
        files.mkdir(parents=True, exist_ok=True)
        tmp = root / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        worker = IngestWorker(store, components, reader or RoutingReader(components), files)
        installer, problem = _installer(data_dir, components, products_dir)
        return cls(store, components, worker, files, tmp, installer, problem)


def _installer(
    data_dir: Path, components: Components, products_dir: Path | None
) -> tuple[ReaderInstaller | None, str]:
    """The reader's installer, or why it cannot run here (no lock for this platform, no uv)."""
    base = (products_dir or Path("products")) / PRODUCT_ID / "reader"
    lock = base / f"requirements-{uv_target()}.lock"
    if not lock.is_file() or not (base / "models.yaml").is_file():
        return None, "The reader is not part of this build."
    uv = os.environ.get("WASIFYAI_UV") or shutil.which("uv")
    if not uv:
        return None, "The tool that sets up the reader was not found."
    cache = Path(data_dir) / "engine" / "cache"
    return (
        ReaderInstaller(
            reader_dir=components.reader_dir,
            lock=lock,
            weights=load_weights(base / "models.yaml"),
            worker_script=Path(__file__).with_name("docling_worker.py"),
            uv=uv,
            cache_dir=cache if cache.is_dir() else None,
        ),
        "",
    )


def runtime_for(state: Any) -> Runtime:
    """The engine's runtime, made on first use and kept on the app state."""
    existing = getattr(state, "notebooks_runtime", None)
    if existing is not None:
        return existing
    data = getattr(state, "desktop_dir", None)
    if not data:
        raise NotAvailable("Notebooks are not available in this deployment yet.")
    models = getattr(state, "desktop_models", None)
    data_dir = Path(data)

    def roots() -> list[Path]:
        return list(models.roots()) if models is not None else [data_dir / "models"]

    products = getattr(state, "products_dir", None)
    runtime = Runtime.build(data_dir, roots, products_dir=Path(products) if products else None)
    state.notebooks_runtime = runtime
    return runtime
