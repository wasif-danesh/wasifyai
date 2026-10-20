"""Web access for the assistant (ADR-0083 decision 4, stage CO3): `caps.web.search` and
`caps.web.read`.

    SearchProvider    what a search service is: a query in, titles, addresses and snippets out
    DuckDuckGoProvider, OllamaProvider, TavilyProvider, ExaProvider, BraveProvider
    WebReader         fetch one page safely and take its main text out
    WebCapabilities   the two calls the rest of the engine makes, over a provider chosen per call

Everything that comes back is **untrusted text**: it is quoted to the model as material, never as
instructions (the assistant's prompt says so and its tool results are marked), and a page is never
run or rendered as markup. A search sends the person's question to the provider they chose; the
engine asks for their consent before the first one (`wasifyai_api.web_search`).

`web.read` fetches with an SSRF guard: only http and https on the usual ports, no address
that is not public (loopback, private, link-local, the cloud metadata address) whether it
was typed or came back from a name lookup or a redirect, the connection goes to the address
that was checked, no cookies or
credentials, a size limit and a time limit. Queries and pages are not logged."""

import asyncio
import ipaddress
import re
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

MAX_QUERY_CHARS = 300
MAX_RESULTS = 10
SNIPPET_CHARS = 400
TITLE_CHARS = 200
PAGE_CHARS = 12_000  # what a read hands back: enough to answer from, small enough for the window
PAGE_BYTES = 2_000_000
PAGE_SECONDS = 15.0
MAX_REDIRECTS = 5
ALLOWED_PORTS = (80, 443, 8080, 8443)
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
USER_AGENT = "Mozilla/5.0 (compatible; WasifyAI/1.0; +https://github.com/wasifdanesh/wasifyai)"
# advertisement links some search engines mix into their results
AD_HOSTS = ("bing.com/aclick", "duckduckgo.com/y.js", "googleadservices.com", "doubleclick.net")


