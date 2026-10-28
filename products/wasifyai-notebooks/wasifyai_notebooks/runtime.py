# SPDX-License-Identifier: Apache-2.0
"""What the notebooks need at run time: the store, the pieces it depends on, the reading worker.

Built once, from the engine's app state (the data folder, the model folders, the products folder),
and shared by the routes and the chat graph, so both see the same library.
"""

import asyncio
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import Storage
from wasifyai_platform_sdk.usage import EMBEDDING_TOKENS

from wasifyai_notebooks.components import Components, GatewayComponents, reader_dir_from
from wasifyai_notebooks.embedding import GATEWAY_ALIAS, GatewayEmbedder, Purpose, embed_counted
from wasifyai_notebooks.files import FileLibrary, FileStore, LocalFiles
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
    # where originals and the outputs' files are kept: folders on the desktop, objects on the web
    files: FileLibrary | None = None
    # whether this program reads the sources (the desktop engine does; on the web a worker does)
    reads_sources: bool = True
    # whether a worker, not this program, makes the Studio outputs (the web)
    outputs_by_worker: bool = False

    def __post_init__(self) -> None:
        if self.files is None:
            self.files = LocalFiles(self.files_dir.parent)

    def query_vector(
        self, embedder: Any, tenant: str, user: str, text: str, source: str
    ) -> list[float]:
        """A question as a vector, with the tokens it cost noted for the person."""
        vectors, tokens = embed_counted(embedder, [text], Purpose.QUERY)
        if tokens:
            self.store.record_usage(
                tenant, user, EMBEDDING_TOKENS, tokens, "tokens",
                capability="notebooks.embed", source=source,
            )  # fmt: skip
        return vectors[0]

    def files_for(self, tenant: str, user: str) -> "FileStore":
        """The files of one person."""
        assert self.files is not None
        return self.files.for_owner(tenant, user)

    @property
    def artifacts_dir(self) -> Path:
        """Where the files of a notebook's outputs (Word, PDF, JSON) are kept."""
        return self.files_dir.parent / "artifacts"

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


# a source another reader has had this long (more than a reading may take) is taken as lost
STALE_AFTER_S = 30 * 60


@dataclass
class WebSetup:
    """What the web profile gives the notebooks: the database, the object storage, and where the
    search model and the document reader are on the machine that reads (docs/phase3-web-parity-plan
    W4). The engine's own program only serves requests; a worker (`worker.py`) reads the sources."""

    dsn: str
    storage: Storage
    models_dir: Path
    reader_dir: Path
    tmp_dir: Path
    schema: str = "notebooks"
    loop: asyncio.AbstractEventLoop | None = None  # the engine's loop, for its storage calls
    components: Components | None = None  # made from the folders above unless a test gives them
    # the search model through the gateway (rule 5), instead of model files on the machine
    gateway_url: str = ""
    gateway_key: str = ""
    embed_model: str = GATEWAY_ALIAS
    embed_dimension: int = 1024

    def _components(self) -> Components:
        if self.gateway_url:
            embedder = GatewayEmbedder(
                self.gateway_url,
                self.gateway_key,
                model=self.embed_model,
                dimension=self.embed_dimension,
            )
            return GatewayComponents(embedder, self.reader_dir)
        return Components(lambda: [self.models_dir], self.reader_dir)

    def build(
        self,
        *,
        reads_sources: bool,
        components: Components | None = None,
        tokenizer_factory: Callable[[], Any] | None = None,
    ) -> "Runtime":
        from wasifyai_notebooks.files import ObjectFiles
        from wasifyai_notebooks.pgstore import PostgresNotebookStore

        comps = (
            components or self.components or Components(lambda: [self.models_dir], self.reader_dir)
        )
        store = PostgresNotebookStore(
            self.dsn,
            dimension=comps.spec.dimension,
            embedder_id=comps.spec.id,
            schema=self.schema,
        )
        library = ObjectFiles(self.storage, self.loop)
        files = self.tmp_dir / "files"
        files.mkdir(parents=True, exist_ok=True)
        worker = IngestWorker(
            store,
            comps,
            RoutingReader(comps),
            library,
            tokenizer_factory=tokenizer_factory,
            stale_after_s=STALE_AFTER_S,
        )
        return Runtime(
            store,
            comps,
            worker,
            files,
            self.tmp_dir,
            files=library,
            reads_sources=reads_sources,
            outputs_by_worker=not reads_sources,
        )


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
    existing = state.notebooks_runtime
    if existing is not None:
        return existing
    web = state.notebooks_web
    if web is not None:  # the web profile: Postgres and object storage, read by a worker
        runtime = web.build(reads_sources=False)
        state.notebooks_runtime = runtime
        return runtime
    data = state.desktop_dir
    if not data:
        raise NotAvailable("Notebooks are not available in this deployment yet.")
    models = state.desktop_models
    data_dir = Path(data)

    def roots() -> list[Path]:
        return list(models.roots()) if models is not None else [data_dir / "models"]

    products = state.products_dir
    runtime = Runtime.build(data_dir, roots, products_dir=Path(products) if products else None)
    state.notebooks_runtime = runtime
    return runtime
