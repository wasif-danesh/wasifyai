"""The web's cloud models (ADR-0099, ADR-0100 stage CP11): the service's media keys, kept by the
admin in Admin › Media, and the model each product runs on.

The web runs no model of its own. Each tenant has the same keys service the desktop's Settings ›
Your keys uses (`OwnKeysService`), set to `cloud_only`: media products only, a Runware, WaveSpeed or
fal.ai key under "Every media product" (or one product's own), and each product on the model the
admin chose for it, else the first of its catalogue models that a key can run. Each job then goes
to the cheapest offer with a key, as on the desktop.

The tenant's settings and secrets are its own: the settings under `own_keys@<tenant>`, the keys in
the `secrets` table under `tenant-<tenant>.keys.<product>.<provider>`.

Speaking, music, lip sync, 3D and training ask synchronously (`known`), so each tenant's answers
are kept here: read at start, again when the admin saves (on this replica at once) and every
`refresh_s` (on the others). Pictures and clips are jobs: `plan_of` names the offers a job may run
on and where each key is kept, never the key; the media worker reads the key itself."""

import asyncio
import logging
import re
from typing import Any

from wasifyai_platform_sdk import SecretStore, require_context
from wasifyai_platform_sdk.offers import offer_dict

from wasifyai_api.logging import tenant_id as current_tenant
from wasifyai_api.own_keys import KeyRoute, OwnKeysService
from wasifyai_api.settings_store import SettingsStore

log = logging.getLogger(__name__)

# the picture and clip products whose jobs carry their offers, by the product id of the job
JOB_PRODUCTS = {"wasifyai-image": "images", "wasifyai-video": "video"}
LOOKS = "cloud_looks"  # name -> {provider, url, model} of the looks taught on a cloud trainer


def tenant_slug(tenant: str) -> str:
    """A tenant id as a part of a secret's name (lower-case letters, digits and dashes)."""
    slug = re.sub(r"[^a-z0-9-]+", "-", tenant.lower()).strip("-")
    return slug or "default"


class _TenantSettings:
    def __init__(self, store: SettingsStore, tenant: str) -> None:
        self._store = store
        self._suffix = f"@{tenant}"

    async def get(self, key: str) -> object | None:
        return await self._store.get(key + self._suffix)

    async def put(self, key: str, value: object, by: str) -> None:
        await self._store.put(key + self._suffix, value, by)


class _TenantSecrets:
    def __init__(self, secrets: SecretStore, tenant: str) -> None:
        self._secrets = secrets
        self._prefix = f"tenant-{tenant_slug(tenant)}."

    @property
    def ready(self) -> bool:
        return self._secrets.ready

    async def put(self, name: str, value: str) -> None:
        await self._secrets.put(self._prefix + name, value)

    async def get(self, name: str) -> str | None:
        return await self._secrets.get(self._prefix + name)

    async def delete(self, name: str) -> None:
        await self._secrets.delete(self._prefix + name)

    async def names(self) -> list[str]:
        n = len(self._prefix)
        return [x[n:] for x in await self._secrets.names() if x.startswith(self._prefix)]

    def full(self, name: str) -> str:
        """The name in the shared store: what the media worker reads."""
        return self._prefix + name