class WebError(Exception):
    """A search or a read that could not be done. `message` is a sentence for the person and the
    model; `code` is one of: needs_key, bad_key, limit, search_busy, search_failed, blocked_url,
    read_refused, not_text, unreadable, read_failed."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    site: str


@dataclass(frozen=True)
class WebPage:
    url: str  # what was asked for
    final_url: str  # where it ended up after redirects
    title: str
    text: str
    read_at: str  # ISO, UTC
    truncated: bool = False


# ---- helpers ----------------------------------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_SPACE = re.compile(r"\s+")


def clean(text: object, limit: int) -> str:
    """Text from the outside, made safe to show and to quote: no control characters, one line of
    spaces, cut to `limit`."""
    s = _SPACE.sub(" ", _CONTROL.sub("", str(text or ""))).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def site_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def make_result(title: object, url: object, snippet: object) -> SearchResult | None:
    """One result, or None when it is not something to show: no http(s) address, or an ad."""
    address = str(url or "").strip()
    parts = urlsplit(address)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
        return None
    if any(ad in (parts.hostname + parts.path).lower() for ad in AD_HOSTS):
        return None
    return SearchResult(
        clean(title, TITLE_CHARS) or site_of(address),
        address,
        clean(snippet, SNIPPET_CHARS),
        site_of(address),
    )


def tidy(results: list[SearchResult | None], limit: int) -> list[SearchResult]:
    seen: set[str] = set()
    out: list[SearchResult] = []
    for r in results:
        if r is None or r.url in seen:
            continue
        seen.add(r.url)
        out.append(r)
        if len(out) >= limit:
            break
    return out


# ---- the providers ----------------------------------------------------------------------------


class SearchProvider(Protocol):
    id: str
    title: str

    async def search(self, query: str, max_results: int) -> list[SearchResult]: ...


class DuckDuckGoProvider:
    """DuckDuckGo through the `ddgs` library, which reads its search page (there is no public search
    API). DuckDuckGo answers a burst of automated queries with a bot challenge (measured: one query
    a minute works, a handful in a few seconds does not), so searches are spaced `min_gap_s` apart
    and a refusal is said in words."""

    id = "duckduckgo"
    title = "DuckDuckGo"
    BUSY = (
        "DuckDuckGo gave no results. If searches were made a moment ago it may be limiting them "
        "from this computer: wait a few minutes, or add a search key in Settings."
    )

    def __init__(
        self,
        *,
        min_gap_s: float = 4.0,
        region: str = "wt-wt",
        run: Callable[[str, int], list[dict[str, Any]]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._gap = min_gap_s
        self._region = region
        self._run = run or self._ddgs
        self._sleep = sleep
        self._clock = clock
        self._lock = asyncio.Lock()
        self._last = -1e9

    def _ddgs(self, query: str, n: int) -> list[dict[str, Any]]:
        from ddgs import DDGS

        return DDGS(timeout=15).text(
            query, region=self._region, safesearch="moderate", max_results=n, backend="duckduckgo"
        )

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        async with self._lock:  # one at a time, and not in a burst
            wait = self._gap - (self._clock() - self._last)
            if wait > 0:
                await self._sleep(wait)
            try:
                rows = await asyncio.to_thread(self._run, query, max_results)
            except Exception as exc:
                self._last = self._clock()
                if "No results" in str(exc):
                    raise WebError("search_busy", self.BUSY) from None
                raise WebError(
                    "search_failed",
                    "DuckDuckGo could not be reached. If it keeps failing, add a search key in "
                    "Settings to use another service.",
                ) from None
            self._last = self._clock()
        found = tidy(
            [make_result(r.get("title"), r.get("href"), r.get("body")) for r in rows], max_results
        )
        if rows and not found:
            # measured 2026-10-20: when DuckDuckGo answers with its bot challenge, `ddgs` hands back
            # one row with every field empty instead of an error
            raise WebError("search_busy", self.BUSY)
        return found


class _Keyed:
    """What the providers that need a key share: one HTTP call, and the same words for the same
    failures."""

    id = ""
    title = ""

    def __init__(self, key: str, client: httpx.AsyncClient | None = None) -> None:
        self._key = key.strip()
        self._client = client

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        raise NotImplementedError

    async def _call(self, method: str, url: str, **kw: Any) -> Any:
        if not self._key:
            raise WebError("needs_key", f"Add your {self.title} key in Settings to search with it.")
        try:
            if self._client is not None:
                res = await self._client.request(method, url, **kw)
            else:
                async with httpx.AsyncClient(timeout=15, trust_env=False) as http:
                    res = await http.request(method, url, **kw)
        except httpx.HTTPError:
            raise WebError("search_failed", f"{self.title} could not be reached.") from None
        if res.status_code in (401, 403):
            raise WebError("bad_key", f"{self.title} did not accept the key. Check it in Settings.")
        if res.status_code == 429:
            raise WebError("limit", f"{self.title} says the limit for this key is reached.")
        if res.status_code >= 400:
            raise WebError(
                "search_failed", f"{self.title} answered with an error ({res.status_code})."
            )
        try:
            return res.json()
        except ValueError:
            raise WebError(
                "search_failed", f"{self.title} sent an answer that could not be read."
            ) from None


class OllamaProvider(_Keyed):
    """Ollama's hosted web search (`POST https://ollama.com/api/web_search`, a bearer key from a
    free Ollama account). The question goes to Ollama's servers."""

    id = "ollama"
    title = "Ollama"

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        data = await self._call(
            "POST",
            "https://ollama.com/api/web_search",
            headers={"authorization": f"Bearer {self._key}"},
            json={"query": query, "max_results": max(1, min(max_results, 10))},
        )
        rows = data.get("results") if isinstance(data, dict) else None
        return tidy(
            [make_result(r.get("title"), r.get("url"), r.get("content")) for r in rows or []],
            max_results,
        )


class TavilyProvider(_Keyed):
    """Tavily (`POST https://api.tavily.com/search`, bearer key)."""

    id = "tavily"
    title = "Tavily"

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        data = await self._call(
            "POST",
            "https://api.tavily.com/search",
            headers={"authorization": f"Bearer {self._key}"},
            json={"query": query, "max_results": max_results, "search_depth": "basic"},
        )
        rows = data.get("results") if isinstance(data, dict) else None
        return tidy(
            [make_result(r.get("title"), r.get("url"), r.get("content")) for r in rows or []],
            max_results,
        )


class ExaProvider(_Keyed):
    """Exa (`POST https://api.exa.ai/search`, `x-api-key`). Asks for short highlights, not pages."""

    id = "exa"
    title = "Exa"

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        data = await self._call(
            "POST",
            "https://api.exa.ai/search",
            headers={"x-api-key": self._key},
            json={
                "query": query,
                "type": "auto",
                "numResults": max_results,
                "contents": {"highlights": {"maxCharacters": SNIPPET_CHARS}},
            },
        )
        rows = data.get("results") if isinstance(data, dict) else None
        out: list[SearchResult | None] = []
        for r in rows or []:
            highlights = r.get("highlights")
            snippet = " … ".join(highlights) if isinstance(highlights, list) else r.get("text")
            out.append(make_result(r.get("title"), r.get("url"), snippet))
        return tidy(out, max_results)


