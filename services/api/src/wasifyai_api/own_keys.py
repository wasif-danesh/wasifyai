"""The person's own provider keys, one per product (ADR-0095, stage K1).

A product runs "On this computer" (`here`) or "With my key" (`key`). The key lives in the secret
store as `keys.<product>` (the keychain on the desktop, ADR-0092); the provider, the model and, for
an OpenAI-compatible server, its address are settings beside it. A key is never answered back,
logged or sent anywhere but its provider: the window learns only whether one is saved and whether
it worked.

    OwnKeysService   what each product uses, saving (tested first), testing, copying and removing
    router           `/desktop/keys`, what Settings > Your keys calls

Chat and every text product follow `route("chat")` (K2, `own_keys_text.py`); images and video
theirs in the media worker (K3, `own_keys_media.py`); speaking and 3D through `known` (K4,
`own_keys_engines.py`)."""

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

from wasifyai_api.identity import get_identity
from wasifyai_api.services import services_of
from wasifyai_api.settings_store import SettingsStore

SETTINGS = "own_keys"
FAL_QUEUE = "https://queue.fal.run"
TEST_TIMEOUT_S = 20.0

Kind = Literal["text", "media"]
Mode = Literal["here", "key"]


@dataclass(frozen=True)
class Provider:
    id: str
    title: str
    kind: Kind
    base_url: str = ""  # empty: the person gives the address (an OpenAI-compatible server)
    host: str = ""  # said on the screens: "what you make is sent to <host>"


@dataclass(frozen=True)
class Product:
    id: str
    title: str
    kind: Kind
    models: tuple[str, ...]  # suggestions for the model field, by provider family


TEXT_PROVIDERS = (
    Provider("openrouter", "OpenRouter", "text", "https://openrouter.ai/api/v1", "openrouter.ai"),
    Provider("openai", "OpenAI", "text", "https://api.openai.com/v1", "api.openai.com"),
    Provider(
        "anthropic", "Anthropic", "text", "https://api.anthropic.com/v1/", "api.anthropic.com"
    ),
    Provider(
        "gemini",
        "Google Gemini",
        "text",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "generativelanguage.googleapis.com",
    ),  # fmt: skip
    Provider("groq", "Groq", "text", "https://api.groq.com/openai/v1", "api.groq.com"),
    Provider("compatible", "Another OpenAI-compatible server", "text"),
)
MEDIA_PROVIDERS = (Provider("fal", "fal.ai", "media", FAL_QUEUE, "fal.ai"),)
PROVIDERS = {p.id: p for p in (*TEXT_PROVIDERS, *MEDIA_PROVIDERS)}

TEXT_MODELS = {
    "openrouter": ("openai/gpt-4o-mini", "google/gemini-2.5-flash"),
    "openai": ("gpt-4o-mini", "gpt-4.1"),
    "anthropic": ("claude-sonnet-5-5", "claude-haiku-5-5"),
    "gemini": ("gemini-2.5-flash", "gemini-2.5-pro"),
    "groq": ("llama-3.3-70b-versatile",),
    "compatible": (),
}

PRODUCTS = (
    Product("chat", "Chat and writing", "text", ()),
    Product("images", "Images", "media", ("fal-ai/flux-2",)),
    Product("video", "Video", "media", ("fal-ai/ltx-2/text-to-video/fast",)),
    Product("voice", "Voice", "media", ("fal-ai/kokoro",)),
    Product("model3d", "3D", "media", ("fal-ai/pixal3d",)),
)
BY_ID = {p.id: p for p in PRODUCTS}


def secret_name(product: str) -> str:
    return f"keys.{product}"


@dataclass(frozen=True)
class KeyRoute:
    """Where a product's requests go when it runs with the person's key."""

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


