"""The person's own provider keys, by product (ADR-0095; amendment of 2026-11-11: keys hold no
model, the model picker's Cloud tab chooses one; ADR-0100: text vendors and three media providers).

Settings › Your keys keeps, for each product, a key for each provider the person uses there. Chat
and writing run on a text vendor: Anthropic (Claude Haiku 5.5, the default), OpenAI, Google Gemini,
DeepSeek, Z.ai or OpenRouter. The media products run on Runware, WaveSpeed and fal.ai: a key saved
under "Every media product" (`media`) serves them all, and a product's own key for the same provider
wins (separate billing). Any one media key is enough (ADR-0100, decision 9). Each key is tested
before it is saved. Keys of providers the app no longer offers (Groq, another
OpenAI-compatible server, and fal.ai, WaveSpeed or Runware for chat) are deleted on the first start
(`_prune`).

The picker's Cloud tab lists the models of every provider with a key for that product
(`own_keys_catalogue.py`); choosing one sets the product's `use`, choosing a model on this computer
clears it. A text `use` names the vendor and its model; a media `use` names the model only, and its
route carries every offer with a key (`KeyRoute.choices`), for the router to pick the cheapest for
each job (`wasifyai_platform_sdk/offers.py`, stage CP3).

A key lives in the secret store as `keys.<product>.<provider>` (the keychain on the desktop,
ADR-0092) and is never answered back, logged or sent anywhere but its provider: the window learns
only whether one is saved and whether it worked.

    OwnKeysService   keys (test, save, check, remove), `use`, the Cloud tab's rows, `route`
    router           `/desktop/keys`, what Settings › Your keys and the pickers call

Chat and every text product follow `route("chat")` (`own_keys_text.py`); images and video theirs in
the media worker (`own_keys_media.py`); speaking, music, lip sync and 3D through `known`
(`own_keys_engines.py`)."""

import logging
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
from wasifyai_platform_sdk.offers import TIE_ORDER, Offer, Price, cheapest_words, order

from wasifyai_api import own_keys_catalogue as catalogue
from wasifyai_api.identity import get_identity
from wasifyai_api.services import services_of
from wasifyai_api.settings_store import SettingsStore

log = logging.getLogger(__name__)

SETTINGS = "own_keys"
FAL_QUEUE = "https://queue.fal.run"
OPENROUTER_TEXT = "https://openrouter.ai/api/v1"
ANTHROPIC_API = "https://api.anthropic.com"
TEST_TIMEOUT_S = 20.0

Kind = Literal["text", "media"]


@dataclass(frozen=True)
class Provider:
    id: str
    title: str
    host: str = ""  # said on the screens: "what you make is sent to <host>"
    text_url: str = ""  # its OpenAI-compatible address, for chat ("" for no chat)
    media_url: str = ""  # its media API, for everything else ("" for none)

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
        # ADR-0100: text on the vendors (Anthropic first: Claude Haiku 5.5 is the default), media
        # on Runware, WaveSpeed and fal.ai; no provider runs the other kind
        Provider("anthropic", "Anthropic", "api.anthropic.com", text_url=f"{ANTHROPIC_API}/v1/"),
        Provider("openai", "OpenAI", "api.openai.com", text_url="https://api.openai.com/v1"),
        Provider(
            "gemini",
            "Google Gemini",
            "generativelanguage.googleapis.com",
            text_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        ),
        Provider("deepseek", "DeepSeek", "api.deepseek.com", text_url="https://api.deepseek.com"),
        Provider("zai", "Z.ai", "api.z.ai", text_url="https://api.z.ai/api/paas/v4"),
        Provider("openrouter", "OpenRouter", "openrouter.ai", text_url=OPENROUTER_TEXT),
        Provider("runware", "Runware", "runware.ai", media_url=RUNWARE_API),
        Provider("wavespeed", "WaveSpeed", "wavespeed.ai", media_url=WAVESPEED_API),
        Provider("fal", "fal.ai", "fal.ai", media_url=FAL_QUEUE),
    )
}
LEGACY_IDS = {"fal_text": "fal"}  # rows saved before 2026-11-11

MEDIA = "media"  # the key row that serves every media product
MEDIA_PROVIDERS = TIE_ORDER  # runware, wavespeed, fal

