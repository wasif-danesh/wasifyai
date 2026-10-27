"""Web search settings and the service behind `web.search` (ADR-0083, stage CO3): what the person
allowed, the keys kept encrypted, and the searches and reads it permits."""

import os
import stat
from typing import Any

import httpx
import pytest
from wasifyai_api.safeguards import InMemorySettingsStore
from wasifyai_api.web_search import KEY, WebService, consent_text, load_or_create_key
from wasifyai_platform_sdk import (
    FileSecretStore,
    InMemorySecretStore,
    InMemoryUsageRecorder,
    RunContext,
    SecretBox,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.web import DuckDuckGoProvider, WebError, WebReader


@pytest.fixture
def ctx():
    token = set_context(RunContext("t1", "wasifyai-assistant", "u1", run_id="r1", thread_id="th"))
    yield
    reset_context(token)


def service(**kw: Any) -> tuple[WebService, InMemorySettingsStore, InMemoryUsageRecorder]:
    store = InMemorySettingsStore()
    usage = InMemoryUsageRecorder()
    ddg = DuckDuckGoProvider(
        min_gap_s=0,
        run=lambda q, n: [{"title": "Fox", "href": "https://a.test/fox", "body": "Foxes."}],
    )
    svc = WebService(store, InMemorySecretStore(), usage, duckduckgo=ddg, **kw)
    return svc, store, usage


async def test_nothing_is_allowed_until_the_person_says_so_and_duckduckgo_is_the_default():
    svc, _, _ = service()
    st = await svc.status()
    assert st["provider"] == "duckduckgo" and st["consented"] is False
    assert [p["id"] for p in st["providers"]] == ["duckduckgo", "ollama", "tavily", "exa", "brave"]
    assert "DuckDuckGo" in st["consent_text"] and "turn this off in Settings" in st["consent_text"]
    ready = await svc.readiness()
    assert ready.state == "needs_setup" and "off" in ready.step
    with pytest.raises(WebError) as e:
        await svc.search("fox")
    assert e.value.code == "search_off"


async def test_allowing_search_lets_it_run_and_counts_it(ctx):
    svc, _, usage = service()
    await svc.update(consent=True)
    assert (await svc.readiness()).state == "ready"
    found = await svc.search("fox", 3)
    assert found.provider == "duckduckgo" and found.results[0].title == "Fox"
    kinds = [(e.kind, e.unit, e.meta) for e in usage.events]
    assert kinds == [("web.search", "searches", {"provider": "duckduckgo"})]  # no query in it
    await svc.update(consent=False)
    with pytest.raises(WebError):
        await svc.search("fox")


async def test_the_consent_is_for_the_service_named_so_another_one_asks_again():
    svc, _, _ = service()
    await svc.update(consent=True)
    assert (await svc.status())["consented"] is True
    st = await svc.update(provider="tavily")
    assert st["provider"] == "tavily" and st["consented"] is False
    assert "Tavily" in st["consent_text"]
    st = await svc.update(provider="duckduckgo")  # back: it does not remember an old yes
    assert st["consented"] is False
    st = await svc.update(provider="duckduckgo", consent=True)
    assert st["consented"] is True
    assert consent_text("ollama").startswith("Searching the web sends your question to Ollama")


async def test_a_keyed_service_needs_its_key_and_the_key_is_kept_encrypted_and_never_shown():
    svc, store, _ = service()
    await svc.update(provider="tavily", consent=True)
    ready = await svc.readiness()
    assert ready.state == "needs_setup" and "Tavily" in ready.step and "key" in ready.step
    secret = "tvly-SECRET-1234567890"
    st = await svc.update(key=("tavily", f"  {secret}\n"))
    assert next(p for p in st["providers"] if p["id"] == "tavily")["key_set"] is True
    assert secret not in repr(st)  # the answer says that a key is saved, not what it is
    assert secret not in repr(store.values)  # and the store holds it encrypted
    assert (await svc.readiness()).state == "ready"
    # the provider is made with the real key when a search runs
    provider = await svc._provider()
    assert provider.id == "tavily" and provider._key == secret  # type: ignore[attr-defined]
    st = await svc.update(remove_key="tavily")
    assert next(p for p in st["providers"] if p["id"] == "tavily")["key_set"] is False
    assert (await svc.readiness()).state == "needs_setup"


@pytest.mark.parametrize(
    "key", ["short", "has a space in it 12345", "x" * 400, "tab\tinside1234567"]
)
async def test_a_key_that_cannot_be_one_is_refused_in_words(key):
    svc, _, _ = service()
    with pytest.raises(ValueError, match="does not look like a key"):
        await svc.update(key=("exa", key))


async def test_settings_refuse_what_makes_no_sense():
    svc, _, _ = service()
    with pytest.raises(ValueError, match="not a search service"):
        await svc.update(provider="bing")
    with pytest.raises(ValueError, match="does not use a key"):
        await svc.update(key=("duckduckgo", "abcdefgh12345"))
    no_box = WebService(InMemorySettingsStore(), None)
    with pytest.raises(ValueError, match="cannot be saved"):
        await no_box.update(key=("exa", "abcdefgh12345"))
    assert (await no_box.status())["can_save_keys"] is False


async def test_a_saved_key_that_cannot_be_read_says_to_enter_it_again(tmp_path):
    store = InMemorySettingsStore()
    path = tmp_path / "secrets.json"
    first = WebService(store, FileSecretStore(path, SecretBox(SecretBox.generate_key())))
    await first.update(provider="exa", consent=True, key=("exa", "exa-key-123456789"))
    # the key file was replaced: the same store file, another key
    other_key = WebService(store, FileSecretStore(path, SecretBox(SecretBox.generate_key())))
    with pytest.raises(WebError) as e:
        await other_key._provider()
    assert e.value.code == "needs_key" and "Enter it again" in e.value.message


async def test_a_page_is_read_only_after_the_person_allowed_the_web(ctx):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body><article>"
            + "".join(
                f"<p>Foxes live in many places and eat small animals and fruit, fact {n}.</p>"
                for n in range(8)
            )
            + "</article></body></html>",
        )

    async def public(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    reader = WebReader(
        resolve=public, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    svc, _, usage = service(reader=reader)
    with pytest.raises(WebError) as off:
        await svc.read("https://example.com/foxes")
    assert off.value.code == "search_off" and seen == []  # nothing was fetched
    await svc.update(consent=True)
    page = await svc.read("https://example.com/foxes")
    assert "Foxes live" in page.text
    assert [(e.kind, e.unit) for e in usage.events] == [("web.read", "pages")]


def test_the_key_file_is_made_once_and_only_this_user_can_read_it(tmp_path):
    path = tmp_path / "data" / "secrets.key"
    first = load_or_create_key(path)
    assert SecretBox(first).ready
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert load_or_create_key(path) == first  # the same key every time after


async def test_a_corrupt_setting_falls_back_to_the_safe_default():
    svc, store, _ = service()
    store.values[KEY] = {"provider": "nonsense", "consented_for": "also-nonsense", "keys": "x"}
    st = await svc.status()
    assert st["provider"] == "duckduckgo" and st["consented"] is False
    store.values[KEY] = "not even a dict"
    assert (await svc.status())["consented"] is False


# ---- on a service: an admin keeps the service and keys; each person allows it


class Who:
    def __init__(self, user: str) -> None:
        self.tenant_id, self.user_id = "t1", user


async def test_on_a_service_each_person_allows_searching_for_themself():
    svc, _, _ = service(per_person=True)
    ann, bob = Who("ann"), Who("bob")
    assert (await svc.status(ann))["consented"] is False
    await svc.update(consent=True, who=ann)
    assert (await svc.status(ann))["consented"] is True
    assert (await svc.status(bob))["consented"] is False  # not for anyone else
    assert (await svc.readiness(bob)).state == "needs_setup"
    assert (await svc.readiness(ann)).state == "ready"
    assert "from this service" in (await svc.status(ann))["consent_text"]
    await svc.update(consent=False, who=ann)
    assert (await svc.status(ann))["consented"] is False


async def test_on_a_service_a_run_searches_for_the_person_whose_run_it_is(ctx):
    svc, _, usage = service(per_person=True)
    with pytest.raises(WebError):  # u1 has not allowed it
        await svc.search("fox")
    await svc.update(consent=True, who=Who("u1"))
    found = await svc.search("fox")
    assert found.results and usage.events


async def test_a_different_service_asks_each_person_again():
    svc, _, _ = service(per_person=True)
    ann = Who("ann")
    await svc.update(consent=True, who=ann)
    await svc.update(provider="tavily")  # an admin's change
    assert (await svc.status(ann))["consented"] is False