class AdminProviders:
    """Every tenant's keys service, and the `Routes` the keyed engines ask (by the tenant of the
    request at hand)."""

    cloud_only = True

    def __init__(
        self,
        store: SettingsStore,
        secrets: SecretStore,
        default_tenant: str,
        refresh_s: float = 30.0,
        testers: dict[Any, Any] | None = None,
    ):
        self._store = store
        self._secrets = secrets
        self._default = default_tenant
        self._refresh_s = refresh_s
        self._testers = testers
        self._by_tenant: dict[str, OwnKeysService] = {}
        self._names: dict[str, _TenantSecrets] = {}

    def _tenant(self) -> str:
        t = current_tenant.get()
        if t in ("", "-"):  # a run's own task: the tenant of the run, else the default
            try:
                t = require_context().tenant_id
            except Exception:
                t = self._default
        return t or self._default

    def for_tenant(self, tenant: str | None = None) -> OwnKeysService:
        t = tenant or self._tenant()
        if t not in self._by_tenant:
            secrets = _TenantSecrets(self._secrets, t)
            self._names[t] = secrets
            self._by_tenant[t] = OwnKeysService(
                _TenantSettings(self._store, t), secrets, self._testers, cloud_only=True
            )
        return self._by_tenant[t]

    # ---- `Routes`, for speaking, music, lip sync, 3D and training -------------------------------

    def known(self, product: str) -> KeyRoute | None:
        return self.for_tenant().known(product)

    async def route(self, product: str) -> KeyRoute | None:
        return await self.for_tenant().route(product)

    def __getattr__(self, name: str) -> Any:
        """What else the keyed engines ask (a kept voice, say): the tenant's keys service."""
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.for_tenant(), name)

    # ---- looks taught on a cloud model (CP10 on the web) -----------------------------------------

    async def keep_look(self, name: str, cloud: dict[str, str]) -> None:
        """Where a look taught on a cloud trainer is kept there: filled into the image jobs that
        use it (`looks_of`)."""
        tenant = self._tenant()
        store = _TenantSettings(self._store, tenant)
        kept = await store.get(LOOKS)
        rows = dict(kept) if isinstance(kept, dict) else {}
        rows[name] = dict(cloud)
        await store.put(LOOKS, rows, "training")

    async def looks_of(self, tenant: str, names: list[str]) -> dict[str, dict[str, str]]:
        kept = await _TenantSettings(self._store, tenant).get(LOOKS)
        rows = kept if isinstance(kept, dict) else {}
        return {n: dict(rows[n]) for n in names if isinstance(rows.get(n), dict)}

    # ---- jobs ----------------------------------------------------------------------------------

    async def plan_of(self, tenant: str, product_id: str) -> dict[str, Any] | None:
        """What a picture or clip job carries to the media worker: its model and the offers it may
        run on, each with the name its key is kept under. None: no key can run it."""
        product = JOB_PRODUCTS.get(product_id)
        if product is None:
            return None
        route = await self.for_tenant(tenant).route(product)
        if route is None or not route.choices:
            return None
        names = self._names[tenant]
        return {
            "model": route.model,
            "title": route.title or route.model,
            "offers": [
                {"offer": offer_dict(c.offer), "base_url": c.base_url,
                 "secret": names.full(c.secret)}
                for c in route.choices
            ],
        }  # fmt: skip

    # ---- kept current --------------------------------------------------------------------------

    async def refresh(self, tenant: str) -> None:
        await self.for_tenant(tenant).refresh()

    async def run(self) -> None:
        """Keep every tenant asked about current: the admin may save on another replica."""
        while True:
            for tenant in {self._default, *self._by_tenant}:
                try:
                    await self.refresh(tenant)
                except Exception:  # the database is away: keep the last answer
                    log.warning("could not read the service's media keys", exc_info=True)
            await asyncio.sleep(self._refresh_s)


class CloudPlanSink:
    """The web's media line with each picture or clip job's offers attached (`plan_of`): the media
    worker runs it on the cheapest of them."""

    def __init__(self, sink: Any, providers: AdminProviders) -> None:
        self.sink = sink
        self._providers = providers

    async def submit(self, request: Any) -> None:
        plan = await self._providers.plan_of(request.tenant_id, request.product_id)
        if plan is not None:
            inputs = {**request.inputs, "cloud": plan}
            # a look taught on a cloud trainer is loaded there by its address (CP10)
            names = [str(x.get("name")) for x in inputs.get("loras") or [] if isinstance(x, dict)]
            looks = await self._providers.looks_of(request.tenant_id, names) if names else {}
            if looks:
                inputs["lora_urls"] = {**looks, **(inputs.get("lora_urls") or {})}
            request = request.model_copy(update={"inputs": inputs})
        await self.sink.submit(request)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.sink, name)
