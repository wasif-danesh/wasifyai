"""Object storage behind one interface (rule 10): S3 API (MinIO-compatible servers, S3, GCS)
and Azure Blob through obstore. Keys always start with tenant and product (rule 7):

    {tenant_id}/{product_id}/{user_id}/{relative path}

API and SSE responses carry URLs from `url()`, never file bytes.
"""

import re
from datetime import timedelta
from typing import Any

import obstore
from obstore.store import MemoryStore, S3Store

from wasifyai_platform_sdk.context import require_context

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@=+-]*$")


def _check(parts: list[str]) -> None:
    for p in parts:
        for seg in p.split("/"):
            if not _SEGMENT.match(seg) or seg in (".", ".."):
                raise ValueError(f"invalid object key segment {seg!r}")


def object_key(tenant_id: str, product_id: str, user_id: str, *parts: str) -> str:
    _check([tenant_id, product_id, user_id, *parts])
    return "/".join([tenant_id, product_id, user_id, *parts])


class Storage:
    """Thin wrapper over an obstore store. `signer` signs URLs (may differ from `store` when the
    browser reaches storage through a different host than the cluster does)."""

    def __init__(self, store: Any, signer: Any | None = None, scheme_hint: str = "memory"):
        self._store = store
        self._signer = signer
        self._hint = scheme_hint

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        attrs = {"Content-Type": content_type} if content_type else None
        await obstore.put_async(self._store, key, data, attributes=attrs)

    async def get(self, key: str) -> bytes:
        res = await obstore.get_async(self._store, key)
        return bytes(await res.bytes_async())

    async def exists(self, key: str) -> bool:
        try:
            await obstore.head_async(self._store, key)
            return True
        except FileNotFoundError:
            return False

    async def delete(self, key: str) -> None:
        await obstore.delete_async(self._store, key)

    async def copy(self, src: str, dst: str) -> None:
        await obstore.copy_async(self._store, src, dst)

    async def list(self, prefix: str) -> list[str]:
        out: list[str] = []
        async for batch in obstore.list(self._store, prefix=prefix):
            out += [o["path"] for o in batch]
        return out

    async def url(self, key: str, expires: timedelta = timedelta(hours=1)) -> str:
        if self._signer is None:
            return f"{self._hint}://{key}"
        return await obstore.sign_async(self._signer, "GET", key, expires_in=expires)


class ScopedStorage:
    """Storage scoped to the current run's tenant, product and user. Graphs use relative paths;
    the tenancy prefix is added here and cannot be bypassed."""

    def __init__(self, storage: Storage):
        self._storage = storage

    def _key(self, rel: str) -> str:
        ctx = require_context()
        return object_key(ctx.tenant_id, ctx.product_id, ctx.user_id, rel)

    async def put(self, rel: str, data: bytes, content_type: str | None = None) -> str:
        key = self._key(rel)
        await self._storage.put(key, data, content_type)
        return key

    async def get(self, rel: str) -> bytes:
        return await self._storage.get(self._key(rel))

    async def exists(self, rel: str) -> bool:
        return await self._storage.exists(self._key(rel))

    async def delete(self, rel: str) -> None:
        await self._storage.delete(self._key(rel))

    async def move(self, src_rel: str, dst_rel: str) -> str:
        """Re-key a file within the user's own prefix (copy, then delete the original)."""
        src, dst = self._key(src_rel), self._key(dst_rel)
        await self._storage.copy(src, dst)
        await self._storage.delete(src)
        return dst_rel

    async def url(self, rel: str, expires: timedelta = timedelta(hours=1)) -> str:
        return await self._storage.url(self._key(rel), expires)

    # For code that acts for a named owner without a run context (an upload request, a clean-up
    # task). The owner's prefix is still added here, so a key outside it cannot be built.
    async def put_for(
        self, owner: tuple[str, str, str], rel: str, data: bytes, content_type: str | None = None
    ) -> str:
        key = object_key(*owner, rel)
        await self._storage.put(key, data, content_type)
        return key

    async def delete_for(self, owner: tuple[str, str, str], rel: str) -> None:
        await self._storage.delete(object_key(*owner, rel))


def memory_storage() -> Storage:
    return Storage(MemoryStore())


def s3_storage(
    *,
    bucket: str,
    endpoint: str,
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
    public_endpoint: str = "",
) -> Storage:
    """S3-compatible storage (SeaweedFS in dev and staging, S3 or GCS-interop in the clouds).
    Set `public_endpoint` when browsers reach the server on a different URL than pods do."""

    def make(ep: str) -> S3Store:
        return S3Store(
            bucket,
            endpoint=ep,
            access_key_id=access_key,
            secret_access_key=secret_key,
            region=region,
            client_options={"allow_http": ep.startswith("http://")},
            virtual_hosted_style_request=False,
        )

    store = make(endpoint)
    return Storage(
        store, signer=make(public_endpoint) if public_endpoint else store, scheme_hint="s3"
    )