class BraveProvider(_Keyed):
    """Brave Search (`GET api.search.brave.com/res/v1/web/search`, `X-Subscription-Token`)."""

    id = "brave"
    title = "Brave Search"

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        data = await self._call(
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            headers={"x-subscription-token": self._key, "accept": "application/json"},
            params={"q": query, "count": max(1, min(max_results, 20)), "safesearch": "moderate"},
        )
        web = data.get("web") if isinstance(data, dict) else None
        rows = web.get("results") if isinstance(web, dict) else None
        return tidy(
            [make_result(r.get("title"), r.get("url"), r.get("description")) for r in rows or []],
            max_results,
        )


@dataclass(frozen=True)
class ProviderInfo:
    """What the Settings screen says about a provider."""

    id: str
    title: str
    needs_key: bool
    key_url: str  # where a person gets a key
    sends_to: str  # who receives the question
    note: str


PROVIDERS: tuple[ProviderInfo, ...] = (
    ProviderInfo(
        "duckduckgo", "DuckDuckGo", False, "",
        "DuckDuckGo",
        "No account needed. DuckDuckGo limits automated searches, so it can say it is busy.",
    ),
    ProviderInfo(
        "ollama", "Ollama", True, "https://ollama.com/settings/keys",
        "Ollama (ollama.com)",
        "Needs a free Ollama account and key.",
    ),
    ProviderInfo(
        "tavily", "Tavily", True, "https://app.tavily.com/home",
        "Tavily (tavily.com)",
        "Free key: 1,000 searches a month, no card.",
    ),
    ProviderInfo(
        "exa", "Exa", True, "https://dashboard.exa.ai/api-keys",
        "Exa (exa.ai)",
        "Free key with a monthly credit, no card.",
    ),
    ProviderInfo(
        "brave", "Brave Search", True, "https://api-dashboard.search.brave.com/app/keys",
        "Brave (search.brave.com)",
        "Free monthly credit, a card is asked for.",
    ),
)  # fmt: skip
PROVIDER_IDS = tuple(p.id for p in PROVIDERS)

KEYED: dict[str, type[_Keyed]] = {
    "ollama": OllamaProvider,
    "tavily": TavilyProvider,
    "exa": ExaProvider,
    "brave": BraveProvider,
}


def make_provider(
    provider_id: str, key: str = "", duckduckgo: DuckDuckGoProvider | None = None
) -> SearchProvider:
    """The provider with this id. DuckDuckGo is one shared object (its spacing is per computer)."""
    if provider_id == "duckduckgo":
        return duckduckgo or DuckDuckGoProvider()
    if provider_id in KEYED:
        return KEYED[provider_id](key)
    raise ValueError(f"unknown search provider {provider_id!r}")


# ---- reading a page ---------------------------------------------------------------------------

Resolver = Callable[[str, int], Awaitable[list[str]]]


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise WebError("read_failed", f"The address {host} could not be found.") from None
    return list(dict.fromkeys(str(i[4][0]) for i in infos))


def is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 is 127.0.0.1
    return ip.is_global and not ip.is_multicast


_NUMERIC = re.compile(r"^[0-9a-fx.]+$", re.I)


def _blocked(why: str) -> WebError:
    return WebError("blocked_url", f"That address is not one the assistant may read ({why}).")


@dataclass
class _Hop:
    scheme: str
    host: str
    port: int
    target: str  # path and query
    ip: str


async def check_url(url: str, resolve: Resolver) -> _Hop:
    """The address this url would be fetched from, or a refusal. Run for every hop of a redirect."""
    if len(url) > 2000:
        raise _blocked("too long")
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise _blocked("only http and https")
    if parts.username or parts.password:
        raise _blocked("it carries a login")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise _blocked("no address")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise _blocked("bad port") from None
    if port not in ALLOWED_PORTS:
        raise _blocked("an unusual port")
    try:
        literal = ipaddress.ip_address(host)
        addresses = [str(literal)]
    except ValueError:
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan")):
            raise _blocked("a local name") from None
        if _NUMERIC.match(host):  # 0x7f.1, 2130706433, 017.0.0.1: a resolver turns them into one
            raise _blocked("an unusual way to write an address") from None
        addresses = await resolve(host, port)
    if not addresses or not all(is_public(a) for a in addresses):
        raise _blocked("it is on this computer or a private network")
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    return _Hop(parts.scheme, host, port, target, addresses[0])


def _charset(content_type: str) -> str:
    m = re.search(r"charset=([\w-]+)", content_type, re.I)
    return m.group(1) if m else "utf-8"


def extract_text(html: str, url: str) -> tuple[str, str]:
    """(title, main text) of a page. Navigation, ads and boilerplate are left out (trafilatura)."""
    import trafilatura

    text = trafilatura.extract(
        html,
        url=url,
        favor_precision=True,
        include_comments=False,
        include_tables=True,
        include_links=False,
    )
    meta = trafilatura.extract_metadata(html, default_url=url)
    return clean(getattr(meta, "title", "") or "", TITLE_CHARS), (text or "").strip()


