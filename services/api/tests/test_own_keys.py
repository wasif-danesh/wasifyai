"""The person's own provider keys (ADR-0095, stage K1): saved once tested, kept in the secret store
under `keys.<product>`, never answered back, copied inside the store, removed with the settings."""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api import own_keys
from wasifyai_api.identity import get_identity
from wasifyai_api.own_keys import OwnKeysService, Provider, Tried, try_fal, try_text
from wasifyai_api.services import ApiServices
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import Identity, InMemorySecretStore

GOOD = "sk-or-good-0123456789"
BAD = "sk-or-bad-0123456789"


class Store(InMemorySecretStore):
    @property
    def values(self) -> dict[str, str]:  # what is kept, for the checks
        return self._values


class FakeProviders:
    """Stands in for the providers: a key with "good" in it is accepted."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    async def __call__(self, provider: Provider, model: str, key: str, base: str) -> Tried:
        self.calls.append((provider.id, model, key, base))
        if "good" in key:
            return Tried(True, 12)
        return Tried(False, 9, f"{provider.title} did not accept the key.")


def rig() -> tuple[TestClient, Store, FakeProviders]:
    secrets, testers = Store(), FakeProviders()
    services = ApiServices()
    services.own_keys = OwnKeysService(
        InMemorySettingsStore(), secrets, {"text": testers, "media": testers}
    )
    app = FastAPI()
    app.state.services = services
    app.include_router(own_keys.router)
    app.dependency_overrides[get_identity] = lambda: Identity("local", "u1", "user")
    return TestClient(app), secrets, testers


def rows(body: dict) -> dict[str, dict]:
    return {p["id"]: p for p in body["products"]}


def test_every_product_starts_on_this_computer_and_the_providers_are_listed():
    c, _, _ = rig()
    body = c.get("/desktop/keys").json()
    assert list(rows(body)) == ["chat", "images", "video", "voice", "model3d"]
    assert all(p["mode"] == "here" and not p["key_saved"] for p in body["products"])
    by = {p["id"]: p for p in body["providers"]}
    assert by["openrouter"]["kind"] == "text" and by["fal"]["kind"] == "media"
    assert by["compatible"]["needs_base"] and not by["openrouter"]["needs_base"]
    assert rows(body)["images"]["models"] == ["fal-ai/flux-2"] and body["can_save"] is True


def test_a_key_is_tested_saved_in_the_store_and_never_answered_back():
    c, secrets, testers = rig()
    choice = {"mode": "key", "provider": "openrouter", "model": "openai/gpt-4o-mini", "key": GOOD}
    r = c.put("/desktop/keys/chat", json=choice)
    assert r.status_code == 200, r.text
    assert GOOD not in r.text  # the key is never in an answer
    chat = rows(r.json())["chat"]
    assert chat["mode"] == "key" and chat["state"] == "ok" and chat["key_saved"]
    assert (chat["provider"], chat["model"]) == ("openrouter", "openai/gpt-4o-mini")
    assert secrets.values == {"keys.chat": GOOD}
    assert testers.calls == [
        ("openrouter", "openai/gpt-4o-mini", GOOD, own_keys.PROVIDERS["openrouter"].base_url)
    ]


def test_a_key_the_provider_refuses_is_not_saved_and_the_reason_is_said():
    c, secrets, _ = rig()
    r = c.put(
        "/desktop/keys/images",
        json={"mode": "key", "provider": "fal", "model": "fal-ai/flux-2", "key": BAD},
    )
    assert r.status_code == 422 and r.json()["detail"] == "fal.ai did not accept the key."
    assert secrets.values == {}
    assert rows(c.get("/desktop/keys").json())["images"]["mode"] == "here"


def test_test_saves_nothing_and_uses_the_saved_key_when_none_is_given():
    c, secrets, testers = rig()
    t = c.post(
        "/desktop/keys/video/test",
        json={"provider": "fal", "model": "fal-ai/ltx-2/text-to-video/fast", "key": GOOD},
    )
    assert t.json() == {"ok": True, "ms": 12, "said": None} and secrets.values == {}
    nothing = c.post("/desktop/keys/video/test", json={"provider": "fal", "model": "m"})
    assert nothing.status_code == 422 and "Paste the key" in nothing.json()["detail"]
    c.put("/desktop/keys/video", json={"mode": "key", "provider": "fal", "model": "m", "key": GOOD})
    again = c.post("/desktop/keys/video/test", json={"provider": "fal", "model": "m"})
    assert again.json()["ok"] and testers.calls[-1][2] == GOOD


@pytest.mark.parametrize(
    ("product", "body", "words"),
    [
        ("chat", {"provider": "fal", "model": "x", "key": GOOD}, "can do chat"),
        ("images", {"provider": "openai", "model": "x", "key": GOOD}, "can do images"),
        ("chat", {"provider": "openai", "model": " ", "key": GOOD}, "Choose a model"),
        ("chat", {"provider": "compatible", "model": "m", "key": GOOD}, "server's address"),
        (
            "chat",
            {"provider": "compatible", "model": "m", "key": GOOD, "base_url": "ftp://x"},
            "https://",
        ),
    ],
)
def test_what_cannot_be_used_is_refused_in_words(product, body, words):
    c, _, testers = rig()
    r = c.post(f"/desktop/keys/{product}/test", json=body)
    assert r.status_code == 422 and words in r.json()["detail"]
    assert testers.calls == []
    assert c.post("/desktop/keys/nope/test", json=body).status_code == 404


def test_an_openai_compatible_server_keeps_its_address():
    c, _, testers = rig()
    body = {"mode": "key", "provider": "compatible", "model": "llama3",
            "base_url": "http://192.168.1.5:8000/v1/", "key": GOOD}  # fmt: skip
    chat = rows(c.put("/desktop/keys/chat", json=body).json())["chat"]
    assert chat["base_url"] == "http://192.168.1.5:8000/v1"
    assert testers.calls[-1][3] == "http://192.168.1.5:8000/v1"


def test_a_saved_key_that_stops_working_says_so_after_a_check():
    c, secrets, _ = rig()
    c.put(
        "/desktop/keys/voice",
        json={"mode": "key", "provider": "fal", "model": "fal-ai/kokoro", "key": GOOD},
    )
    secrets.values["keys.voice"] = BAD  # revoked at the provider, say
    voice = rows(c.post("/desktop/keys/voice/check").json())["voice"]
    assert voice["state"] == "bad" and voice["said"] == "fal.ai did not accept the key."
    assert c.post("/desktop/keys/chat/check").status_code == 422  # chat runs here


def test_the_same_key_is_copied_inside_the_store_between_products_of_one_kind():
    c, secrets, _ = rig()
    c.put(
        "/desktop/keys/images",
        json={"mode": "key", "provider": "fal", "model": "fal-ai/flux-2", "key": GOOD},
    )
    r = c.post("/desktop/keys/voice/copy", json={"source": "images"})
    assert r.status_code == 200 and GOOD not in r.text
    voice = rows(r.json())["voice"]
    assert voice["key_saved"] and voice["provider"] == "fal" and voice["mode"] == "here"
    assert secrets.values["keys.voice"] == GOOD
    wrong = c.post("/desktop/keys/chat/copy", json={"source": "images"})
    assert wrong.status_code == 422 and "another kind" in wrong.json()["detail"]
    empty = c.post("/desktop/keys/model3d/copy", json={"source": "video"})
    assert empty.status_code == 422 and "no key saved" in empty.json()["detail"]
    # now saved with the copied key: no key need be pasted again
    saved = c.put(
        "/desktop/keys/voice", json={"mode": "key", "provider": "fal", "model": "fal-ai/kokoro"}
    )
    assert rows(saved.json())["voice"]["state"] == "ok"


def test_back_to_this_computer_keeps_the_key_and_remove_forgets_both():
    c, secrets, _ = rig()
    c.put("/desktop/keys/chat", json={"mode": "key", "provider": "groq", "model": "m", "key": GOOD})
    here = rows(c.put("/desktop/keys/chat", json={"mode": "here"}).json())["chat"]
    assert here["mode"] == "here" and here["key_saved"] and secrets.values["keys.chat"] == GOOD
    gone = rows(c.delete("/desktop/keys/chat").json())["chat"]
    assert gone["mode"] == "here" and not gone["key_saved"] and gone["provider"] is None
    assert secrets.values == {}


# ---- the real testers, against fake providers ---------------------------------------------------


@pytest.mark.parametrize(
    ("status", "ok", "words"),
    [(404, True, ""), (405, True, ""), (401, False, "did not accept"),
     (403, False, "did not accept"), (502, False, "answered 502")],
)  # fmt: skip
async def test_fal_is_asked_about_a_request_that_does_not_exist(monkeypatch, status, ok, words):
    seen: list[httpx.Request] = []

    def answer(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, json={"detail": "x"})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        own_keys.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(answer))
    )
    fal = own_keys.PROVIDERS["fal"]
    tried = await try_fal(fal, "fal-ai/ltx-2/text-to-video/fast", GOOD, fal.base_url)
    assert tried.ok is ok and words in tried.said
    (req,) = seen
    assert req.method == "GET" and req.headers["authorization"] == f"Key {GOOD}"
    assert str(req.url).startswith("https://queue.fal.run/fal-ai/ltx-2/requests/")  # owner/app only


@pytest.mark.parametrize(
    ("status", "ok", "words"),
    [(200, True, ""), (401, False, "did not accept"), (404, False, "no model called m"),
     (429, False, "too many requests"), (500, False, "answered 500")],
)  # fmt: skip
async def test_a_text_provider_is_asked_for_one_token(monkeypatch, status, ok, words):
    seen: list[httpx.Request] = []

    def answer(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "no"}})
        return httpx.Response(200, json={
            "id": "c", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "length",
                         "message": {"role": "assistant", "content": "OK"}}],
        })  # fmt: skip

    real = own_keys.AsyncOpenAI
    monkeypatch.setattr(
        own_keys,
        "AsyncOpenAI",
        lambda **kw: real(
            **kw,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(answer)),  # pyright: ignore[reportArgumentType]
        ),
    )
    v = own_keys.PROVIDERS["openrouter"]
    tried = await try_text(v, "m", GOOD, v.base_url)
    assert tried.ok is ok and words in tried.said
    assert GOOD not in tried.said
    assert str(seen[0].url) == "https://openrouter.ai/api/v1/chat/completions"
    assert seen[0].headers["authorization"] == f"Bearer {GOOD}"