PRODUCTS = (
    Product("chat", "Chat and writing", "text"),
    Product(MEDIA, "Every media product", "media"),
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
    """The providers a key can be saved for under `product`: those with models for it, of the
    product's kind (text on the vendors, media on Runware, WaveSpeed and fal.ai)."""
    if product.id == MEDIA:
        return list(MEDIA_PROVIDERS)
    if product.kind == "media":  # in the tie order: Runware, WaveSpeed, fal.ai
        return [v for v in MEDIA_PROVIDERS if v in catalogue.providers_of(product.id)]
    return [
        v for v in catalogue.providers_of(product.id)
        if v in PROVIDERS and PROVIDERS[v].url_for(product.kind)
    ]  # fmt: skip


def secret_name(product: str, provider: str) -> str:
    return f"keys.{product}.{provider}"


@dataclass(frozen=True)
class KeyChoice:
    """One offer of a media model that a saved key can run: the provider, its key and address, and
    the offer (endpoint, price, what it can do)."""

    provider: Provider
    key: str
    base_url: str
    offer: Offer


# what a media model can do, as the capabilities the screens ask for: making is always offered, the
# rest by what an offer `can` (stages CP4 and CP5)
MAKES = {"images": "image.generate", "video": "video.generate"}
CAN = {
    "edit": ("image.edit", "image.reference"),
    "mask": ("image.inpaint",),
    "animate": ("video.animate",),
    "extend": ("video.extend",),
}


def capabilities(product: str, offers: list[Offer]) -> list[str]:
    """What the offers a key can run let a product's model do, for its screen to offer."""
    out = [MAKES[product]] if product in MAKES else []
    for o in offers:
        for verb in sorted(o.can):
            out.extend(c for c in CAN.get(verb, ()) if c not in out)
    return out


def offer_of(c: KeyChoice) -> Offer:
    return c.offer


@dataclass(frozen=True)
class KeyRoute:
    """Where a product's requests go while it runs on a cloud model. A text route is its vendor,
    model and key. A media route's `model` is the catalogue's id for the model and `choices` its
    offers with a key, cheapest by list price first; `provider`, `key` and `base_url` are the first
    choice's (the router prices each job and may pick another)."""

    provider: Provider
    model: str
    key: str
    base_url: str
    choices: tuple[KeyChoice, ...] = ()
    title: str = ""

    def offers(self) -> tuple[KeyChoice, ...]:
        """The choices to price for a job; a route without any (an admin's single row on the web)
        is its own one choice, at no known price."""
        if self.choices:
            return self.choices
        unpriced = Offer(self.provider.id, self.model, Price(0.0, "run"))
        return (KeyChoice(self.provider, self.key, self.base_url, unpriced),)


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
    """The OpenAI-compatible client for a text vendor, its key sent as `Bearer`."""
    make = factory or AsyncOpenAI
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


async def try_anthropic(provider: Provider, model: str, key: str, base_url: str) -> Tried:
    """Anthropic's model list: answered for a good key, refused for a bad one; nothing is charged.
    (It does not show whether the account has credits: only a real answer does.)"""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TEST_TIMEOUT_S) as http:
            r = await http.get(
                f"{ANTHROPIC_API}/v1/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            )
    except httpx.HTTPError:
        return Tried(False, _ms(t0), f"{provider.title} could not be reached.")
    return _answer(provider, t0, r)


TEXT_TESTERS: dict[str, Tester] = {"anthropic": try_anthropic}


async def try_vendor(provider: Provider, model: str, key: str, base_url: str) -> Tried:
    """Anthropic's own free check; every other vendor a one-token chat (`try_text`)."""
    return await TEXT_TESTERS.get(provider.id, try_text)(provider, model, key, base_url)


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
        self._testers: dict[Kind, Tester] = testers or {"text": try_vendor, "media": try_media}
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
            migrated = await self._migrate(rows)
            if await self._prune(rows) or migrated:
                await self._store.put(SETTINGS, rows, "desktop")
            self._migrated = True
        return rows

    async def _prune(self, rows: dict[str, dict[str, Any]]) -> bool:
        """Keys of providers no longer offered for a product (ADR-0100: Groq, another
        OpenAI-compatible server, and fal.ai, WaveSpeed or Runware for chat) are deleted from the
        secret store, and a product that ran on one runs on this computer again."""
        changed = False
        for pid, row in rows.items():
            p = BY_ID.get(pid)
            offered = providers_for(p) if p is not None else []
            keys = dict(row.get("keys") or {})
            for prov in [k for k in keys if k not in offered]:
                await self._secrets.delete(secret_name(pid, prov))
                del keys[prov]
                changed = True
                log.info("deleted the saved %s key for %s: no longer offered", prov, pid)
            use = row.get("use") or {}
            text = p is None or p.kind == "text"
            if use and text and use.get("provider") not in keys:
                row.pop("use", None)
                changed = True
            if use and not text and use.get("provider"):  # a media choice saved before CP3
                m = catalogue.media_model(pid, str(use.get("model") or ""))
                if m is None:
                    row.pop("use", None)
                else:
                    row["use"] = {"model": m.model}
                changed = True
            row["keys"] = keys
        # a key in the secret store with no row (saved by an older build) goes too
        for name in await self._secrets.names():
            parts = name.split(".")
            if len(parts) == 3 and parts[0] == "keys":
                p = BY_ID.get(parts[1])
                if p is not None and parts[2] not in providers_for(p):
                    await self._secrets.delete(name)
                    changed = True
        return changed

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
                    "tested_at": row.get("tested_at"),
                }  # fmt: skip
                if row.get("mode") == "key" and model:
                    new["use"] = {"provider": prov, "model": model}
            if old is not None:
                await self._secrets.delete(f"keys.{pid}")
            rows[pid] = new
        return changed

    async def route(self, product: str) -> KeyRoute | None:
        """Where `product` runs now: None for this computer, else its provider, model and key (and,
        for a media model, every offer with a key)."""
        if product in self._routes:
            return self._routes[product]
        p = BY_ID.get(product)
        rows = await self._all()
        use = rows.get(product, {}).get("use") or {}
        found: KeyRoute | None = None
        if p is not None and use and self._secrets.ready:
            found = (
                await self._text_route(p, use) if p.kind == "text"
                else await self._media_route(p, str(use.get("model") or ""))
            )  # fmt: skip
        self._routes[product] = found
        return found

    async def _text_route(self, p: Product, use: dict[str, Any]) -> KeyRoute | None:
        v = PROVIDERS.get(use.get("provider") or "")
        if v is None:
            return None
        key = await self._secrets.get(secret_name(p.id, v.id))
        model = str(use.get("model") or "")
        # a model taken off the list runs on this computer again
        if not key or catalogue.find(p.id, v.id, model) is None:
            return None
        return KeyRoute(v, model, key, v.url_for("text"))

    async def keyed_media(self, product: str) -> dict[str, str]:
        """The media providers with a key that serves `product`, and that key: the product's own,
        else the one saved under "Every media product"."""
        out: dict[str, str] = {}
        if not self._secrets.ready:
            return out
        rows = await self._all()
        for prov in MEDIA_PROVIDERS:
            for owner in (product, MEDIA):
                if prov not in (rows.get(owner, {}).get("keys") or {}):
                    continue
                key = await self._secrets.get(secret_name(owner, prov))
                if key:
                    out[prov] = key
                    break
        return out

    async def _media_route(self, p: Product, model: str) -> KeyRoute | None:
        m = catalogue.media_model(p.id, model)
        if m is None:  # a model taken off the list (LongCat, 2026-11-12): this computer again
            return None
        keys = await self.keyed_media(p.id)
        choices = [
            KeyChoice(PROVIDERS[o.provider], keys[o.provider], PROVIDERS[o.provider].media_url, o)
            for o in m.offers
            if o.provider in keys
        ]
        if not choices:
            return None
        ordered = tuple(x.choice for x in order(choices, offer_of, {}))
        first = ordered[0]
        return KeyRoute(first.provider, m.model, first.key, first.base_url, ordered, m.title)

    @staticmethod
    def _offered(product: str, use: dict[str, Any]) -> bool:
        """`use` names a model still on the list."""
        provider, model = str(use.get("provider") or ""), str(use.get("model") or "")
        p = BY_ID.get(product)
        if p is not None and p.kind == "media":
            return catalogue.media_model(product, model) is not None
        return catalogue.find(product, provider, model) is not None

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
        return (m.title, m.price_words) if m else (model, "")

    @staticmethod
    def _key_rows(row: dict[str, Any], names: set[str], product: str) -> list[dict[str, Any]]:
        keys = []
        for prov, saved in (row.get("keys") or {}).items():
            if secret_name(product, prov) not in names or prov not in PROVIDERS:
                continue
            keys.append({
                "provider": prov, "state": "ok" if saved.get("ok") else "bad",
                "said": saved.get("said") or None, "tested_at": saved.get("tested_at"),
            })  # fmt: skip
        return keys

    @staticmethod
    def _media_keys(
        own: list[dict[str, Any]], shared: list[dict[str, Any]], product: str
    ) -> dict[str, dict[str, Any]]:
        """The media keys that serve `product`, by provider: its own, else the shared one."""
        out = {k["provider"]: {**k, "shared": True} for k in shared}
        out.update({k["provider"]: {**k, "shared": False} for k in own})
        offered = set(catalogue.providers_of(product))
        return {p: k for p, k in out.items() if p in offered}

    @staticmethod
    def _media_offer_row(
        m: catalogue.CloudModel, keyed: dict[str, dict[str, Any]], use: dict[str, Any]
    ) -> dict[str, Any] | None:
        """One media model in the Cloud tab: shown once, priced from the offers a key can run,
        with the provider that would be cheaper if the person had its key."""
        able = [o for o in m.offers if o.provider in keyed]
        if not able:
            return None
        first = order(able, lambda o: o, {})[0].offer
        lowest = order(m.offers, lambda o: o, {})[0].offer
        cheaper = lowest.provider not in keyed and lowest.price.amount < first.price.amount
        v = PROVIDERS[first.provider]
        return {
            "provider": v.id, "provider_title": v.title, "host": v.host, "model": m.model,
            "title": m.title, "about": m.about,
            "price": cheapest_words(able), "speed": m.speed,
            "works": any(keyed[o.provider]["state"] == "ok" for o in able),
            "chosen": use.get("model") == m.model,
            "providers": [x.offer.provider for x in order(able, lambda o: o, {})],
            "cheaper_with": PROVIDERS[lowest.provider].title if cheaper else None,
            "can": capabilities(m.product, able),
        }  # fmt: skip

    async def view(self) -> dict[str, Any]:
        rows = await self._all()
        names = set(await self._secrets.names()) if self._secrets.ready else set()
        shared = self._key_rows(rows.get(MEDIA, {}), names, MEDIA)
        products = []
        for p in PRODUCTS:
            row = rows.get(p.id, {})
            keys = self._key_rows(row, names, p.id)
            use = row.get("use")
            if use and not self._offered(p.id, use):  # a model taken off the list: not in use
                use = None
            if use and p.kind == "text":
                if not any(k["provider"] == use.get("provider") for k in keys):
                    use = None
                else:
                    title, price = self._model_title(p.id, use["provider"], use["model"])
                    use = {**use, "title": title, "price": price}
            elif use:
                m = catalogue.media_model(p.id, str(use.get("model") or ""))
                offer_row = (
                    self._media_offer_row(m, self._media_keys(keys, shared, p.id), use)
                    if m else None
                )  # fmt: skip
                use = (
                    {"provider": offer_row["provider"], "model": offer_row["model"],
                     "title": offer_row["title"], "price": offer_row["price"]}
                    if offer_row else None
                )  # fmt: skip
            products.append({
                "id": p.id, "title": p.title, "kind": p.kind, "providers": providers_for(p),
                "keys": keys, "use": use,
            })  # fmt: skip
        return {
            "products": products,
            "providers": [
                {"id": v.id, "title": v.title, "host": v.host} for v in PROVIDERS.values()
            ],
            "can_save": self._secrets.ready,
        }

    async def cloud(self, product: str) -> dict[str, Any]:
        """The Cloud tab of `product`'s picker: a text vendor's models for each vendor with a key;
        each media model once, when any key that serves the product can run it."""
        p = self._product(product)
        view = await self.view()
        by_id = {x["id"]: x for x in view["products"]}
        row = by_id[p.id]
        use = row["use"] or {}
        models = []
        if p.kind == "text":
            for k in row["keys"]:
                v = PROVIDERS[k["provider"]]
                for m in catalogue.models_of(p.id, v.id):
                    models.append({
                        "provider": v.id, "provider_title": v.title, "host": v.host,
                        "model": m.model, "title": m.title, "about": m.about,
                        "price": m.price_words, "speed": m.speed, "works": k["state"] == "ok",
                        "chosen": use.get("provider") == v.id and use.get("model") == m.model,
                        "providers": [v.id], "cheaper_with": None, "can": [],
                    })  # fmt: skip
            return {"product": p.id, "models": models, "has_keys": bool(row["keys"])}
        keyed = self._media_keys(row["keys"], by_id[MEDIA]["keys"], p.id)
        for m in catalogue.models_of(p.id):
            found = self._media_offer_row(m, keyed, use)
            if found is not None:
                models.append(found)
        return {"product": p.id, "models": models, "has_keys": bool(keyed)}

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
    def _test_model(p: Product, v: Provider) -> str:
        """A model to test the key with: a vendor's model, or a media provider's endpoint."""
        products = [x.id for x in PRODUCTS if x.kind == "media"] if p.id == MEDIA else [p.id]
        for pid in products:
            for m in catalogue.models_of(pid, v.id):
                o = m.offer_of(v.id)
                return o.endpoint if o else m.model
        return ""

    async def _key_for(self, product: str, provider: str, key: str | None) -> str:
        if key and key.strip():
            return key.strip()
        name = secret_name(product, provider)
        saved = await self._secrets.get(name) if self._secrets.ready else None
        if not saved:
            raise OwnKeyRefused("Paste the key first.")
        return saved

    # ---- what the window asks ---------------------------------------------------------------

    async def test(self, product: str, provider: str | None, key: str | None) -> Tried:
        """One small request with the key given (or the one saved). Nothing is saved, nothing is
        charged but a one-token chat for a text vendor other than Anthropic."""
        p = self._product(product)
        v = self._provider(p, provider)
        await self._all()  # old keys pruned first
        base = v.url_for(p.kind)
        name = self._test_model(p, v)
        return await self._testers[p.kind](v, name, await self._key_for(product, v.id, key), base)

    async def save_key(self, product: str, provider: str | None, key: str | None) -> dict[str, Any]:
        """Tested first, and saved only when the provider accepted it."""
        p = self._product(product)
        if not self._secrets.ready:
            raise OwnKeyRefused("This computer has nowhere safe to keep a key.", 409)
        v = self._provider(p, provider)
        tried = await self.test(product, v.id, key)
        if not tried.ok:
            raise OwnKeyRefused(tried.said)
        if key and key.strip():
            await self._secrets.put(secret_name(product, v.id), key.strip())
        row = (await self._all()).get(product, {"keys": {}})
        keys = dict(row.get("keys") or {})
        keys[v.id] = {"ok": True, "said": "", "tested_at": time.time()}
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
        if p.kind == "text" and (row.get("use") or {}).get("provider") == pid:
            new.pop("use", None)
        await self._put(product, new)
        return await self.view()

    async def use(self, product: str, provider: str | None, model: str | None) -> dict[str, Any]:
        """Run `product` on a cloud model (from the picker's Cloud tab), or on this computer
        again (no provider and no model). A media model needs no provider: each job runs on its
        cheapest offer with a key. The keys stay either way."""
        p = self._product(product)
        row = (await self._all()).get(product, {"keys": {}})
        if provider is None and not (model or "").strip():
            new = {k: v for k, v in row.items() if k != "use"}
            await self._put(product, new)
            return await self.cloud(product)
        if p.kind == "media":
            return await self._use_media(p, row, (model or "").strip())
        v = self._provider(p, provider)
        saved = (row.get("keys") or {}).get(v.id)
        names = set(await self._secrets.names()) if self._secrets.ready else set()
        if saved is None or secret_name(p.id, v.id) not in names:
            raise OwnKeyRefused(f"Save a {v.title} key for {p.title.lower()} first.", 409)
        name = (model or "").strip()
        if not name or catalogue.find(p.id, v.id, name) is None:
            raise OwnKeyRefused(f"{v.title} has no {p.title.lower()} model called {name} here.")
        await self._put(product, {**row, "use": {"provider": v.id, "model": name}})
        return await self.cloud(product)

    async def _use_media(self, p: Product, row: dict[str, Any], model: str) -> dict[str, Any]:
        """A media model is chosen, not a provider: each job runs on its cheapest keyed offer."""
        if p.id == MEDIA:
            raise OwnKeyRefused("Choose a model under a product, not under every media product.")
        m = catalogue.media_model(p.id, model) if model else None
        if m is None:
            raise OwnKeyRefused(f"There is no {p.title.lower()} model called {model} here.")
        keyed = await self.keyed_media(p.id)
        if not any(o.provider in keyed for o in m.offers):
            names = " or ".join(PROVIDERS[o.provider].title for o in m.offers)
            raise OwnKeyRefused(f"{m.title} needs a {names} key first.", 409)
        await self._put(p.id, {**row, "use": {"model": m.model}})
        return await self.cloud(p.id)


# ---- routes -----------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop/keys", tags=["desktop"])


class KeyBody(BaseModel):
    key: str | None = Field(None, max_length=500)  # write-only: never answered back


class UseBody(BaseModel):
    provider: str | None = Field(None, max_length=40)  # a text vendor; not needed for media
    model: str | None = Field(None, max_length=200)  # neither: this computer


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
    t = await _do(_service(request).test(product, provider, body.key))
    return {"ok": t.ok, "ms": t.ms, "said": t.said or None}


@router.put("/{product}/keys/{provider}")
async def keys_save(
    product: str, provider: str, body: KeyBody, request: Request,
    _: Identity = Depends(get_identity),
) -> dict[str, Any]:  # fmt: skip
    svc = _service(request)
    return await _do(svc.save_key(product, provider, body.key))  # type: ignore[no-any-return]


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
