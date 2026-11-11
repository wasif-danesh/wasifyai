"""The person's own provider keys, by product (ADR-0095; amendment of 2026-11-11: keys hold no
model, the model picker's Cloud tab chooses one).

Settings › Your keys keeps, for each product, any number of provider keys (fal.ai, WaveSpeed,
Runware and, for chat, the text providers), each tested before it is saved. The picker's Cloud tab
lists the models of every provider with a key for that product (`own_keys_catalogue.py`); choosing
one sets the product's `use`, choosing a model on this computer clears it. A key lives in the
secret store as `keys.<product>.<provider>` (the keychain on the desktop, ADR-0092) and is never
answered back, logged or sent anywhere but its provider: the window learns only whether one is saved
and whether it worked.

    OwnKeysService   keys (test, save, check, remove), `use`, the Cloud tab's rows, `route`
    router           `/desktop/keys`, what Settings › Your keys and the pickers call

Chat and every text product follow `route("chat")` (`own_keys_text.py`); images and video theirs in
the media worker (`own_keys_media.py`); speaking, music, lip sync and 3D through `known`
(`own_keys_engines.py`)."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from openai import (
    APIConnectionError,
    APIStatusError,
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel, Field
from wasifyai_platform_sdk import Identity, SecretStore
from wasifyai_platform_sdk.cloud_queues import RUNWARE_API, WAVESPEED_API

from wasifyai_api import own_keys_catalogue as catalogue
from wasifyai_api.identity import get_identity
from wasifyai_api.services import services_of
from wasifyai_api.settings_store import SettingsStore

SETTINGS = "own_keys"
FAL_QUEUE = "https://queue.fal.run"
# fal.ai's OpenAI-compatible route to OpenRouter's models (its key goes as `Key …`, not `Bearer`)
FAL_TEXT = "https://fal.run/openrouter/router/openai/v1"
WAVESPEED_TEXT = "https://llm.wavespeed.ai/v1"
RUNWARE_TEXT = "https://api.runware.ai/v1"
TEST_TIMEOUT_S = 20.0
COMPATIBLE = "compatible"

Kind = Literal["text", "media"]


@dataclass(frozen=True)
class Provider:
    id: str
    title: str
    host: str = ""  # said on the screens: "what you make is sent to <host>"
    text_url: str = ""  # its OpenAI-compatible address, for chat ("" for no chat, or the person's)
    media_url: str = ""  # its media API, for everything else ("" for none)
    auth: Literal["bearer", "key"] = (
        "bearer"  # how a text key is sent: `Bearer …` or fal.ai's `Key …`
    )

    @property
    def base_url(self) -> str:
        return self.media_url or self.text_url

    def url_for(self, kind: Kind) -> str:
        return self.text_url if kind == "text" else self.media_url


@dataclass(frozen=True)
class Product:
    id: str
    title: str
    kind: Kind


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        Provider("fal", "fal.ai", "fal.ai", FAL_TEXT, FAL_QUEUE, "key"),
        Provider("wavespeed", "WaveSpeed", "wavespeed.ai", WAVESPEED_TEXT, WAVESPEED_API),
        Provider("runware", "Runware", "runware.ai", RUNWARE_TEXT, RUNWARE_API),
        Provider("openrouter", "OpenRouter", "openrouter.ai", "https://openrouter.ai/api/v1"),
        Provider("openai", "OpenAI", "api.openai.com", "https://api.openai.com/v1"),
        Provider("anthropic", "Anthropic", "api.anthropic.com", "https://api.anthropic.com/v1/"),
        Provider(
            "gemini",
            "Google Gemini",
            "generativelanguage.googleapis.com",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ),  # fmt: skip
        Provider("groq", "Groq", "api.groq.com", "https://api.groq.com/openai/v1"),
        Provider(COMPATIBLE, "Another OpenAI-compatible server"),
    )
}
LEGACY_IDS = {"fal_text": "fal"}  # rows saved before 2026-11-11

PRODUCTS = (
    Product("chat", "Chat and writing", "text"),
    Product("images", "Images", "media"),
    Product("video", "Video", "media"),
    Product("voice", "Voice", "media"),
    Product("music", "Music", "media"),
    Product("sfx", "Sound effects", "media"),
    Product("lipsync", "Lip sync", "media"),
    Product("model3d", "3D", "media"),
)
BY_ID = {p.id: p for p in PRODUCTS}


def providers_for(product: Product) -> list[str]:
    """The providers a key can be saved for under `product`: those with models for it."""
    found = catalogue.providers_of(product.id)
    return [*found, COMPATIBLE] if product.kind == "text" else found


def secret_name(product: str, provider: str) -> str:
    return f"keys.{product}.{provider}"


@dataclass(frozen=True)
class KeyRoute:
    """Where a product's requests go while it runs on a cloud model."""

    provider: Provider
    model: str
    key: str
    base_url: str


