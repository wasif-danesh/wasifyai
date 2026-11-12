"""The person's own provider keys (ADR-0095; amendment of 2026-11-11): keys per product and
provider, saved once tested, kept in the secret store under `keys.<product>.<provider>`, never
answered back; the picker's Cloud tab lists the models of each provider with a key and sets
`use`."""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wasifyai_api import own_keys
from wasifyai_api.identity import get_identity
from wasifyai_api.own_keys import (
    SETTINGS,
    OwnKeysService,
    Provider,
    Tried,
    try_fal,
    try_runware,
    try_text,
    try_wavespeed,
)
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


def test_every_product_starts_with_no_keys_and_offers_its_providers():
    c, _, _ = rig()
    body = c.get("/desktop/keys").json()
    assert list(rows(body)) == [
        "chat", "images", "video", "voice", "music", "sfx", "lipsync", "model3d",
    ]  # fmt: skip
    assert all(p["keys"] == [] and p["use"] is None for p in body["products"])
    by = rows(body)
    assert by["images"]["providers"] == ["fal", "wavespeed", "runware"]
    assert by["lipsync"]["providers"] == ["fal"]  # lip sync is fal.ai only (owner, 2026-11-12)
    assert by["music"]["providers"] == ["fal", "wavespeed", "runware"]
    assert by["video"]["providers"] == ["fal"]
    assert by["chat"]["providers"][:3] == ["fal", "wavespeed", "runware"]
    assert by["chat"]["providers"][-1] == "compatible"
    providers = {p["id"]: p for p in body["providers"]}
    assert providers["compatible"]["needs_base"] and not providers["fal"]["needs_base"]
    assert body["can_save"] is True


def test_a_key_is_tested_saved_per_provider_and_never_answered_back():
    c, secrets, testers = rig()
    r = c.put("/desktop/keys/music/keys/fal", json={"key": GOOD})
    assert r.status_code == 200, r.text
    assert GOOD not in r.text  # the key is never in an answer
    c.put("/desktop/keys/music/keys/wavespeed", json={"key": GOOD + "-ws"})
    music = rows(c.get("/desktop/keys").json())["music"]
    assert [(k["provider"], k["state"]) for k in music["keys"]] == [
        ("fal", "ok"), ("wavespeed", "ok"),
    ]  # fmt: skip
    assert music["use"] is None  # saving a key chooses no model
    assert secrets.values == {"keys.music.fal": GOOD, "keys.music.wavespeed": GOOD + "-ws"}
    # media keys are tested against the provider's media API; chat ones against its text route
    assert testers.calls[0][3] == own_keys.PROVIDERS["fal"].media_url
    c.put("/desktop/keys/chat/keys/fal", json={"key": GOOD})
    assert testers.calls[-1][1:] == ("google/gemini-2.5-flash", GOOD, own_keys.FAL_TEXT)


def test_a_key_the_provider_refuses_is_not_saved_and_the_reason_is_said():
    c, secrets, _ = rig()
    r = c.put("/desktop/keys/images/keys/fal", json={"key": BAD})
    assert r.status_code == 422 and r.json()["detail"] == "fal.ai did not accept the key."
    assert secrets.values == {}
    assert rows(c.get("/desktop/keys").json())["images"]["keys"] == []


def test_test_saves_nothing_and_uses_the_saved_key_when_none_is_given():
    c, secrets, testers = rig()
    t = c.post("/desktop/keys/video/keys/fal/test", json={"key": GOOD})
    assert t.json() == {"ok": True, "ms": 12, "said": None} and secrets.values == {}
    nothing = c.post("/desktop/keys/video/keys/fal/test", json={})
    assert nothing.status_code == 422 and "Paste the key" in nothing.json()["detail"]
    c.put("/desktop/keys/video/keys/fal", json={"key": GOOD})
    again = c.post("/desktop/keys/video/keys/fal/test", json={})
    assert again.json()["ok"] and testers.calls[-1][2] == GOOD


@pytest.mark.parametrize(
    ("product", "provider", "body", "words"),
    [
        ("video", "wavespeed", {"key": GOOD}, "no video models"),
        ("images", "openai", {"key": GOOD}, "no images models"),
        ("chat", "compatible", {"key": GOOD, "base_url": "https://x"}, "Name the model"),
        ("chat", "compatible", {"key": GOOD, "model": "m"}, "server's address"),
        ("chat", "compatible", {"key": GOOD, "model": "m", "base_url": "ftp://x"}, "https://"),
    ],
)
def test_what_cannot_be_used_is_refused_in_words(product, provider, body, words):
    c, _, testers = rig()
    r = c.post(f"/desktop/keys/{product}/keys/{provider}/test", json=body)
    assert r.status_code == 422 and words in r.json()["detail"]
    assert testers.calls == []
    assert c.post(f"/desktop/keys/nope/keys/{provider}/test", json=body).status_code == 404