async def try_text(provider: Provider, model: str, key: str, base_url: str) -> Tried:
    """One tiny chat (one token) through the OpenAI-compatible client the text provider uses: it
    proves the key, the address and the model together."""
    client = AsyncOpenAI(base_url=base_url, api_key=key, timeout=TEST_TIMEOUT_S, max_retries=0)
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
    if r.status_code in (401, 403):
        return Tried(False, _ms(t0), f"{provider.title} did not accept the key.")
    if r.status_code >= 500:
        return Tried(False, _ms(t0), f"{provider.title} answered {r.status_code}.")
    return Tried(True, _ms(t0))


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
        self._testers: dict[Kind, Tester] = testers or {"text": try_text, "media": try_fal}
        # each request asks where to go: the answer is kept until a key or a setting changes
        self._routes: dict[str, KeyRoute | None] = {}
        # the same answers for code that cannot wait (the speech and 3D engines' lists, K4)
        self._known: dict[str, KeyRoute | None] = {}

    # ---- what is saved ---------------------------------------------------------------------

    async def _all(self) -> dict[str, dict[str, Any]]:
        saved = await self._store.get(SETTINGS)
        return {k: dict(v) for k, v in saved.items()} if isinstance(saved, dict) else {}

    async def route(self, product: str) -> KeyRoute | None:
        """Where `product` runs now: None for this computer, else its provider, model and key."""
        if product in self._routes:
            return self._routes[product]
        row = (await self._all()).get(product, {})
        found: KeyRoute | None = None
        v = PROVIDERS.get(row.get("provider") or "")
        if row.get("mode") == "key" and v is not None and self._secrets.ready:
            key = await self._secrets.get(secret_name(product))
            if key:
                base = v.base_url or row.get("base_url") or ""
                found = KeyRoute(v, str(row.get("model") or ""), key, base)
        self._routes[product] = found
        return found

    def known(self, product: str) -> KeyRoute | None:
        """`route` as of the last `warm`: read at start and after every change in Settings."""
        return self._known.get(product)

    async def warm(self) -> None:
        self._known = {p.id: await self.route(p.id) for p in PRODUCTS}

    async def _put(self, product: str, row: dict[str, Any] | None) -> None:
        self._routes.clear()
        rows = await self._all()
        if row is None:
            rows.pop(product, None)
        else:
            rows[product] = row
        await self._store.put(SETTINGS, rows, "desktop")
        await self.warm()

    async def view(self) -> dict[str, Any]:
        rows = await self._all()
        names = set(await self._secrets.names()) if self._secrets.ready else set()
        products = []
        for p in PRODUCTS:
            row = rows.get(p.id, {})
            saved = secret_name(p.id) in names
            mode = row.get("mode", "here") if saved else "here"
            products.append({
                "id": p.id, "title": p.title, "kind": p.kind, "mode": mode,
                "provider": row.get("provider"), "model": row.get("model"),
                "base_url": row.get("base_url") or None, "key_saved": saved,
                "state": "here" if mode == "here" else ("ok" if row.get("ok") else "bad"),
                "said": row.get("said") or None, "tested_at": row.get("tested_at"),
                "models": list(p.models),
            })  # fmt: skip
        return {
            "products": products,
            "providers": [
                {
                    "id": v.id,
                    "title": v.title,
                    "kind": v.kind,
                    "host": v.host,
                    "needs_base": not v.base_url,
                    "models": list(TEXT_MODELS.get(v.id, ())),
                }
                for v in PROVIDERS.values()
            ],  # fmt: skip
            "can_save": self._secrets.ready,
        }

    # ---- checking a request ------------------------------------------------------------------

    @staticmethod
    def _product(product: str) -> Product:
        p = BY_ID.get(product)
        if p is None:
            raise OwnKeyRefused("There is no such product.", 404)
        return p

    @staticmethod
    def _provider(p: Product, provider_id: str | None) -> Provider:
        v = PROVIDERS.get(provider_id or "")
        if v is None or v.kind != p.kind:
            raise OwnKeyRefused(f"Choose a provider that can do {p.title.lower()}.")
        return v

    @staticmethod
    def _base(v: Provider, base_url: str | None) -> str:
        if v.base_url:
            return v.base_url
        base = (base_url or "").strip()
        if not base.startswith(("https://", "http://")):
            raise OwnKeyRefused("Give the server's address, starting with https://.")
        return base.rstrip("/")

    async def _key_for(self, product: str, key: str | None) -> str:
        if key and key.strip():
            return key.strip()
        saved = await self._secrets.get(secret_name(product)) if self._secrets.ready else None
        if not saved:
            raise OwnKeyRefused("Paste the key first.")
        return saved

    # ---- what the window asks ---------------------------------------------------------------

    async def test(
        self, product: str, provider: str | None, model: str | None, base_url: str | None,
        key: str | None,
    ) -> Tried:  # fmt: skip
        """One small request with the key given (or the one saved). Nothing is saved."""
        p = self._product(product)
        v = self._provider(p, provider)
        name = (model or "").strip()
        if not name:
            raise OwnKeyRefused("Choose a model.")
        return await self._testers[p.kind](
            v, name, await self._key_for(product, key), self._base(v, base_url)
        )

    async def save(
        self, product: str, mode: Mode, provider: str | None, model: str | None,
        base_url: str | None, key: str | None,
    ) -> dict[str, Any]:  # fmt: skip
        """`here`: the product runs on this computer; a saved key stays until it is removed.
        `key`: tested first, and saved only when the provider accepted it."""
        p = self._product(product)
        rows = await self._all()
        if mode == "here":
            row = rows.get(product, {})
            await self._put(product, {**row, "mode": "here"} if row else None)
            return await self.view()
        if not self._secrets.ready:
            raise OwnKeyRefused("This computer has nowhere safe to keep a key.", 409)
        v = self._provider(p, provider)
        tried = await self.test(product, provider, model, base_url, key)
        if not tried.ok:
            raise OwnKeyRefused(tried.said)
        if key and key.strip():
            await self._secrets.put(secret_name(product), key.strip())
            self._routes.clear()
        await self._put(product, {
            "mode": "key", "provider": v.id, "model": (model or "").strip(),
            "base_url": self._base(v, base_url) if not v.base_url else "", "ok": True, "said": "",
            "tested_at": time.time(),
        })  # fmt: skip
        return await self.view()

    async def check_saved(self, product: str) -> dict[str, Any]:
        """Test what is saved and keep the answer (the state "Key not working" comes from here)."""
        row = (await self._all()).get(product)
        if not row or row.get("mode") != "key":
            raise OwnKeyRefused("This product runs on this computer.")
        tried = await self.test(
            product, row.get("provider"), row.get("model"), row.get("base_url"), None
        )
        await self._put(
            product, {**row, "ok": tried.ok, "said": tried.said, "tested_at": time.time()}
        )
        return await self.view()

    async def copy(self, product: str, source: str) -> dict[str, Any]:
        """ "Use the same key as …": the key is copied inside the store, never through the window.
        Only between products that use the same kind of provider."""
        p, s = self._product(product), self._product(source)
        if p.kind != s.kind:
            raise OwnKeyRefused(f"{s.title} uses another kind of provider.")
        key = await self._secrets.get(secret_name(source)) if self._secrets.ready else None
        if not key:
            raise OwnKeyRefused(f"{s.title} has no key saved.")
        await self._secrets.put(secret_name(product), key)
        self._routes.clear()
        src = (await self._all()).get(source, {})
        row = (await self._all()).get(product, {})
        provider = row.get("provider") or src.get("provider")
        await self._put(product, {**row, "mode": row.get("mode", "here"), "provider": provider})
        return await self.view()

    async def remove(self, product: str) -> dict[str, Any]:
        self._product(product)
        if self._secrets.ready:
            await self._secrets.delete(secret_name(product))
        self._routes.clear()
        await self._put(product, None)
        return await self.view()