@dataclass(frozen=True)
class Tried:
    ok: bool
    ms: int
    said: str = ""  # why it did not work, in words; never the key


# (provider, model, key, base_url) -> Tried; the real ones call the provider, tests give fakes
Tester = Callable[[Provider, str, str, str], Awaitable[Tried]]


def said_of(provider: Provider, model: str, e: Exception) -> str | None:
    """What a provider's refusal means, in words; None for an error that is not the provider's."""
    if isinstance(e, AuthenticationError | PermissionDeniedError):
        return f"{provider.title} did not accept the key."
    if isinstance(e, NotFoundError):
        return f"{provider.title} has no model called {model}."
    if isinstance(e, RateLimitError):
        return f"{provider.title} says too many requests. Try again soon."
    if isinstance(e, APIConnectionError):
        return f"{provider.title} could not be reached."
    if isinstance(e, APIStatusError):
        return f"{provider.title} answered {e.status_code}."
    return None


def text_client(
    provider: Provider, base_url: str, key: str, factory: Any = None, **kw: Any
) -> AsyncOpenAI:
    """The OpenAI-compatible client for a text provider, its key sent the way the provider asks."""
    make = factory or AsyncOpenAI
    if provider.auth == "key":  # fal.ai: `Authorization: Key …` in place of the client's `Bearer`
        return make(  # type: ignore[no-any-return]
            base_url=base_url, api_key="unused", default_headers={"Authorization": f"Key {key}"},
            **kw,
        )  # fmt: skip
    return make(base_url=base_url, api_key=key, **kw)  # type: ignore[no-any-return]


async def try_text(provider: Provider, model: str, key: str, base_url: str) -> Tried:
    """One tiny chat (one token) through the OpenAI-compatible client the text provider uses: it
    proves the key, the address and the model together."""
    client = text_client(provider, base_url, key, timeout=TEST_TIMEOUT_S, max_retries=0)
    t0 = time.monotonic()
    try:
        await client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "Say OK."}], max_tokens=1
        )
    except APIConnectionError as e:  # APIStatusError and its kinds, and the connection
        return Tried(False, _ms(t0), said_of(provider, model, e) or "")
    except APIStatusError as e:
        return Tried(False, _ms(t0), said_of(provider, model, e) or "")
    finally:
        await client.close()
    return Tried(True, _ms(t0))


def _answer(provider: Provider, t0: float, r: httpx.Response) -> Tried:
    if r.status_code in (401, 403):
        return Tried(False, _ms(t0), f"{provider.title} did not accept the key.")
    if r.status_code >= 500:
        return Tried(False, _ms(t0), f"{provider.title} answered {r.status_code}.")
    return Tried(True, _ms(t0))


async def try_fal(provider: Provider, model: str, key: str, base_url: str) -> Tried:
    """Asks fal.ai about a request that does not exist: a rejected key answers 401 or 403, an
    accepted one answers that the request is not there. Nothing is made, so nothing is charged.
    (Checked against a fake; checked against fal.ai at release time, backlog A11.)"""
    owner_app = "/".join(model.split("/")[:2])
    url = f"{base_url}/{owner_app}/requests/00000000-0000-0000-0000-000000000000/status"
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TEST_TIMEOUT_S) as http:
            r = await http.get(url, headers={"Authorization": f"Key {key}"})
    except httpx.HTTPError:
        return Tried(False, _ms(t0), f"{provider.title} could not be reached.")
    return _answer(provider, t0, r)