def test_the_cloud_tab_lists_every_model_of_each_provider_with_a_key():
    c, _, _ = rig()
    empty = c.get("/desktop/keys/lipsync/cloud").json()
    assert empty == {"product": "lipsync", "models": [], "has_keys": False}
    c.put("/desktop/keys/lipsync/keys/fal", json={"key": GOOD})
    # lip sync is fal.ai only (owner, 2026-11-12): no WaveSpeed key is taken for it
    refused = c.put("/desktop/keys/lipsync/keys/wavespeed", json={"key": GOOD})
    assert refused.status_code == 422 and "no lip sync models" in refused.json()["detail"]
    cloud = c.get("/desktop/keys/lipsync/cloud").json()
    assert [(m["provider"], m["title"]) for m in cloud["models"]] == [
        ("fal", "Fabric 1.0 Fast"), ("fal", "Kling Avatar v2"), ("fal", "OmniHuman 1.5"),
        ("fal", "InfiniteTalk"),
    ]  # fmt: skip
    first = cloud["models"][0]
    assert first["price"] == "$0.10 per second at 480p, $0.20 at 720p"
    assert first["speed"] == "5 to 25 s per second of video at 480p (two runs)"
    assert first["provider_title"] == "fal.ai" and first["works"] and not first["chosen"]


def test_choosing_a_cloud_model_routes_the_product_and_clearing_it_keeps_the_keys():
    c, secrets, _ = rig()
    svc = c.app.state.services.own_keys  # type: ignore[attr-defined]
    c.put("/desktop/keys/music/keys/wavespeed", json={"key": GOOD})
    chosen = c.put(
        "/desktop/keys/music/use",
        json={"provider": "wavespeed", "model": "minimax/music-2.6"},
    )
    assert chosen.status_code == 200, chosen.text
    assert [m["model"] for m in chosen.json()["models"] if m["chosen"]] == ["minimax/music-2.6"]
    route = svc.known("music")
    assert (route.provider.id, route.model, route.key) == (
        "wavespeed",
        "minimax/music-2.6",
        GOOD,
    )
    assert route.base_url == own_keys.PROVIDERS["wavespeed"].media_url
    use = rows(c.get("/desktop/keys").json())["music"]["use"]
    assert use["title"] == "MiniMax Music 2.6" and use["price"] == "$0.15 per song"
    off = c.put("/desktop/keys/music/use", json={"provider": None})
    assert off.status_code == 200 and svc.known("music") is None
    assert secrets.values == {"keys.music.wavespeed": GOOD}


@pytest.mark.parametrize(
    ("body", "status", "words"),
    [
        ({"provider": "fal", "model": "fal-ai/minimax-music/v2.6"}, 409, "Save a fal.ai key"),
        ({"provider": "wavespeed", "model": "fal-ai/infinitalk"}, 422, "no music model"),
        ({"provider": "openai", "model": "gpt-4o-mini"}, 422, "no music models"),
    ],
)
def test_a_cloud_model_needs_its_key_and_must_be_in_the_list(body, status, words):
    c, _, _ = rig()
    c.put("/desktop/keys/music/keys/wavespeed", json={"key": GOOD})
    r = c.put("/desktop/keys/music/use", json=body)
    assert r.status_code == status and words in r.json()["detail"]


def test_an_openai_compatible_server_keeps_its_address_and_its_model():
    c, _, testers = rig()
    body = {"model": "llama3", "base_url": "http://192.168.1.5:8000/v1/", "key": GOOD}
    chat = rows(c.put("/desktop/keys/chat/keys/compatible", json=body).json())["chat"]
    (key,) = chat["keys"]
    assert (key["base_url"], key["model"]) == ("http://192.168.1.5:8000/v1", "llama3")
    assert testers.calls[-1][1:] == ("llama3", GOOD, "http://192.168.1.5:8000/v1")
    (row,) = c.get("/desktop/keys/chat/cloud").json()["models"]
    assert (row["model"], row["provider"]) == ("llama3", "compatible")
    c.put("/desktop/keys/chat/use", json={"provider": "compatible", "model": "llama3"})
    route = c.app.state.services.own_keys.known("chat")  # type: ignore[attr-defined]
    assert route.base_url == "http://192.168.1.5:8000/v1" and route.model == "llama3"


def test_a_saved_key_that_stops_working_says_so_after_a_check():
    c, secrets, _ = rig()
    c.put("/desktop/keys/voice/keys/fal", json={"key": GOOD})
    secrets.values["keys.voice.fal"] = BAD  # revoked at the provider, say
    voice = rows(c.post("/desktop/keys/voice/keys/fal/check").json())["voice"]
    (key,) = voice["keys"]
    assert key["state"] == "bad" and key["said"] == "fal.ai did not accept the key."
    assert c.post("/desktop/keys/chat/keys/openai/check").status_code == 422  # none saved


