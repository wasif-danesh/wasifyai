"""Speech and 3D models on the provider the admin chose (ADR-0095, stage K5).

On the web people bring no keys: the admin sets each product's media in Admin › Media. Pictures and
clips are jobs, so the media worker reads their row per job. Speaking and 3D models are run by the
API, through `KeyedSpeechEngine` and `KeyedModel3d`; this is where they ask whether the admin put
"Voice · Speak" or "3D · Make a model" on fal.ai, and with which model and key.

The products ask synchronously, so the answer for each tenant is kept here: read at start, again
when the admin saves a row (on this replica at once) and every `refresh_s` (on the others)."""

import asyncio
import logging
from typing import Any

from wasifyai_platform_sdk import FAL, FAL_QUEUE, MediaBindingStore, SecretBox, SecretsUnavailable

from wasifyai_api.logging import tenant_id as current_tenant
from wasifyai_api.own_keys import PROVIDERS, KeyRoute

log = logging.getLogger(__name__)

# the rows of Admin › Media that the API runs, by the name the keyed engines ask with
ROWS = {
    "voice": ("wasifyai-voice", "speech.speak"),
    "model3d": ("wasifyai-model3d", "model3d.generate"),
}


class AdminProviders:
    def __init__(
        self,
        store: MediaBindingStore,
        box: SecretBox,
        default_tenant: str,
        refresh_s: float = 30.0,
    ):
        self._store = store
        self._box = box
        self._default = default_tenant
        self._refresh_s = refresh_s
        self._known: dict[str, dict[str, KeyRoute | None]] = {}

    def _tenant(self) -> str:
        t = current_tenant.get()
        return self._default if t in ("", "-") else t

    def known(self, product: str) -> KeyRoute | None:
        tenant = self._tenant()
        if tenant not in self._known:
            self._known[tenant] = {}  # read by the next refresh; the engine workers until then
        return self._known[tenant].get(product)

    async def route(self, product: str) -> KeyRoute | None:
        tenant = self._tenant()
        await self.refresh(tenant)
        return self._known[tenant].get(product)

    async def refresh(self, tenant: str) -> None:
        routes: dict[str, KeyRoute | None] = {}
        for product, (product_id, capability) in ROWS.items():
            routes[product] = await self._read(tenant, product_id, capability)
        self._known[tenant] = routes

    async def _read(self, tenant: str, product_id: str, capability: str) -> KeyRoute | None:
        b = await self._store.get(tenant, product_id, capability)
        if b is None or b.backend != FAL or b.secret_enc is None:
            return None
        try:
            key = self._box.decrypt(b.secret_enc)
        except SecretsUnavailable:
            log.error("the fal.ai key of %s/%s is unreadable", product_id, capability)
            return None
        return KeyRoute(PROVIDERS["fal"], str(b.config.get("model") or ""), key, FAL_QUEUE)

    async def run(self) -> None:
        """Keep every tenant asked about current: the admin may save on another replica."""
        while True:
            for tenant in {self._default, *self._known}:
                try:
                    await self.refresh(tenant)
                except Exception:  # the database is away: keep the last answer
                    log.warning("could not read the admin's media rows", exc_info=True)
            await asyncio.sleep(self._refresh_s)

    def changed(self, tenant: str) -> Any:
        """What Admin › Media calls after a save or a reset (an awaitable)."""
        return self.refresh(tenant)
