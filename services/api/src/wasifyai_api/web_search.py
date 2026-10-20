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

from wasifyai_platform_sdk import SecretBox, SecretsUnavailable, UsageRecorder, require_context
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

from wasifyai_api.safeguards import SettingsStore

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


def consent_text(provider_id: str) -> str:
    info = next(p for p in PROVIDERS if p.id == provider_id)
    return (
        f"Searching the web sends your question to {info.sends_to}. The results are read by the "
        "assistant on this computer. You can turn this off in Settings."
    )


class WebService:
    def __init__(
        self,
        store: SettingsStore,
        box: SecretBox | None = None,
        usage: UsageRecorder | None = None,
        *,
        reader: WebReader | None = None,
        duckduckgo: DuckDuckGoProvider | None = None,
    ) -> None:
        self._store = store
        self._box = box
        self.usage = usage
        self._ddg = duckduckgo or DuckDuckGoProvider()  # one object: its spacing is per computer
        self.caps = WebCapabilities(self._provider, reader or WebReader())
        self._lock = asyncio.Lock()

    # ---- what the person chose ------------------------------------------------------------

    async def _state(self) -> dict[str, Any]:
        saved = await self._store.get(KEY)
        s = saved if isinstance(saved, dict) else {}
        provider = s.get("provider") if s.get("provider") in PROVIDER_IDS else DEFAULT_PROVIDER
        raw_keys = s.get("keys")
        keys: dict[str, Any] = raw_keys if isinstance(raw_keys, dict) else {}
        return {
            "provider": provider,
            "consented_for": s.get("consented_for")
            if s.get("consented_for") in PROVIDER_IDS
            else None,
            "keys": {k: v for k, v in keys.items() if k in PROVIDER_IDS and isinstance(v, str)},
        }

    async def status(self) -> dict[str, Any]:
        """What Settings and the chat box show. Never a key, only whether one is saved."""
        s = await self._state()
        return {
            "provider": s["provider"],
            "consented": s["consented_for"] == s["provider"],
            "consent_text": consent_text(s["provider"]),
            "can_save_keys": bool(self._box and self._box.ready),
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
                if self._box is None or not self._box.ready:
                    raise ValueError("Keys cannot be saved on this computer.")
                s["keys"][kid] = self._box.encrypt(value)
            if remove_key is not None:
                s["keys"].pop(remove_key, None)
            if consent is not None:
                s["consented_for"] = s["provider"] if consent else None
            await self._store.put(KEY, s, "window")
        return await self.status()

    async def readiness(self) -> Readiness:
        """Can a search or a read go ahead: allowed by the person, and the service has its key."""
        s = await self._state()
        info = next(p for p in PROVIDERS if p.id == s["provider"])
        if s["consented_for"] != s["provider"]:
            return Readiness.needs_setup(
                "Web search is off. The person can allow it with the Search button in the chat box "
                "or in Settings."
            )
        if info.needs_key and info.id not in s["keys"]:
            return Readiness.needs_setup(f"Add the {info.title} key in Settings.")
        return Readiness.ready()

    # ---- the capability -------------------------------------------------------------------

    async def _provider(self) -> SearchProvider:
        s = await self._state()
        key = ""
        if s["provider"] in s["keys"]:
            try:
                key = self._box.decrypt(s["keys"][s["provider"]]) if self._box else ""
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