# ---- routes -----------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop/keys", tags=["desktop"])


class Choice(BaseModel):
    provider: str | None = Field(None, max_length=40)
    model: str | None = Field(None, max_length=200)
    base_url: str | None = Field(None, max_length=500)
    key: str | None = Field(None, max_length=500)  # write-only: never answered back


class Saving(Choice):
    mode: Mode


class Copying(BaseModel):
    source: str = Field(max_length=40)


def _service(request: Request) -> OwnKeysService:
    svc = getattr(services_of(request), "own_keys", None)
    if svc is None:
        raise HTTPException(404, "Own keys are not available here.")
    return svc


def _http(e: OwnKeyRefused) -> HTTPException:
    return HTTPException(e.status, str(e))


@router.get("")
async def keys_view(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return await _service(request).view()


@router.post("/{product}/test")
async def keys_test(
    product: str, body: Choice, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    try:
        t = await _service(request).test(
            product, body.provider, body.model, body.base_url, body.key
        )
    except OwnKeyRefused as e:
        raise _http(e) from None
    return {"ok": t.ok, "ms": t.ms, "said": t.said or None}


@router.put("/{product}")
async def keys_save(
    product: str, body: Saving, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    try:
        return await _service(request).save(
            product, body.mode, body.provider, body.model, body.base_url, body.key
        )
    except OwnKeyRefused as e:
        raise _http(e) from None


@router.post("/{product}/check")
async def keys_check(
    product: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    try:
        return await _service(request).check_saved(product)
    except OwnKeyRefused as e:
        raise _http(e) from None


@router.post("/{product}/copy")
async def keys_copy(
    product: str, body: Copying, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    try:
        return await _service(request).copy(product, body.source)
    except OwnKeyRefused as e:
        raise _http(e) from None


@router.delete("/{product}")
async def keys_remove(
    product: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    try:
        return await _service(request).remove(product)
    except OwnKeyRefused as e:
        raise _http(e) from None
