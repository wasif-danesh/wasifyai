"""Web search and reading for the assistant (ADR-0083, stage CO3): the person's choices and the
engine's side of `caps.web`.

    WebService     which search service is used, whether the person allowed it, and the keys of
                   the services that need one (kept encrypted); `search` and `read` for the host
    load_or_create_key   the key that keeps those keys encrypted on this computer

DuckDuckGo is the default and needs no account. Ollama, Tavily, Exa and Brave Search work with the
person's own key (`web.PROVIDERS` says what each is). **Nothing is sent until the person has
allowed searching with the service named to them** (the consent is for that service: choosing
another asks again), and the choice can be turned off. The keys are encrypted at rest with a key
file in the app's data folder (mode 0600): they are not shown again, but anyone who can read that
folder as this user can use them (the operating system's keychain is the better place and is a
later step). Queries and pages are not logged and not stored beyond the conversation."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import (
    SecretBox,
    SecretStore,
    SecretsUnavailable,
    UsageRecorder,
    require_context,
)
from wasifyai_platform_sdk.actions import Readiness
from wasifyai_platform_sdk.usage import UsageEvent, record_safely
from wasifyai_platform_sdk.web import (
    PROVIDER_IDS,
    PROVIDERS,
    DuckDuckGoProvider,
    SearchProvider,
    SearchResponse,
    WebCapabilities,
    WebError,
    WebPage,
    WebReader,
    make_provider,
)

from wasifyai_api.settings_store import SettingsStore

log = logging.getLogger(__name__)

KEY = "web.search"
DEFAULT_PROVIDER = "duckduckgo"
WEB_SEARCH_USAGE = "web.search"
WEB_READ_USAGE = "web.read"
MIN_KEY, MAX_KEY = 8, 300


def load_or_create_key(path: Path) -> str:
    """The key that encrypts the saved search keys: read from the file, or made once and kept
    readable by this user only."""
    try:
        return path.read_text().strip()
    except OSError:
        pass
    key = SecretBox.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key)
    return key


def consent_text(provider_id: str, hosted: bool = False) -> str:
    info = next(p for p in PROVIDERS if p.id == provider_id)
    if hosted:
        return (
            f"Searching the web sends your question to {info.sends_to}, from this service. The "
            "results are read by the assistant. You can turn this off with the Search button."
        )
    return (
        f"Searching the web sends your question to {info.sends_to}. The results are read by the "
        "assistant on this computer. You can turn this off in Settings."
    )


class WebService:
    def __init__(
        self,
        store: SettingsStore,
        secrets: SecretStore | None = None,
        usage: UsageRecorder | None = None,
        *,
        reader: WebReader | None = None,
        duckduckgo: DuckDuckGoProvider | None = None,
        per_person: bool = False,
        legacy_box: SecretBox | None = None,
    ) -> None:
        # on a service (`per_person`) an admin chooses the service and keeps the keys, and each
        # person allows searching for themself; on the desktop the one person does all of it.
        # Keys live in the secret store as `web.search.<service>` (ADR-0092); `legacy_box` reads
        # the ones saved inside the settings row before the store existed, once, to move them.
        self.per_person = per_person
        self._store = store
        self._secrets = secrets
        self._legacy_box = legacy_box
        self.usage = usage
        self._ddg = duckduckgo or DuckDuckGoProvider()  # one object: its spacing is per computer
        self.caps = WebCapabilities(self._provider, reader or WebReader())
        self._lock = asyncio.Lock()

    # ---- what the person chose ------------------------------------------------------------

    @staticmethod
    def _who_key(who: Any) -> str | None:
        """Who a consent belongs to: the identity given, or the person whose run this is."""
        if who is None:
            try:
                who = require_context()
            except RuntimeError:
                return None
        return f"{KEY}.consent:{who.tenant_id}:{who.user_id}"

    async def _consented_for(self, s: dict[str, Any], who: Any) -> str | None:
        if not self.per_person:
            return s["consented_for"]
        key = self._who_key(who)
        saved = await self._store.get(key) if key else None
        value = saved.get("provider") if isinstance(saved, dict) else None
        return value if value in PROVIDER_IDS else None

    @staticmethod
    def _secret(provider_id: str) -> str:
        return f"{KEY}.{provider_id}"

    async def _key_ids(self) -> set[str]:
        """The services whose key is in the store. Never the keys."""
        if self._secrets is None:
            return set()
        prefix = KEY + "."
        names = await self._secrets.names()
        return {n[len(prefix) :] for n in names if n.startswith(prefix)} & set(PROVIDER_IDS)

    async def _move_legacy(self, s: dict[str, Any]) -> None:
        """Keys saved inside the settings row before the secret store existed move into it,
        once. One that cannot be read with the current key is dropped: enter it again."""
        legacy = s.get("keys")
        if not isinstance(legacy, dict) or not legacy:
            return
        if self._secrets is None or not self._secrets.ready or self._legacy_box is None:
            return
        for kid, token in legacy.items():
            if kid in PROVIDER_IDS and isinstance(token, str):
                try:
                    await self._secrets.put(self._secret(kid), self._legacy_box.decrypt(token))
                except SecretsUnavailable:
                    log.warning("a saved %s key could not be moved to the secret store", kid)
        await self._store.put(KEY, {k: v for k, v in s.items() if k != "keys"}, "window")

    async def _state(self) -> dict[str, Any]:
        saved = await self._store.get(KEY)
        s = saved if isinstance(saved, dict) else {}
        await self._move_legacy(s)
        provider = s.get("provider") if s.get("provider") in PROVIDER_IDS else DEFAULT_PROVIDER
        return {
            "provider": provider,
            "consented_for": s.get("consented_for")
            if s.get("consented_for") in PROVIDER_IDS
            else None,
            "keys": await self._key_ids(),
        }

    def _row(self, s: dict[str, Any]) -> dict[str, Any]:
        """What the settings row keeps: the choices, never a key."""
        return {"provider": s["provider"], "consented_for": s["consented_for"]}

    async def status(self, who: Any = None) -> dict[str, Any]:
        """What Settings and the chat box show. Never a key, only whether one is saved."""
        s = await self._state()
        return {
            "provider": s["provider"],
            "consented": await self._consented_for(s, who) == s["provider"],
            "consent_text": consent_text(s["provider"], self.per_person),
            "can_save_keys": bool(self._secrets and self._secrets.ready),
            "providers": [
                {
                    "id": p.id,
                    "title": p.title,
                    "needs_key": p.needs_key,
                    "key_set": p.id in s["keys"],
                    "key_url": p.key_url,
                    "sends_to": p.sends_to,
                    "note": p.note,
                }
                for p in PROVIDERS
            ],
        }

    async def update(
        self,
        *,
        provider: str | None = None,
        consent: bool | None = None,
        key: tuple[str, str] | None = None,
        remove_key: str | None = None,
        who: Any = None,
    ) -> dict[str, Any]:
        """Change one or more settings; answers the new status. A different provider asks for
        consent again; a key that is not usable is refused in words."""
        async with self._lock:
            s = await self._state()
            if provider is not None:
                if provider not in PROVIDER_IDS:
                    raise ValueError("That is not a search service the app knows.")
                if provider != s["provider"]:
                    s["provider"], s["consented_for"] = provider, None
            if key is not None:
                kid, value = key
                value = value.strip()
                if kid not in PROVIDER_IDS or kid == DEFAULT_PROVIDER:
                    raise ValueError("That search service does not use a key.")
                if not MIN_KEY <= len(value) <= MAX_KEY or any(c.isspace() for c in value):
                    raise ValueError(
                        "That does not look like a key: no spaces, 8 to 300 characters."
                    )
                if self._secrets is None or not self._secrets.ready:
                    raise ValueError("Keys cannot be saved on this computer.")
                await self._secrets.put(self._secret(kid), value)
                s["keys"].add(kid)
            if remove_key is not None and remove_key in s["keys"] and self._secrets is not None:
                await self._secrets.delete(self._secret(remove_key))
                s["keys"].discard(remove_key)
            if consent is not None:
                if self.per_person:
                    mine = self._who_key(who)
                    if mine is None:
                        raise ValueError("Sign in to allow web search.")
                    await self._store.put(
                        mine, {"provider": s["provider"] if consent else None}, "person"
                    )
                else:
                    s["consented_for"] = s["provider"] if consent else None
            await self._store.put(KEY, self._row(s), "window")
        return await self.status(who)

    async def readiness(self, who: Any = None) -> Readiness:
        """Can a search or a read go ahead: allowed by the person, and the service has its key."""
        s = await self._state()
        info = next(p for p in PROVIDERS if p.id == s["provider"])
        if await self._consented_for(s, who) != s["provider"]:
            return Readiness.needs_setup(
                "Web search is off. The person can allow it with the Search button in the chat box"
                + ("." if self.per_person else " or in Settings.")
            )
        if info.needs_key and info.id not in s["keys"]:
            return Readiness.needs_setup(
                f"An admin needs to add the {info.title} key (Admin > Search)."
                if self.per_person
                else f"Add the {info.title} key in Settings."
            )
        return Readiness.ready()

    # ---- the capability -------------------------------------------------------------------

    async def _provider(self) -> SearchProvider:
        s = await self._state()
        key = ""
        if s["provider"] in s["keys"] and self._secrets is not None:
            try:
                key = await self._secrets.get(self._secret(s["provider"])) or ""
            except SecretsUnavailable:
                raise WebError(
                    "needs_key",
                    "The saved key cannot be read any more. Enter it again in Settings.",
                ) from None
        return make_provider(s["provider"], key, self._ddg)

    async def _allowed(self) -> None:
        ready = await self.readiness()
        if ready.state != "ready":
            raise WebError("search_off", ready.step or ready.reason)

    async def search(self, query: str, limit: int = 5) -> SearchResponse:
        await self._allowed()
        found = await self.caps.search(query, limit)
        await self._count(WEB_SEARCH_USAGE, "searches", found.provider)
        return found

    async def read(self, url: str) -> WebPage:
        await self._allowed()
        page = await self.caps.read(url)
        await self._count(WEB_READ_USAGE, "pages", "")
        return page

    async def _count(self, kind: str, unit: str, provider: str) -> None:
        """One usage event per search or read (rule 9). Bounded labels: no query, no address."""
        if self.usage is None:
            return
        try:
            ctx = require_context()
        except RuntimeError:
            return  # outside a run (a test of Settings): nothing to count against
        meta = {"provider": provider} if provider else {}
        await record_safely(self.usage, UsageEvent.for_context(ctx, kind, 1, unit, **meta))
