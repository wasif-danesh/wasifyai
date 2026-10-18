# SPDX-License-Identifier: Apache-2.0
# The steps and the cancel/interrupt rules follow SurfSense (Apache-2.0),
# worker/ingestion/pipeline.py and worker/jobs.py, commit 622c1ded8. See ../PROVENANCE.md.
"""Reading a source into the library: parse, cut into passages, embed, index (ADR-0065 decision 6).

One source at a time: reading saturates the processor and writes to the file the engine serves from.
Cancel is checked between steps; a running read is not killed mid-step, it notices at the next one.
A failure is written on the source with a sentence a person can act on.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.usage import EMBEDDING_TOKENS

from wasifyai_notebooks.chunking import chunk
from wasifyai_notebooks.components import Components, Unavailable
from wasifyai_notebooks.embedding import EmbedError, Purpose, embed_counted
from wasifyai_notebooks.files import FileLibrary, as_library, original_key
from wasifyai_notebooks.reading import Reader, ReadError, ReadResult
from wasifyai_notebooks.store import NotebookStore

log = logging.getLogger(__name__)

# a file that should hold text but gave almost none is a scan the reader could not read, not an
# empty document (E0: an unreadable scan came back as a bare `<!-- image -->` and no error)
MIN_TEXT_CHARS = 20
POLL_S = 1.0
SWEEP_S = 60.0  # how often a reader looks for sources another reader lost

NO_TEXT = (
    "No text could be read from this file. If it is a scan or a picture of text, the text may be "
    "too faint or too small to read."
)


def original_path(files_dir: Path, notebook_id: str, doc: dict[str, Any]) -> Path:
    from wasifyai_notebooks.hardening import safe_name

    return files_dir / notebook_id / doc["id"] / safe_name(doc["title"])


async def ingest_one(
    store: NotebookStore,
    components: Components,
    reader: Reader,
    files: FileLibrary | Path,
    doc: dict[str, Any],
    *,
    tokenizer_factory: Callable[[], Any] | None = None,
) -> str:
    """Read one pending source. Returns its final status. `files` is where the originals are kept
    (a library, or the desktop's `files` folder)."""
    began = await asyncio.to_thread(store.begin, doc["id"])
    if began is None:  # cancelled or deleted while it waited
        return "cancelled"
    did = doc["id"]

    async def cancelled() -> bool:
        return not await asyncio.to_thread(store.is_processing, did)

    try:
        embedder = components.embedder()
        if began["kind"] == "note":
            markdown, pages = began["content"] or "", None
        else:
            result = await _read_original(store, as_library(files), reader, began)
            markdown, pages = result.markdown, result.pages
            if len(markdown.strip()) < MIN_TEXT_CHARS:
                raise ReadError(NO_TEXT)
        if await cancelled():
            return "cancelled"

        tokenizer = (tokenizer_factory or components.tokenizer)()
        passages = await asyncio.to_thread(
            chunk, markdown, tokenizer=tokenizer, chunk_size=components.chunk_size
        )
        if await cancelled():
            return "cancelled"
        if not passages:
            raise ReadError(NO_TEXT)

        vectors, tokens = await asyncio.to_thread(
            embed_counted, embedder, [p.text for p in passages], Purpose.DOCUMENT
        )
        if tokens:
            owner = await asyncio.to_thread(store.owner_of, began["notebook_id"])
            if owner is not None:
                await asyncio.to_thread(
                    store.record_usage, *owner, EMBEDDING_TOKENS, tokens, "tokens",
                    capability="notebooks.embed", source="reading",
                )  # fmt: skip
        if await cancelled():
            return "cancelled"

        ok = await asyncio.to_thread(
            store.finish,
            did,
            markdown=None if began["kind"] == "note" else markdown,
            pages=pages,
            passages=passages,
            vectors=vectors,
            embedder=embedder.spec.id,
        )
        return "ready" if ok else "cancelled"
    except (ReadError, Unavailable, EmbedError) as e:
        message = e.message if isinstance(e, Unavailable) else str(e)
        await asyncio.to_thread(store.fail, did, message)
        return "failed"
    except asyncio.CancelledError:
        await asyncio.to_thread(store.fail, did, "Reading was interrupted.")
        raise
    except Exception:
        log.exception("reading a source failed")
        await asyncio.to_thread(store.fail, did, "Something went wrong reading this source.")
        return "failed"


async def _read_original(
    store: NotebookStore, files: FileLibrary, reader: Reader, doc: dict[str, Any]
) -> ReadResult:
    """Read a source's stored file. The reader needs a path: the file itself in a folder, a copy
    (removed afterwards) from object storage."""
    nid = doc["notebook_id"]
    owner = await asyncio.to_thread(store.owner_of, nid)
    if owner is None:
        raise ReadError("The notebook of this source is gone.")
    keep = files.for_owner(*owner).local(original_key(nid, doc))
    stored = await asyncio.to_thread(keep.__enter__)
    try:
        if stored is None:
            raise ReadError("The stored file is no longer here.")
        return await reader.read(stored, doc["suffix"] or "")
    finally:
        await asyncio.to_thread(keep.__exit__, None, None, None)


class IngestWorker:
    """The background loop: takes the next pending source, highest priority first."""

    def __init__(
        self,
        store: NotebookStore,
        components: Components,
        reader: Reader,
        files: FileLibrary | Path,
        *,
        tokenizer_factory: Callable[[], Any] | None = None,
        stale_after_s: float | None = None,
    ):
        """`stale_after_s` is for a deployment with several readers (the web): a source another
        reader has had longer than that is taken as lost. Left out, this is the only reader."""
        self._stale_after = stale_after_s
        self._store = store
        self._components = components
        self._reader = reader
        self._files = as_library(files)
        self._tokenizer_factory = tokenizer_factory
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._store.reset_interrupted(self._stale_after)
            self._task = asyncio.create_task(self._loop())

    def wake(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        close = getattr(self._reader, "close", None)
        if close is not None:
            await close()  # the document reader's process goes away with the worker

    async def drain(self, timeout: float = 60) -> None:  # noqa: ASYNC109
        """Wait until nothing is pending or being read (tests, and a clean shutdown)."""

        async def idle() -> None:
            while True:
                pending = await asyncio.to_thread(self._store.next_pending)
                busy = await asyncio.to_thread(self._busy)
                if pending is None and not busy:
                    return
                await asyncio.sleep(0.02)

        await asyncio.wait_for(idle(), timeout)

    def _busy(self) -> bool:
        with self._store.connect() as db:
            return (
                db.execute("SELECT 1 FROM documents WHERE status = 'processing' LIMIT 1").fetchone()
                is not None
            )

    async def _loop(self) -> None:
        swept = time.monotonic()
        while True:
            try:
                if self._stale_after is not None and time.monotonic() - swept > SWEEP_S:
                    swept = time.monotonic()
                    await asyncio.to_thread(self._store.reset_interrupted, self._stale_after)
                # nothing is read until the search model is here: sources added first stay waiting
                # and are read as soon as the model arrives, instead of failing one by one
                if self._components.embedder_paths() is None:
                    await asyncio.sleep(POLL_S)
                    continue
                doc = await asyncio.to_thread(self._store.next_pending)
                if doc is None:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), POLL_S)
                    except TimeoutError:
                        pass
                    continue
                await ingest_one(
                    self._store,
                    self._components,
                    self._reader,
                    self._files,
                    doc,
                    tokenizer_factory=self._tokenizer_factory,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ingest loop error")
                await asyncio.sleep(1)
