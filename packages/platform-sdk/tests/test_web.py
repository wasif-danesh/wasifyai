"""Web search and reading (ADR-0083, stage CO3): the providers, the guard against fetching what
is not public, the reader, and the spacing of DuckDuckGo."""

import json
from typing import Any

import httpx
import pytest
from wasifyai_platform_sdk.web import (
    BraveProvider,
    DuckDuckGoProvider,
    ExaProvider,
    OllamaProvider,
    TavilyProvider,
    WebCapabilities,
    WebError,
    WebReader,
    check_url,
    is_public,
    make_provider,
    make_result,
)

ARTICLE = (
    "<html><head><title>The fox</title></head><body><nav>Home About Login</nav><article>"
    + "".join(
        f"<p>The red fox is a small wild dog that lives in many countries, sentence {n}.</p>"
        for n in range(30)
    )
    + "</article><footer>cookies</footer></body></html>"
)


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---- results -----------------------------------------------------------------------------------


def test_a_result_is_text_with_an_http_address_and_advertisements_are_left_out():
    ok = make_result("  The   fox \n", "https://www.example.com/fox", "A  fox\x00 is small")
    assert ok is not None and (ok.title, ok.snippet, ok.site) == (
        "The fox",
        "A fox is small",
        "example.com",
    )
    for bad in (
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://x.test/a",
        "/relative",
        "",
        None,
        "https://user:pw@example.com/",
        "https://www.bing.com/aclick?ld=abc",
        "https://duckduckgo.com/y.js?ad=1",
    ):
        assert make_result("t", bad, "s") is None, bad


# ---- the providers (their requests and answers; no real service is called) -----------------------


async def test_ollama_asks_with_a_bearer_key_and_reads_title_url_content():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Fox", "url": "https://a.test/fox", "content": "Foxes are small."},
                    {"title": "Ad", "url": "javascript:x", "content": "no"},
                ]
            },
        )

    p = OllamaProvider("k-1", client_for(handler))
    out = await p.search("fox", 5)
    assert [(r.title, r.url, r.snippet) for r in out] == [
        ("Fox", "https://a.test/fox", "Foxes are small.")
    ]
    assert str(seen[0].url) == "https://ollama.com/api/web_search"
    assert seen[0].headers["authorization"] == "Bearer k-1"
    assert json.loads(seen[0].content) == {"query": "fox", "max_results": 5}


async def test_tavily_exa_and_brave_use_their_own_endpoints_and_headers():
    calls: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        calls[host] = request
        if host == "api.tavily.com":
            return httpx.Response(
                200, json={"results": [{"title": "T", "url": "https://t.test/1", "content": "c"}]}
            )
        if host == "api.exa.ai":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"title": "E", "url": "https://e.test/1", "highlights": ["one", "two"]}
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "web": {"results": [{"title": "B", "url": "https://b.test/1", "description": "d"}]}
            },
        )

    c = client_for(handler)
    t = await TavilyProvider("tvly-1", c).search("q", 3)
    e = await ExaProvider("exa-1", c).search("q", 3)
    b = await BraveProvider("brv-1", c).search("q", 3)
    assert (t[0].title, e[0].snippet, b[0].snippet) == ("T", "one … two", "d")
    assert calls["api.tavily.com"].headers["authorization"] == "Bearer tvly-1"
    assert json.loads(calls["api.tavily.com"].content)["max_results"] == 3
    assert calls["api.exa.ai"].headers["x-api-key"] == "exa-1"
    assert json.loads(calls["api.exa.ai"].content)["numResults"] == 3
    assert calls["api.search.brave.com"].headers["x-subscription-token"] == "brv-1"
    assert calls["api.search.brave.com"].url.params["q"] == "q"
    assert calls["api.search.brave.com"].url.params["count"] == "3"


@pytest.mark.parametrize(
    ("status", "code"), [(401, "bad_key"), (403, "bad_key"), (429, "limit"), (500, "search_failed")]
)
async def test_a_keyed_provider_says_in_words_what_went_wrong(status, code):
    p = TavilyProvider("k", client_for(lambda r: httpx.Response(status, json={})))
    with pytest.raises(WebError) as e:
        await p.search("q", 3)
    assert e.value.code == code and "Tavily" in e.value.message


async def test_no_key_is_asked_for_before_anything_is_sent():
    def boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing may be sent without a key")

    with pytest.raises(WebError) as e:
        await BraveProvider("  ", client_for(boom)).search("q", 3)
    assert e.value.code == "needs_key" and "Settings" in e.value.message


async def test_a_network_failure_is_a_sentence_not_a_traceback():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(WebError) as e:
        await ExaProvider("k", client_for(down)).search("q", 3)
    assert e.value.code == "search_failed"


async def test_duckduckgo_spaces_searches_and_says_when_it_is_limiting_them():
    waits: list[float] = []
    now = [1000.0]

    async def sleep(s: float) -> None:
        waits.append(round(s, 2))
        now[0] += s

    answers: list[Any] = [
        [{"title": "Fox", "href": "https://a.test/fox", "body": "Foxes."}],
        Exception("No results found."),
        Exception("boom"),
        [{"title": "", "href": "", "body": ""}],  # what a bot challenge looks like through ddgs
    ]

    def run(query: str, n: int) -> list[dict[str, Any]]:
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    p = DuckDuckGoProvider(min_gap_s=4.0, run=run, sleep=sleep, clock=lambda: now[0])
    first = await p.search("fox", 5)
    assert [r.title for r in first] == ["Fox"] and waits == []
    now[0] += 1.0  # asked again a second later: it waits for the rest of the gap
    with pytest.raises(WebError) as busy:
        await p.search("fox again", 5)
    assert waits == [3.0] and busy.value.code == "search_busy"
    assert "wait a few minutes" in busy.value.message
    with pytest.raises(WebError) as other:
        await p.search("third", 5)
    assert other.value.code == "search_failed"
    with pytest.raises(WebError) as challenged:
        await p.search("fourth", 5)
    assert challenged.value.code == "search_busy"  # an empty row is a refusal, not "nothing found"