def test_removing_a_key_forgets_it_and_a_model_that_used_it():
    c, secrets, _ = rig()
    svc = c.app.state.services.own_keys  # type: ignore[attr-defined]
    c.put("/desktop/keys/music/keys/fal", json={"key": GOOD})
    c.put("/desktop/keys/music/keys/runware", json={"key": GOOD})
    c.put("/desktop/keys/music/use", json={"provider": "fal", "model": "fal-ai/elevenlabs/music"})
    music = rows(c.delete("/desktop/keys/music/keys/fal").json())["music"]
    assert [k["provider"] for k in music["keys"]] == ["runware"] and music["use"] is None
    assert svc.known("music") is None and secrets.values == {"keys.music.runware": GOOD}


async def test_a_row_saved_before_keys_per_provider_is_read_as_one_key_and_its_use():
    secrets, store = Store(), InMemorySettingsStore()
    await store.put(SETTINGS, {
        "chat": {"mode": "key", "provider": "fal_text", "model": "openai/gpt-4o-mini", "ok": True,
                 "said": "", "tested_at": 1.0, "base_url": ""},
        "images": {"mode": "here", "provider": "fal", "model": "fal-ai/flux-2", "ok": True},
        "video": {"mode": "here"},
    }, "desktop")  # fmt: skip
    await secrets.put("keys.chat", GOOD)
    await secrets.put("keys.images", GOOD)
    svc = OwnKeysService(store, secrets, {"text": FakeProviders(), "media": FakeProviders()})
    route = await svc.route("chat")
    assert route is not None and (route.provider.id, route.model) == ("fal", "openai/gpt-4o-mini")
    assert route.base_url == own_keys.FAL_TEXT
    assert await svc.route("images") is None  # it ran on this computer; the key stays
    assert secrets.values == {"keys.chat.fal": GOOD, "keys.images.fal": GOOD}
    saved = await store.get(SETTINGS)
    assert isinstance(saved, dict)
    assert saved["images"] == {"keys": {"fal": {
        "ok": True, "said": "", "tested_at": None, "base_url": "", "model": ""}}}  # fmt: skip
    assert saved["video"] == {"keys": {}}


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


async def test_fal_ai_as_a_text_provider_sends_its_key_as_key_not_bearer(monkeypatch):
    seen: list[httpx.Request] = []

    def answer(req: httpx.Request) -> httpx.Response:
        seen.append(req)
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
    v = own_keys.PROVIDERS["fal"]
    assert v.text_url == own_keys.FAL_TEXT and v.host == "fal.ai"
    tried = await try_text(v, "google/gemini-2.5-flash", GOOD, v.text_url)
    assert tried.ok
    assert str(seen[0].url) == "https://fal.run/openrouter/router/openai/v1/chat/completions"
    assert seen[0].headers["authorization"] == f"Key {GOOD}"


@pytest.mark.parametrize(
    ("status", "body", "ok", "words"),
    [(200, {"data": {"balance": 1.0}}, True, ""), (401, {}, False, "did not accept"),
     (503, {}, False, "answered 503")],
)  # fmt: skip
async def test_wavespeed_is_asked_for_its_balance(monkeypatch, status, body, ok, words):
    seen: list[httpx.Request] = []

    def answer(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, json=body)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        own_keys.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(answer))
    )
    v = own_keys.PROVIDERS["wavespeed"]
    tried = await try_wavespeed(v, "", GOOD, v.media_url)
    assert tried.ok is ok and words in tried.said
    assert str(seen[0].url) == "https://api.wavespeed.ai/api/v3/balance"
    assert seen[0].headers["authorization"] == f"Bearer {GOOD}"


@pytest.mark.parametrize(
    ("status", "body", "ok"),
    [(200, {"data": [{"taskType": "authentication", "connectionSessionUUID": "x"}]}, True),
     (200, {"errors": [{"code": "invalidApiKey", "message": "Invalid API key"}]}, False),
     (401, {}, False)],
)  # fmt: skip
async def test_runware_is_sent_its_authentication_task(monkeypatch, status, body, ok):
    seen: list[httpx.Request] = []

    def answer(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, json=body)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        own_keys.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(answer))
    )
    v = own_keys.PROVIDERS["runware"]
    tried = await try_runware(v, "", GOOD, v.media_url)
    assert tried.ok is ok
    assert seen[0].method == "POST" and str(seen[0].url) == "https://api.runware.ai/v1"
    assert b'"taskType":"authentication"' in seen[0].content.replace(b" ", b"")
