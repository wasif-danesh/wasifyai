"""Media access: which backend runs each product's media capability (ADR-0025).

The product config says what a capability needs (a ComfyUI workflow); the admin may point it at
another backend. Bindings are stored in Postgres, keys encrypted; the worker reads them per job."""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel
from wasifyai_platform_sdk import (
    BACKENDS,
    CheckOutcome,
    InvalidBackendConfig,
    MediaBinding,
    MediaBindingStore,
    SecretBox,
    SecretsUnavailable,
    backends_for,
    check_backend,
    family,
    validate_config,
)

log = logging.getLogger(__name__)

DEFAULT_BACKEND = "comfyui-local"


class MediaAccessError(Exception):
    """A request that cannot be accepted; the message is meant for the admin."""


class MediaCapability(BaseModel):
    product_id: str
    capability: str
    workflow: str | None = None


class FieldView(BaseModel):
    name: str
    label: str
    required: bool
    secret: bool
    placeholder: str
    help: str


class BackendView(BaseModel):
    id: str
    label: str
    description: str
    families: list[str]
    fields: list[FieldView]


class MediaView(BaseModel):
    product_id: str
    capability: str
    workflow: str | None
    backend: str
    source: str  # "default" (the product's own ComfyUI workflow) or "custom"
    config: dict[str, str]
    key_set: bool
    allowed_backends: list[str]
    updated_by: str | None
    updated_at: datetime | None


class MediaList(BaseModel):
    items: list[MediaView]
    backends: list[BackendView]
    secrets_ready: bool  # false: saving an API key is refused until MEDIA_SECRETS_KEY is set


class MediaBindingIn(BaseModel):
    backend: str
    config: dict[str, str] = {}
    api_key: str | None = None  # write-only: encrypted, never returned


def backend_views() -> list[BackendView]:
    return [
        BackendView(
            id=b.id, label=b.label, description=b.description, families=sorted(b.families),
            fields=[
                FieldView(
                    name=f.name, label=f.label, required=f.required, secret=f.secret,
                    placeholder=f.placeholder, help=f.help,
                )
                for f in b.fields
            ],
        )
        for b in BACKENDS.values()
    ]  # fmt: skip


class MediaAccess:
    def __init__(
        self,
        store: MediaBindingStore,
        box: SecretBox,
        capabilities: Callable[[], list[MediaCapability]],
        local_url: str,
        http: httpx.AsyncClient | None = None,
        video_local_url: str = "",
    ):
        self._store = store
        self._box = box
        self._capabilities = capabilities
        self._local_url = local_url
        self._video_local_url = video_local_url
        self._http = http

    def _find(self, product_id: str, capability: str) -> MediaCapability:
        for c in self._capabilities():
            if (c.product_id, c.capability) == (product_id, capability):
                return c
        raise MediaAccessError(f"{product_id} has no media capability {capability!r}")

    def _view(self, cap: MediaCapability, b: MediaBinding | None) -> MediaView:
        return MediaView(
            product_id=cap.product_id, capability=cap.capability, workflow=cap.workflow,
            backend=b.backend if b else DEFAULT_BACKEND, source="custom" if b else "default",
            config={k: str(v) for k, v in (b.config if b else {}).items()},
            key_set=bool(b and b.key_set),
            allowed_backends=[s.id for s in backends_for(cap.capability)],
            updated_by=b.updated_by if b else None, updated_at=b.updated_at if b else None,
        )  # fmt: skip

    async def list(self, tenant_id: str) -> MediaList:
        saved = {(b.product_id, b.capability): b for b in await self._store.list(tenant_id)}
        items = [
            self._view(c, saved.get((c.product_id, c.capability))) for c in self._capabilities()
        ]
        return MediaList(items=items, backends=backend_views(), secrets_ready=self._box.ready)

    async def get(self, tenant_id: str, product_id: str, capability: str) -> MediaView:
        cap = self._find(product_id, capability)
        return self._view(cap, await self._store.get(tenant_id, product_id, capability))

    async def set(
        self, tenant_id: str, product_id: str, capability: str, new: MediaBindingIn, actor: str
    ) -> MediaView:
        cap = self._find(product_id, capability)
        saved = await self._store.get(tenant_id, product_id, capability)
        keep = saved is not None and saved.backend == new.backend and saved.key_set
        api_key = (new.api_key or "").strip() or None
        try:
            config = validate_config(new.backend, capability, new.config, api_key, keep)
        except InvalidBackendConfig as exc:
            raise MediaAccessError(str(exc)) from exc
        if api_key:
            try:
                secret: str | None = self._box.encrypt(api_key)
            except SecretsUnavailable as exc:
                raise MediaAccessError(str(exc)) from exc
        else:
            secret = saved.secret_enc if keep and saved else None  # same backend: keep the old key
        binding = MediaBinding(product_id, capability, new.backend, config, secret, actor)
        await self._store.put(tenant_id, binding)
        return await self.get(tenant_id, cap.product_id, cap.capability)

    async def reset(self, tenant_id: str, product_id: str, capability: str) -> MediaView:
        self._find(product_id, capability)
        await self._store.delete(tenant_id, product_id, capability)
        return await self.get(tenant_id, product_id, capability)

    async def test(
        self, tenant_id: str, product_id: str, capability: str, proposed: MediaBindingIn | None
    ) -> CheckOutcome:
        """A light check of the saved binding, or of one that is not saved yet."""
        self._find(product_id, capability)
        saved = await self._store.get(tenant_id, product_id, capability)
        if proposed is None:
            backend, config = (saved.backend, saved.config) if saved else (DEFAULT_BACKEND, {})
            key = self._saved_key(saved)
        else:
            api_key = (proposed.api_key or "").strip() or None
            same = saved is not None and saved.backend == proposed.backend and saved.key_set
            try:
                config = validate_config(
                    proposed.backend, capability, proposed.config, api_key, same
                )
            except InvalidBackendConfig as exc:
                raise MediaAccessError(str(exc)) from exc
            backend, key = proposed.backend, api_key or (self._saved_key(saved) if same else None)
        url = self._video_local_url if capability.startswith("video.") else ""
        return await check_backend(backend, config, key, url or self._local_url, self._http)

    def _saved_key(self, saved: MediaBinding | None) -> str | None:
        if saved is None or saved.secret_enc is None:
            return None
        try:
            return self._box.decrypt(saved.secret_enc)
        except SecretsUnavailable as exc:
            raise MediaAccessError(str(exc)) from exc


def media_capabilities_from(registry: Any, products_dir: Any, env: str) -> list[MediaCapability]:
    """Every ComfyUI-backed capability of every product, from the products' own config."""
    from wasifyai_platform_sdk import load_product_config

    out: list[MediaCapability] = []
    for product_id in registry.products():
        try:
            config = load_product_config(products_dir, product_id, env=env)
        except Exception:
            log.exception("could not read the config of %s", product_id)
            continue
        for name, binding in config.capabilities.items():
            if binding.provider == "comfyui" and family(name) in {"image", "music", "video"}:
                out.append(
                    MediaCapability(
                        product_id=product_id, capability=name, workflow=binding.workflow
                    )
                )
    return out