def test_a_provider_is_made_by_its_id_and_an_unknown_one_is_refused():
    assert make_provider("duckduckgo").id == "duckduckgo"
    assert make_provider("tavily", "k").id == "tavily"
    with pytest.raises(ValueError):
        make_provider("nope")


async def test_the_capability_searches_with_the_provider_chosen_at_each_call():
    chosen = [make_provider("tavily", "k")]

    async def which():
        return chosen[0]

    class Fake:
        id, title = "fake", "Fake"

        async def search(self, q: str, n: int):
            return [make_result(q, "https://f.test/" + q, "s")]

    caps = WebCapabilities(which)
    chosen[0] = Fake()  # type: ignore[assignment]  # changed in Settings between two calls
    out = await caps.search("  fox\x00 ", 3)
    assert out.provider == "fake" and out.results[0].title == "fox"
    with pytest.raises(WebError):
        await caps.search("   ", 3)


# ---- the guard ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "100.64.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "224.0.0.1",
        "not an address",
    ],
)
def test_addresses_that_are_not_public_are_not(address):
    assert is_public(address) is False


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are_public(address):
    assert is_public(address) is True


async def resolve_to(*addresses: str):
    async def r(host: str, port: int) -> list[str]:
        return list(addresses)

    return r


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/a",
        "javascript:alert(1)",
        "gopher://example.com",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/",
        "http://0x7f.0.0.1/",
        "http://localhost/",
        "http://printer.local/",
        "http://service.internal/",
        "https://user:pass@example.com/",
        "http://example.com:22/",
        "http://example.com:6379/",
        "http:///nohost",
        "http://" + "a" * 2100,
    ],
)
async def test_what_is_not_a_public_web_address_is_refused_before_anything_is_fetched(url):
    async def public(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    with pytest.raises(WebError) as e:
        await check_url(url, public)
    assert e.value.code == "blocked_url"


async def test_a_name_that_resolves_to_a_private_address_is_refused_even_among_public_ones():
    async def tricky(host: str, port: int) -> list[str]:
        return ["93.184.216.34", "10.0.0.8"]

    with pytest.raises(WebError):
        await check_url("https://rebind.example.com/", tricky)
    ok = await check_url("https://example.com:8443/a/b?c=d", await resolve_to("93.184.216.34"))
    assert (ok.scheme, ok.host, ok.port, ok.target, ok.ip) == (
        "https",
        "example.com",
        8443,
        "/a/b?c=d",
        "93.184.216.34",
    )


# ---- the reader ---------------------------------------------------------------------------------


def reader(handler, **kw) -> WebReader:
    async def public(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    return WebReader(resolve=public, client=client_for(handler), **kw)


async def test_a_page_is_read_as_its_main_text_with_its_title_and_the_time():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, text=ARTICLE
        )

    page = await reader(handler).read("https://example.com/fox")
    assert page.title == "The fox" and "red fox is a small wild dog" in page.text
    assert (
        "Login" not in page.text and "cookies" not in page.text
    )  # the page's furniture is left out
    assert page.final_url == "https://example.com/fox" and page.read_at.endswith("+00:00")
    # the connection went to the checked address; the name is the Host and the certificate name
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "example.com"
    assert seen[0].extensions["sni_hostname"] == "example.com"
    assert "cookie" not in seen[0].headers and "authorization" not in seen[0].headers


async def test_a_redirect_is_followed_and_checked_at_every_step():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "short.test":
            return httpx.Response(302, headers={"location": "https://example.com/fox"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text=ARTICLE)

    page = await reader(handler).read("https://short.test/x")
    assert page.final_url == "https://example.com/fox"

    def to_metadata(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    with pytest.raises(WebError) as e:
        await reader(to_metadata).read("https://short.test/x")
    assert e.value.code == "blocked_url"

    def endless(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://short.test/again"})

    with pytest.raises(WebError) as loop:
        await reader(endless).read("https://short.test/x")
    assert loop.value.code == "read_failed"


@pytest.mark.parametrize(
    ("status", "code"),
    [(403, "read_refused"), (401, "read_refused"), (404, "read_refused"), (500, "read_refused")],
)
async def test_a_site_that_refuses_is_said_so(status, code):
    with pytest.raises(WebError) as e:
        await reader(lambda r: httpx.Response(status, text="no")).read("https://example.com/")
    assert e.value.code == code and str(status) in e.value.message


async def test_only_pages_of_text_are_read():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7")

    with pytest.raises(WebError) as e:
        await reader(handler).read("https://example.com/a.pdf")
    assert e.value.code == "not_text"


async def test_a_page_with_no_text_to_read_says_so():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body><div id=app></div><script>x()</script></body></html>",
        )

    with pytest.raises(WebError) as e:
        await reader(handler).read("https://example.com/app")
    assert e.value.code == "unreadable" and "JavaScript" in e.value.message


async def test_a_long_page_is_cut_and_a_huge_body_is_not_read_to_the_end():
    big = (
        "<html><body><article>"
        + "<p>"
        + ("Long words about foxes and more foxes. " * 40)
        + "</p>" * 1
        + "".join(
            f"<p>{f'Another paragraph about the red fox number {n}. ' * 6}</p>" for n in range(200)
        )
        + "</article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=big)

    page = await reader(handler, max_chars=3000, max_bytes=60_000).read("https://example.com/long")
    assert page.truncated is True and len(page.text) <= 3000
