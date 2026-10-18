# SPDX-License-Identifier: Apache-2.0
"""Where a notebook's files are kept: the files people add as sources, and what its outputs make.

Two homes behind one small interface. On the desktop they are folders under the app's data folder
(`LocalFiles`). On the web they are objects in the deployment's object storage under the person's
own prefix (`ObjectFiles`; rules 7 and 10: `{tenant}/wasifyai-notebooks/{user}/...`). The code that
adds, reads and removes files asks for a store *for an owner* and uses plain keys:

    files/{notebook}/{document}/{name}      a source's original file
    artifacts/{notebook}/{output}/{name}    a file an output made (Word, PDF, audio, ...)

The store is synchronous, like the library's database: the engine and the reading worker call it
from a thread. A reader that needs a path (the document reader runs as a program) gets one from
`local()`: the file itself in a folder, or a copy that is removed afterwards for an object.
"""

import asyncio
import re
import shutil
import tempfile
from collections.abc import Coroutine, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, TypeVar

from wasifyai_platform_sdk import Storage
from wasifyai_platform_sdk.storage import object_key

PRODUCT_ID = "wasifyai-notebooks"
T = TypeVar("T")


def original_key(notebook_id: str, doc: dict[str, Any]) -> str:
    """The key of a source's original file."""
    from wasifyai_notebooks.hardening import safe_name

    return f"files/{notebook_id}/{doc['id']}/{safe_name(doc['title'])}"


def artifact_key(notebook_id: str, artifact_id: str, name: str = "") -> str:
    """The key of an output's folder, or of a file in it."""
    base = f"artifacts/{notebook_id}/{artifact_id}"
    return f"{base}/{Path(name).name}" if name else base


class FileStore(Protocol):
    """The files of one person. Keys are relative and use `/`; a key cannot leave the store."""

    def put_file(self, key: str, source: Path, content_type: str | None = None) -> None:
        """Keep a copy of a local file under `key`."""
        ...

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    def read_bytes(self, key: str) -> bytes | None:
        """The file, or None when there is none."""
        ...

    def exists(self, key: str) -> bool: ...

    def local(self, key: str) -> "Any":
        """A context manager giving a readable `Path` of the file (None if there is none)."""
        ...

    def local_path(self, key: str) -> Path | None:
        """The file's own path when the store is a folder (a response can stream it), else None."""
        ...

    def delete_prefix(self, prefix: str) -> None:
        """Remove the file at `prefix` or everything under it. Nothing there is not an error."""
        ...


class FileLibrary(Protocol):
    def for_owner(self, tenant: str, user: str) -> FileStore: ...


def _safe(key: str) -> str:
    parts = [p for p in key.split("/") if p]
    if not parts or any(p in (".", "..") or "\\" in p for p in parts):
        raise ValueError(f"not a file key: {key!r}")
    return "/".join(parts)


def as_library(files: "FileLibrary | Path") -> FileLibrary:
    """A files library from what a caller holds: a library, or the desktop's `files` folder (the
    parent of which is the root the keys are relative to)."""
    if isinstance(files, Path):
        return LocalFiles(files.parent)
    return files


class LocalFiles:
    """Folders under one root (the desktop's `<data>/notebooks`). One person owns the folder, so the
    owner is ignored."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def for_owner(self, tenant: str, user: str) -> "LocalFiles":
        return self

    def _path(self, key: str) -> Path:
        return self.root / _safe(key)

    def put_file(self, key: str, source: Path, content_type: str | None = None) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def read_bytes(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    @contextmanager
    def local(self, key: str) -> Iterator[Path | None]:
        path = self._path(key)
        yield path if path.is_file() else None

    def local_path(self, key: str) -> Path | None:
        path = self._path(key)
        return path if path.is_file() else None

    def delete_prefix(self, prefix: str) -> None:
        path = self._path(prefix)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)


class ObjectFiles:
    """The deployment's object storage. `loop` is the engine's running event loop, to which the
    storage calls are sent from the threads that use this class; without one (a separate worker
    process) each call runs on a loop of its own."""

    def __init__(
        self,
        storage: Storage,
        loop: asyncio.AbstractEventLoop | None = None,
        product_id: str = PRODUCT_ID,
        timeout_s: float = 300.0,
    ):
        self._storage = storage
        self._loop = loop
        self._product = product_id
        self._timeout = timeout_s

    def for_owner(self, tenant: str, user: str) -> "_OwnedObjects":
        if not tenant or not user:
            raise ValueError("files are kept for a named person")
        return _OwnedObjects(self, tenant, user)

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        if self._loop is not None and self._loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, self._loop).result(self._timeout)
        return asyncio.run(coro)


_OBJECT_SEGMENT = re.compile(r"[^A-Za-z0-9._@=+-]")


def _object_name(key: str) -> str:
    """The key as object storage accepts it: each part limited to letters, digits and `._@=+-` (a
    title with spaces or accents is stored with `_` in their place; the title itself is in the
    database). The same key always gives the same name."""
    parts = []
    for part in _safe(key).split("/"):
        part = _OBJECT_SEGMENT.sub("_", part)
        parts.append(part if re.match(r"[A-Za-z0-9]", part) else f"f{part}")
    return "/".join(parts)


class _OwnedObjects:
    def __init__(self, files: ObjectFiles, tenant: str, user: str):
        self._f = files
        self._owner = (tenant, files._product, user)  # noqa: SLF001

    def _key(self, key: str) -> str:
        return object_key(*self._owner, _object_name(key))

    def put_file(self, key: str, source: Path, content_type: str | None = None) -> None:
        self.put_bytes(key, Path(source).read_bytes(), content_type)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        self._f.run(self._f._storage.put(self._key(key), data, content_type))  # noqa: SLF001

    def read_bytes(self, key: str) -> bytes | None:
        full = self._key(key)
        storage = self._f._storage  # noqa: SLF001

        async def get() -> bytes | None:
            if not await storage.exists(full):
                return None
            return await storage.get(full)

        return self._f.run(get())

    def exists(self, key: str) -> bool:
        return self._f.run(self._f._storage.exists(self._key(key)))  # noqa: SLF001

    @contextmanager
    def local(self, key: str) -> Iterator[Path | None]:
        data = self.read_bytes(key)
        if data is None:
            yield None
            return
        with tempfile.TemporaryDirectory(prefix="notebook-file-") as folder:
            path = Path(folder) / Path(key).name
            path.write_bytes(data)
            yield path

    def local_path(self, key: str) -> Path | None:
        return None

    def delete_prefix(self, prefix: str) -> None:
        full = self._key(prefix)
        storage = self._f._storage  # noqa: SLF001

        async def remove() -> None:
            for found in await storage.list(full):
                if found == full or found.startswith(full + "/"):
                    await storage.delete(found)

        self._f.run(remove())
