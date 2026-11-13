# ruff: noqa: E501
# SPDX-License-Identifier: Apache-2.0
"""Where the web keeps the files of training: pictures, clips, thumbnails, samples, adapters and models (docs/train-web-plan.md).

The product's code works with folders on this computer (`item_folder`, `run_folder`, `model_folder`). On the desktop they are
the truth. On the web the truth is **object storage** under the person's own prefix (rules 7 and 10) and a folder is a cache
on the API's disk: `ensure` fetches it when it is not there, `commit` puts what was written into it back, `drop` removes it
from both. The API may restart or be one of several, so a cache is never trusted past one request chain: a folder that has
no `.synced` mark is fetched again."""

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.storage import object_key

PRODUCT_ID = "wasifyai-training"
KINDS = ("items", "runs", "models", "looks")  # looks: what a run published for the video engine
MARK = ".synced"
_ID = re.compile(r"[0-9a-f]{32}")


def _ids(kind: str, item_id: str) -> None:
    if kind not in KINDS or not _ID.fullmatch(item_id):
        raise ValueError("not a file of this product")


class StorageFiles:
    """The web's side: `storage` is the deployment's `Storage` (keys carry the tenant prefix)."""

    def __init__(self, storage: Any, product_id: str = PRODUCT_ID):
        self._storage = storage
        self._product = product_id

    def _prefix(self, tenant: str, user: str, kind: str, item_id: str) -> str:
        _ids(kind, item_id)
        return object_key(tenant, self._product, user, "train", kind, item_id)

    async def ensure(self, tenant: str, user: str, kind: str, item_id: str, folder: Path) -> Path:
        """`folder` holds what storage holds for this item (fetched once; a folder made here is already synced)."""
        if (folder / MARK).is_file():
            return folder
        prefix = self._prefix(tenant, user, kind, item_id)
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        known: dict[str, int] = {}
        for key in await self._storage.list(prefix + "/"):
            rel = key[len(prefix) + 1 :]
            if not rel or ".." in rel or rel.startswith("/"):
                continue
            data = await self._storage.get(key)
            target = folder / rel
            await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(target.write_bytes, data)
            known[rel] = len(data)
        await asyncio.to_thread((folder / MARK).write_text, json.dumps(known))
        return folder

    async def commit(
        self, tenant: str, user: str, kind: str, item_id: str, folder: Path,
        only: tuple[str, ...] | None = None,
    ) -> None:  # fmt: skip
        """Put every new or changed file of `folder` (or of the named sub-folders) into storage."""
        prefix = self._prefix(tenant, user, kind, item_id)
        mark = folder / MARK
        try:
            known: dict[str, int] = json.loads(await asyncio.to_thread(mark.read_text))
        except (OSError, ValueError):
            known = {}
        roots = [folder / name for name in only] if only else [folder]
        for root in roots:
            paths = [root] if root.is_file() else sorted(root.rglob("*")) if root.is_dir() else []
            for path in paths:
                if not path.is_file() or path.name == MARK:
                    continue
                rel = path.relative_to(folder).as_posix()
                size = (await asyncio.to_thread(path.stat)).st_size
                if known.get(rel) == size:
                    continue
                data = await asyncio.to_thread(path.read_bytes)
                await self._storage.put(f"{prefix}/{rel}", data, "application/octet-stream")
                known[rel] = size
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(mark.write_text, json.dumps(known))

    async def drop(self, tenant: str, user: str, kind: str, item_id: str, folder: Path) -> None:
        prefix = self._prefix(tenant, user, kind, item_id)
        for key in await self._storage.list(prefix + "/"):
            await self._storage.delete(key)
        await asyncio.to_thread(shutil.rmtree, folder, True)