async def try_wavespeed(provider: Provider, model: str, key: str, base_url: str) -> Tried:
    """WaveSpeed's balance: answered for a good key, refused for a bad one; nothing is charged."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TEST_TIMEOUT_S) as http:
            r = await http.get(f"{base_url}/balance", headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError:
        return Tried(False, _ms(t0), f"{provider.title} could not be reached.")
    return _answer(provider, t0, r)


async def try_runware(provider: Provider, model: str, key: str, base_url: str) -> Tried:
    """Runware's `authentication` task: it answers an error for a bad key; nothing is made."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TEST_TIMEOUT_S) as http:
            r = await http.post(base_url, json=[{"taskType": "authentication", "apiKey": key}])
    except httpx.HTTPError:
        return Tried(False, _ms(t0), f"{provider.title} could not be reached.")
    if r.status_code < 400:
        try:
            refused = bool(r.json().get("errors"))
        except ValueError:
            refused = False
        if refused:
            return Tried(False, _ms(t0), f"{provider.title} did not accept the key.")
    return _answer(provider, t0, r)


MEDIA_TESTERS: dict[str, Tester] = {
    "fal": try_fal,
    "wavespeed": try_wavespeed,
    "runware": try_runware,
}


async def try_media(provider: Provider, model: str, key: str, base_url: str) -> Tried:
    return await MEDIA_TESTERS[provider.id](provider, model, key, base_url)


def _ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


