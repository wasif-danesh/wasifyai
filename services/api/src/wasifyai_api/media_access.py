"""Media access: which backend runs each product's media capability (ADR-0025).

The product config says what a capability needs (a ComfyUI workflow); the admin may point it at
another backend. Bindings are stored in Postgres, keys encrypted; the worker reads them per job."""

import logging
import time
from collections.abc import Awaitable, Callable
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
    default_backend,
    family,
    validate_config,
)

from wasifyai_api.settings_store import SettingsStore

log = logging.getLogger(__name__)

DEFAULT_BACKEND = "comfyui-local"
CHECKS = "media_checks"  # the last test of each saved row: "Key not working" comes from here
# the rows the API runs itself (ADR-0095, K5): speaking and 3D models, engine workers or fal.ai
API_ROWS = (("wasifyai-voice", "speech.speak"), ("wasifyai-model3d", "model3d.generate"))


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


class CheckView(BaseModel):
    ok: bool
    message: str
    at: float


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
    check: CheckView | None = None  # the last test of the saved row


class MediaList(BaseModel):
    items: list[MediaView]
    backends: list[BackendView]
    secrets_ready: bool  # false: saving an API key is refused until MEDIA_SECRETS_KEY is set


class MediaBindingIn(BaseModel):
    backend: str
    config: dict[str, str] = {}
    api_key: str | None = None  # write-only: encrypted, never returned
    # "Use the key saved for …": another row of the same backend, "<product>/<capability>"
    key_from: str | None = None


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
        checks: SettingsStore | None = None,
        changed: Callable[[str], Awaitable[None]] | None = None,
    ):
        self._checks = checks
        self._changed = changed  # where the API runs a row itself (`AdminProviders.changed`)
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

    async def _all_checks(self) -> dict[str, Any]:
        saved = await self._checks.get(CHECKS) if self._checks is not None else None
        return dict(saved) if isinstance(saved, dict) else {}

    async def _note(self, tenant_id: str, product_id: str, capability: str, out: Any) -> None:
        if self._checks is None:
            return
        rows = await self._all_checks()
        name = f"{tenant_id}/{product_id}/{capability}"
        if out is None:
            rows.pop(name, None)
        else:
            rows[name] = {"ok": out.ok, "message": out.message, "at": time.time()}
        await self._checks.put(CHECKS, rows, "admin")

    def _view(
        self, cap: MediaCapability, b: MediaBinding | None, check: dict[str, Any] | None = None
    ) -> MediaView:
        return MediaView(
            product_id=cap.product_id, capability=cap.capability, workflow=cap.workflow,
            backend=b.backend if b else default_backend(cap.capability),
            source="custom" if b else "default",
            config={k: str(v) for k, v in (b.config if b else {}).items()},
            key_set=bool(b and b.key_set),
            allowed_backends=[s.id for s in backends_for(cap.capability)],
            updated_by=b.updated_by if b else None, updated_at=b.updated_at if b else None,
            check=CheckView(**check) if b and check else None,
        )  # fmt: skip

    async def list(self, tenant_id: str) -> MediaList:
        saved = {(b.product_id, b.capability): b for b in await self._store.list(tenant_id)}
        checks = await self._all_checks()
        items = [
            self._view(
                c, saved.get((c.product_id, c.capability)),
                checks.get(f"{tenant_id}/{c.product_id}/{c.capability}"),
            )
            for c in self._capabilities()
        ]  # fmt: skip
        return MediaList(items=items, backends=backend_views(), secrets_ready=self._box.ready)

    async def get(self, tenant_id: str, product_id: str, capability: str) -> MediaView:
        cap = self._find(product_id, capability)
        checks = await self._all_checks()
        return self._view(
            cap, await self._store.get(tenant_id, product_id, capability),
            checks.get(f"{tenant_id}/{product_id}/{capability}"),
        )  # fmt: skip

    async def _borrowed(self, tenant_id: str, key_from: str, backend: str) -> tuple[str, bool]:
        """The encrypted key of the row `key_from` ("<product>/<capability>"), which must run on
        the same backend: "Use the key saved for …". The key is copied inside the store."""
        product_id, _, capability = key_from.partition("/")
        source = await self._store.get(tenant_id, product_id, capability)
        if source is None or source.backend != backend or source.secret_enc is None:
            raise MediaAccessError("That row has no key saved for this service.")
        return source.secret_enc, True

    async def set(
        self, tenant_id: str, product_id: str, capability: str, new: MediaBindingIn, actor: str
    ) -> MediaView:
        cap = self._find(product_id, capability)
        saved = await self._store.get(tenant_id, product_id, capability)
        keep = saved is not None and saved.backend == new.backend and saved.key_set
        api_key = (new.api_key or "").strip() or None
        borrowed: str | None = None
        if new.key_from and not api_key:
            borrowed, keep = await self._borrowed(tenant_id, new.key_from, new.backend)
        try:
            config = validate_config(new.backend, capability, new.config, api_key, keep)
        except InvalidBackendConfig as exc:
            raise MediaAccessError(str(exc)) from exc
        if borrowed is not None:
            secret: str | None = borrowed
        elif api_key:
            try:
                secret = self._box.encrypt(api_key)
            except SecretsUnavailable as exc:
                raise MediaAccessError(str(exc)) from exc
        else:
            secret = saved.secret_enc if keep and saved else None  # same backend: keep the old key
        binding = MediaBinding(product_id, capability, new.backend, config, secret, actor)
        await self._store.put(tenant_id, binding)
        if secret != (saved.secret_enc if saved else None) or new.backend != (
            saved.backend if saved else None
        ):
            await self._note(tenant_id, product_id, capability, None)  # a new key: not tested yet
        if self._changed is not None:
            await self._changed(tenant_id)
        return await self.get(tenant_id, cap.product_id, cap.capability)

    async def reset(self, tenant_id: str, product_id: str, capability: str) -> MediaView:
        self._find(product_id, capability)
        await self._store.delete(tenant_id, product_id, capability)
        await self._note(tenant_id, product_id, capability, None)
        if self._changed is not None:
            await self._changed(tenant_id)
        return await self.get(tenant_id, product_id, capability)

    async def test(
        self, tenant_id: str, product_id: str, capability: str, proposed: MediaBindingIn | None
    ) -> CheckOutcome:
        """A light check of the saved binding, or of one that is not saved yet."""
        self._find(product_id, capability)
        saved = await self._store.get(tenant_id, product_id, capability)
        if proposed is None:
            backend, config = (
                (saved.backend, saved.config) if saved else (default_backend(capability), {})
            )
            key = self._saved_key(saved)
        else:
            api_key = (proposed.api_key or "").strip() or None
            same = saved is not None and saved.backend == proposed.backend and saved.key_set
            if proposed.key_from and not api_key:
                enc, _ = await self._borrowed(tenant_id, proposed.key_from, proposed.backend)
                api_key = self._decrypt(enc)
            try:
                config = validate_config(
                    proposed.backend, capability, proposed.config, api_key, same
                )
            except InvalidBackendConfig as exc:
                raise MediaAccessError(str(exc)) from exc
            backend, key = proposed.backend, api_key or (self._saved_key(saved) if same else None)
        url = self._video_local_url if capability.startswith("video.") else ""
        out = await check_backend(backend, config, key, url or self._local_url, self._http)
        if proposed is None and saved is not None:  # the saved row: its state in the table
            await self._note(tenant_id, product_id, capability, out)
        return out

    def _saved_key(self, saved: MediaBinding | None) -> str | None:
        if saved is None or saved.secret_enc is None:
            return None
        return self._decrypt(saved.secret_enc)

    def _decrypt(self, token: str) -> str:
        try:
            return self._box.decrypt(token)
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
    products = set(registry.products())
    out += [MediaCapability(product_id=p, capability=c) for p, c in API_ROWS if p in products]
    return out