class WebReader:
    def __init__(
        self,
        *,
        resolve: Resolver = system_resolver,
        client: httpx.AsyncClient | None = None,
        max_bytes: int = PAGE_BYTES,
        max_chars: int = PAGE_CHARS,
        timeout_s: float = PAGE_SECONDS,
    ) -> None:
        self._resolve = resolve
        self._client = client  # tests give a client with a mock transport
        self._max_bytes = max_bytes
        self._max_chars = max_chars
        self._timeout = timeout_s

    async def read(self, url: str) -> WebPage:
        try:
            return await asyncio.wait_for(self._read(url), self._timeout + 5)
        except TimeoutError:
            raise WebError("read_failed", "The page took too long to answer.") from None

    async def _read(self, url: str) -> WebPage:
        current = url.strip()
        client = self._client or httpx.AsyncClient(timeout=self._timeout, trust_env=False)
        try:
            for _ in range(MAX_REDIRECTS + 1):
                hop = await check_url(current, self._resolve)
                # connect to the address that was checked, not to a second lookup of the name
                netloc_ip = f"[{hop.ip}]" if ":" in hop.ip else hop.ip
                default = 443 if hop.scheme == "https" else 80
                port_part = "" if hop.port == default else f":{hop.port}"
                pinned = f"{hop.scheme}://{netloc_ip}{port_part}{hop.target}"
                headers = {
                    "host": hop.host if hop.port == default else f"{hop.host}:{hop.port}",
                    "user-agent": USER_AGENT,
                    "accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
                    "accept-language": "en,*;q=0.5",
                }
                try:
                    async with client.stream(
                        "GET",
                        pinned,
                        headers=headers,
                        extensions={"sni_hostname": hop.host},
                        follow_redirects=False,
                    ) as res:
                        if res.status_code in (301, 302, 303, 307, 308):
                            where = res.headers.get("location")
                            if not where:
                                raise WebError(
                                    "read_failed",
                                    "The page sent you somewhere without saying where.",
                                )
                            current = urljoin(current, where)
                            continue
                        if res.status_code in (401, 403, 429) or res.status_code >= 400:
                            raise WebError(
                                "read_refused",
                                f"The site refused to show this page ({res.status_code}).",
                            )
                        ctype = res.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if ctype and ctype not in TEXT_TYPES:
                            raise WebError(
                                "not_text", f"That address is not a web page of text ({ctype})."
                            )
                        body = bytearray()
                        truncated = False
                        async for chunk in res.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > self._max_bytes:
                                truncated = True
                                del body[self._max_bytes :]
                                break
                        charset = _charset(res.headers.get("content-type", ""))
                except httpx.HTTPError:
                    raise WebError("read_failed", "The page could not be reached.") from None
                try:
                    html = bytes(body).decode(charset, errors="replace")
                except LookupError:
                    html = bytes(body).decode("utf-8", errors="replace")
                title, text = await asyncio.to_thread(extract_text, html, current)
                if len(text) < 80:
                    raise WebError(
                        "unreadable",
                        "The text of this page could not be read (it may need JavaScript to show, "
                        "or be an index of links).",
                    )
                cut = len(text) > self._max_chars
                if cut:
                    text = text[: self._max_chars].rsplit("\n", 1)[0].rstrip()
                return WebPage(
                    url, current, title or site_of(current), text,
                    datetime.now(UTC).isoformat(timespec="seconds"), truncated or cut,
                )  # fmt: skip
            raise WebError("read_failed", "The page sent you around in a circle.")
        finally:
            if self._client is None:
                await client.aclose()


# ---- the capability ---------------------------------------------------------------------------


@dataclass
class SearchResponse:
    provider: str  # the provider's id
    provider_title: str
    results: list[SearchResult] = field(default_factory=list)


class WebCapabilities:
    """`caps.web`: search and read, over the provider the person chose (asked for at each call, so a
    change in Settings is used at once)."""

    def __init__(
        self,
        provider: Callable[[], Awaitable[SearchProvider]],
        reader: WebReader | None = None,
    ) -> None:
        self._provider = provider
        self.reader = reader or WebReader()

    async def search(self, query: str, max_results: int = 5) -> SearchResponse:
        q = clean(query, MAX_QUERY_CHARS)
        if not q:
            raise WebError("search_failed", "There was nothing to search for.")
        provider = await self._provider()
        results = await provider.search(q, max(1, min(max_results, MAX_RESULTS)))
        return SearchResponse(provider.id, provider.title, results)

    async def read(self, url: str) -> WebPage:
        return await self.reader.read(url)
