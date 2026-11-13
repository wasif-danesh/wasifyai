"""Where the 3D product's files are: pictures, cut-outs, models and thumbnails (ADR-0087, P3).

Two homes behind one interface. `LocalBlobs`: folders beside the SQLite file, in the desktop's
data folder (a `workspace` is the real folder: nothing is copied). `StorageBlobs`: the
deployment's object storage under the person's own prefix, for the web (a `workspace` is a
temporary folder: what a step needs is fetched into it and what it makes is put back). A step that
runs the 3D component works in a `workspace`, the same code on both."""

import asyncio
import re
import shutil
import tempfile
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Response
from fastapi.responses import FileResponse
from wasifyai_platform_sdk import Identity
from wasifyai_platform_sdk.storage import object_key

from wasifyai_model3d.store import Model3dStore

PRODUCT_ID = "wasifyai-model3d"
_ITEM = re.compile(r"[0-9a-f]{32}")
_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def _check(kind: str, item: str, name: str = "x") -> None:
    if kind not in ("inputs", "models") or not _ITEM.fullmatch(item) or not _NAME.fullmatch(name):
        raise ValueError("not a file of this product")


class LocalBlobs:
    """Folders on this computer."""

    local = True

    def __init__(self, store: Model3dStore):
        self._store = store

    def _folder(self, who: Identity | tuple[str, str], kind: str, item: str) -> Path:
        tenant, user = (who.tenant_id, who.user_id) if isinstance(who, Identity) else who
        _check(kind, item)
        return self._store.folder_of(tenant, user, kind, item)

    def local_path(self, identity: Identity, kind: str, item: str, name: str) -> Path | None:
        _check(kind, item, name)
        path = self._folder(identity, kind, item) / name
        return path if path.is_file() else None

    async def put(self, identity: Identity, kind: str, item: str, name: str, data: bytes) -> None:
        _check(kind, item, name)
        folder = self._folder(identity, kind, item)
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((folder / name).write_bytes, data)

    async def get(self, identity: Identity, kind: str, item: str, name: str) -> bytes | None:
        path = self.local_path(identity, kind, item, name)
        return await asyncio.to_thread(path.read_bytes) if path else None

    async def copy(
        self, identity: Identity, kind: str, item: str, name: str, to_item: str, to_name: str
    ) -> bool:
        """A file of an input copied into a model's folder."""
        src = self.local_path(identity, kind, item, name)
        if src is None:
            return False
        dst = self._folder(identity, "models", to_item)
        await asyncio.to_thread(dst.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, src, dst / to_name)
        return True

    async def remove(self, who: Identity | tuple[str, str], kind: str, item: str) -> None:
        await asyncio.to_thread(shutil.rmtree, self._folder(who, kind, item), True)

    @asynccontextmanager
    async def workspace(
        self, identity: Identity, kind: str, item: str, pull: Sequence[str] = (),
        push: Sequence[str] = (),
    ) -> AsyncIterator[Path]:  # fmt: skip
        folder = self._folder(identity, kind, item)
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        yield folder

    async def response(
        self, identity: Identity, kind: str, item: str, name: str, media: str,
        headers: dict[str, str] | None = None,
    ) -> Response:  # fmt: skip
        path = self.local_path(identity, kind, item, name)
        if path is None:
            raise HTTPException(404, "not found")
        return FileResponse(path, media_type=media, headers=headers)


class StorageBlobs:
    """The deployment's object storage, under the person's own prefix."""

    local = False

    def __init__(self, scoped: Any):
        self._s = scoped  # the app's `ScopedStorage`

    @staticmethod
    def _owner(who: Identity | tuple[str, str]) -> tuple[str, str, str]:
        tenant, user = (who.tenant_id, who.user_id) if isinstance(who, Identity) else who
        return tenant, PRODUCT_ID, user

    @staticmethod
    def _rel(kind: str, item: str, name: str) -> str:
        _check(kind, item, name)
        return f"m3d/{kind}/{item}/{name}"

    def local_path(self, identity: Identity, kind: str, item: str, name: str) -> Path | None:
        return None  # nothing on this computer: the web cannot save into a folder

    async def put(self, identity: Identity, kind: str, item: str, name: str, data: bytes) -> None:
        await self._s.put_for(self._owner(identity), self._rel(kind, item, name), data)

    async def get(self, identity: Identity, kind: str, item: str, name: str) -> bytes | None:
        try:
            return bytes(await self._s.get_for(self._owner(identity), self._rel(kind, item, name)))
        except FileNotFoundError:
            return None

    async def copy(
        self, identity: Identity, kind: str, item: str, name: str, to_item: str, to_name: str
    ) -> bool:
        data = await self.get(identity, kind, item, name)
        if data is None:
            return False
        await self.put(identity, "models", to_item, to_name, data)
        return True

    async def remove(self, who: Identity | tuple[str, str], kind: str, item: str) -> None:
        _check(kind, item)
        owner = self._owner(who)
        prefix = object_key(*owner, f"m3d/{kind}/{item}")
        for key in await self._s.backing.list(prefix):
            await self._s.backing.delete(key)

    @asynccontextmanager
    async def workspace(
        self, identity: Identity, kind: str, item: str, pull: Sequence[str] = (),
        push: Sequence[str] = (),
    ) -> AsyncIterator[Path]:  # fmt: skip
        with tempfile.TemporaryDirectory(prefix="wasifyai-m3d-") as tmp:
            folder = Path(tmp)
            for name in pull:
                data = await self.get(identity, kind, item, name)
                if data is not None:
                    await asyncio.to_thread((folder / name).write_bytes, data)
            yield folder
            for name in push:
                path = folder / name
                if path.is_file():
                    await self.put(
                        identity, kind, item, name, await asyncio.to_thread(path.read_bytes)
                    )

    async def response(
        self, identity: Identity, kind: str, item: str, name: str, media: str,
        headers: dict[str, str] | None = None,
    ) -> Response:  # fmt: skip
        data = await self.get(identity, kind, item, name)
        if data is None:
            raise HTTPException(404, "not found")
        return Response(data, media_type=media, headers=headers)