class OwnKeyRefused(Exception):
    """A request that cannot be done; `str(e)` is a sentence for the screen."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


class OwnKeysService:
    def __init__(
        self,
        store: SettingsStore,
        secrets: SecretStore,
        testers: dict[Kind, Tester] | None = None,
    ) -> None:
        self._store = store
        self._secrets = secrets
        self._testers: dict[Kind, Tester] = testers or {"text": try_text, "media": try_media}
        # each request asks where to go: the answer is kept until a key or a setting changes
        self._routes: dict[str, KeyRoute | None] = {}
        # the same answers for code that cannot wait (the speech and 3D engines' lists, K4)
        self._known: dict[str, KeyRoute | None] = {}
        self._migrated = False

    # ---- what is saved ---------------------------------------------------------------------

    async def _all(self) -> dict[str, dict[str, Any]]:
        saved = await self._store.get(SETTINGS)
        rows = {k: dict(v) for k, v in saved.items()} if isinstance(saved, dict) else {}
        if not self._migrated and self._secrets.ready:
            if await self._migrate(rows):
                await self._store.put(SETTINGS, rows, "desktop")
            self._migrated = True
        return rows

    async def _migrate(self, rows: dict[str, dict[str, Any]]) -> bool:
        """Rows saved before 2026-11-11 (one key, one provider and one model per product) become a
        key for that provider, and `use` when the product ran on it."""
        changed = False
        for pid, row in list(rows.items()):
            if "keys" in row:
                continue
            changed = True
            new: dict[str, Any] = {"keys": {}}
            prov = LEGACY_IDS.get(row.get("provider") or "", row.get("provider") or "")
            old = await self._secrets.get(f"keys.{pid}")
            if old and prov in PROVIDERS:
                await self._secrets.put(secret_name(pid, prov), old)
                model = str(row.get("model") or "")
                new["keys"][prov] = {
                    "ok": bool(row.get("ok")), "said": row.get("said") or "",
                    "tested_at": row.get("tested_at"), "base_url": row.get("base_url") or "",
                    "model": model if prov == COMPATIBLE else "",
                }  # fmt: skip
                if row.get("mode") == "key" and model:
                    new["use"] = {"provider": prov, "model": model}
            if old is not None:
                await self._secrets.delete(f"keys.{pid}")
            rows[pid] = new
        return changed

    async def route(self, product: str) -> KeyRoute | None:
        """Where `product` runs now: None for this computer, else its provider, model and key."""
        if product in self._routes:
            return self._routes[product]
        p = BY_ID.get(product)
        row = (await self._all()).get(product, {})
        use = row.get("use") or {}
        v = PROVIDERS.get(use.get("provider") or "")
        found: KeyRoute | None = None
        if p is not None and v is not None and self._secrets.ready:
            key = await self._secrets.get(secret_name(product, v.id))
            if key:
                saved = (row.get("keys") or {}).get(v.id) or {}
                base = v.url_for(p.kind) or str(saved.get("base_url") or "")
                found = KeyRoute(v, str(use.get("model") or ""), key, base)
        self._routes[product] = found
        return found

    def known(self, product: str) -> KeyRoute | None:
        """`route` as of the last `warm`: read at start and after every change in Settings."""
        return self._known.get(product)

    async def warm(self) -> None:
        self._known = {p.id: await self.route(p.id) for p in PRODUCTS}

    async def _put(self, product: str, row: dict[str, Any]) -> None:
        self._routes.clear()
        rows = await self._all()
        rows[product] = row
        await self._store.put(SETTINGS, rows, "desktop")
        await self.warm()

    def _model_title(self, product: str, provider: str, model: str) -> tuple[str, str]:
        m = catalogue.find(product, provider, model)
        return (m.title, m.price) if m else (model, "")

    async def view(self) -> dict[str, Any]:
        rows = await self._all()
        names = set(await self._secrets.names()) if self._secrets.ready else set()
        products = []
        for p in PRODUCTS:
            row = rows.get(p.id, {})
            keys = []
            for prov, saved in (row.get("keys") or {}).items():
                if secret_name(p.id, prov) not in names or prov not in PROVIDERS:
                    continue
                keys.append({
                    "provider": prov, "state": "ok" if saved.get("ok") else "bad",
                    "said": saved.get("said") or None, "tested_at": saved.get("tested_at"),
                    "base_url": saved.get("base_url") or None, "model": saved.get("model") or None,
                })  # fmt: skip
            use = row.get("use")
            if use and not any(k["provider"] == use.get("provider") for k in keys):
                use = None
            if use:
                title, price = self._model_title(p.id, use["provider"], use["model"])
                use = {**use, "title": title, "price": price}
            products.append({
                "id": p.id, "title": p.title, "kind": p.kind, "providers": providers_for(p),
                "keys": keys, "use": use,
            })  # fmt: skip
        return {
            "products": products,
            "providers": [
                {"id": v.id, "title": v.title, "host": v.host, "needs_base": v.id == COMPATIBLE}
                for v in PROVIDERS.values()
            ],  # fmt: skip
            "can_save": self._secrets.ready,
        }

    async def cloud(self, product: str) -> dict[str, Any]:
        """The Cloud tab of `product`'s picker: every model of every provider with a key saved."""
        p = self._product(product)
        view = await self.view()
        row = next(x for x in view["products"] if x["id"] == p.id)
        use = row["use"] or {}
        models = []
        for k in row["keys"]:
            v = PROVIDERS[k["provider"]]
            listed = (
                [catalogue.CloudModel(p.id, v.id, k["model"], k["model"], k["base_url"] or "", "")]
                if v.id == COMPATIBLE and k["model"]
                else catalogue.models_of(p.id, v.id)
            )
            for m in listed:
                models.append({
                    "provider": v.id, "provider_title": v.title, "host": v.host,
                    "model": m.model, "title": m.title, "about": m.about, "price": m.price,
                    "works": k["state"] == "ok",
                    "chosen": use.get("provider") == v.id and use.get("model") == m.model,
                })  # fmt: skip
        return {"product": p.id, "models": models, "has_keys": bool(row["keys"])}

    # ---- checking a request ------------------------------------------------------------------

    @staticmethod
    def _product(product: str) -> Product:
        p = BY_ID.get(product)
        if p is None:
            raise OwnKeyRefused("There is no such product.", 404)
        return p

    @staticmethod
    def _provider(p: Product, provider_id: str | None) -> Provider:
        pid = LEGACY_IDS.get(provider_id or "", provider_id or "")
        if pid not in providers_for(p):
            raise OwnKeyRefused(f"That provider has no {p.title.lower()} models in this app.")
        return PROVIDERS[pid]

    @staticmethod
    def _base(p: Product, v: Provider, base_url: str | None) -> str:
        if v.url_for(p.kind):
            return v.url_for(p.kind)
        base = (base_url or "").strip()
        if not base.startswith(("https://", "http://")):
            raise OwnKeyRefused("Give the server's address, starting with https://.")
        return base.rstrip("/")

    @staticmethod
    def _test_model(p: Product, v: Provider, model: str | None) -> str:
        if v.id == COMPATIBLE:
            name = (model or "").strip()
            if not name:
                raise OwnKeyRefused("Name the model the server runs.")
            return name
        listed = catalogue.models_of(p.id, v.id)
        return listed[0].model if listed else ""

    async def _key_for(self, product: str, provider: str, key: str | None) -> str:
        if key and key.strip():
            return key.strip()
        name = secret_name(product, provider)
        saved = await self._secrets.get(name) if self._secrets.ready else None
        if not saved:
            raise OwnKeyRefused("Paste the key first.")
        return saved

    # ---- what the window asks ---------------------------------------------------------------

    async def test(
        self, product: str, provider: str | None, key: str | None, base_url: str | None = None,
        model: str | None = None,
    ) -> Tried:  # fmt: skip
        """One small request with the key given (or the one saved). Nothing is saved, nothing is
        charged but a one-token chat for a text provider."""
        p = self._product(product)
        v = self._provider(p, provider)
        saved = ((await self._all()).get(product, {}).get("keys") or {}).get(v.id) or {}
        base = self._base(p, v, base_url or saved.get("base_url"))
        name = self._test_model(p, v, model or saved.get("model"))
        return await self._testers[p.kind](v, name, await self._key_for(product, v.id, key), base)

    async def save_key(
        self, product: str, provider: str | None, key: str | None, base_url: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        """Tested first, and saved only when the provider accepted it."""
        p = self._product(product)
        if not self._secrets.ready:
            raise OwnKeyRefused("This computer has nowhere safe to keep a key.", 409)
        v = self._provider(p, provider)
        tried = await self.test(product, v.id, key, base_url, model)
        if not tried.ok:
            raise OwnKeyRefused(tried.said)
        if key and key.strip():
            await self._secrets.put(secret_name(product, v.id), key.strip())
        row = (await self._all()).get(product, {"keys": {}})
        keys = dict(row.get("keys") or {})
        keys[v.id] = {
            "ok": True, "said": "", "tested_at": time.time(),
            "base_url": "" if v.url_for(p.kind) else self._base(p, v, base_url),
            "model": (model or "").strip() if v.id == COMPATIBLE else "",
        }  # fmt: skip
        await self._put(product, {**row, "keys": keys})
        return await self.view()

    async def check_key(self, product: str, provider: str) -> dict[str, Any]:
        """Test a saved key and keep the answer (the state "Key not working" comes from here)."""
        p = self._product(product)
        v = self._provider(p, provider)
        row = (await self._all()).get(product, {})
        saved = (row.get("keys") or {}).get(v.id)
        if saved is None:
            raise OwnKeyRefused(f"No {v.title} key is saved for {p.title.lower()}.")
        tried = await self.test(product, v.id, None)
        keys = {**row["keys"], v.id: {**saved, "ok": tried.ok, "said": tried.said,
                                       "tested_at": time.time()}}  # fmt: skip
        await self._put(product, {**row, "keys": keys})
        return await self.view()

    async def remove_key(self, product: str, provider: str) -> dict[str, Any]:
        p = self._product(product)
        pid = LEGACY_IDS.get(provider, provider)
        if self._secrets.ready:
            await self._secrets.delete(secret_name(p.id, pid))
        row = (await self._all()).get(product, {})
        keys = {k: v for k, v in (row.get("keys") or {}).items() if k != pid}
        new: dict[str, Any] = {**row, "keys": keys}
        if (row.get("use") or {}).get("provider") == pid:
            new.pop("use", None)
        await self._put(product, new)
        return await self.view()

    async def use(self, product: str, provider: str | None, model: str | None) -> dict[str, Any]:
        """Run `product` on a cloud model (from the picker's Cloud tab), or on this computer
        again (`provider` None). The keys stay either way."""
        p = self._product(product)
        row = (await self._all()).get(product, {"keys": {}})
        if provider is None:
            new = {k: v for k, v in row.items() if k != "use"}
            await self._put(product, new)
            return await self.cloud(product)
        v = self._provider(p, provider)
        saved = (row.get("keys") or {}).get(v.id)
        names = set(await self._secrets.names()) if self._secrets.ready else set()
        if saved is None or secret_name(p.id, v.id) not in names:
            raise OwnKeyRefused(f"Save a {v.title} key for {p.title.lower()} first.", 409)
        name = (model or "").strip()
        known = (
            name == saved.get("model") if v.id == COMPATIBLE
            else catalogue.find(p.id, v.id, name) is not None
        )  # fmt: skip
        if not name or not known:
            raise OwnKeyRefused(f"{v.title} has no {p.title.lower()} model called {name} here.")
        await self._put(product, {**row, "use": {"provider": v.id, "model": name}})
        return await self.cloud(product)


# ---- routes -----------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop/keys", tags=["desktop"])


class KeyBody(BaseModel):
    key: str | None = Field(None, max_length=500)  # write-only: never answered back
    base_url: str | None = Field(None, max_length=500)  # another OpenAI-compatible server only
    model: str | None = Field(None, max_length=200)  # another OpenAI-compatible server only


class UseBody(BaseModel):
    provider: str | None = Field(None, max_length=40)  # None: this computer
    model: str | None = Field(None, max_length=200)


def _service(request: Request) -> OwnKeysService:
    svc = getattr(services_of(request), "own_keys", None)
    if svc is None:
        raise HTTPException(404, "Own keys are not available here.")
    return svc


async def _do(work: Awaitable[Any]) -> Any:
    try:
        return await work
    except OwnKeyRefused as e:
        raise HTTPException(e.status, str(e)) from None


@router.get("")
async def keys_view(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return await _service(request).view()


@router.get("/{product}/cloud")
async def keys_cloud(
    product: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    return await _do(_service(request).cloud(product))  # type: ignore[no-any-return]


@router.put("/{product}/use")
async def keys_use(
    product: str, body: UseBody, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    return await _do(_service(request).use(product, body.provider, body.model))  # type: ignore[no-any-return]


@router.post("/{product}/keys/{provider}/test")
async def keys_test(
    product: str, provider: str, body: KeyBody, request: Request,
    _: Identity = Depends(get_identity),
) -> dict[str, Any]:  # fmt: skip
    t = await _do(_service(request).test(product, provider, body.key, body.base_url, body.model))
    return {"ok": t.ok, "ms": t.ms, "said": t.said or None}


@router.put("/{product}/keys/{provider}")
async def keys_save(
    product: str, provider: str, body: KeyBody, request: Request,
    _: Identity = Depends(get_identity),
) -> dict[str, Any]:  # fmt: skip
    svc = _service(request)
    return await _do(svc.save_key(product, provider, body.key, body.base_url, body.model))  # type: ignore[no-any-return]


@router.post("/{product}/keys/{provider}/check")
async def keys_check(
    product: str, provider: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    return await _do(_service(request).check_key(product, provider))  # type: ignore[no-any-return]


@router.delete("/{product}/keys/{provider}")
async def keys_remove(
    product: str, provider: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    return await _do(_service(request).remove_key(product, provider))  # type: ignore[no-any-return]
