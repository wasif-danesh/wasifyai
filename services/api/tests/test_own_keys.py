"""The person's own provider keys (ADR-0095; amendment of 2026-11-11; ADR-0099: OpenRouter for
text, fal.ai for media): keys per product and provider, saved once tested, kept in the secret store
under `keys.<product>.<provider>`, never answered back; the picker's Cloud tab lists the models of
each provider with a key and sets `use`. Keys of providers no longer offered are deleted."""

import json

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
    try_anthropic,
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
        "chat", "media", "images", "video", "voice", "music", "sfx", "lipsync", "model3d",
    ]  # fmt: skip
    assert all(p["keys"] == [] and p["use"] is None for p in body["products"])
    by = rows(body)
    # ADR-0100: text on the vendors, Anthropic first; media on Runware, WaveSpeed and fal.ai
    assert by["chat"]["providers"] == [
        "anthropic", "openai", "gemini", "deepseek", "zai", "openrouter",
    ]  # fmt: skip
    # one media key serves every media product (decision 9); the tie order throughout
    assert by["media"]["providers"] == ["runware", "wavespeed", "fal"]
    for media in ("images", "video", "music"):
        assert by[media]["providers"] == ["runware", "wavespeed", "fal"], media
    for media in ("voice", "sfx", "lipsync", "model3d"):
        assert by[media]["providers"] == ["fal"], media
    assert [p["id"] for p in body["providers"]] == [
        "anthropic", "openai", "gemini", "deepseek", "zai", "openrouter",
        "runware", "wavespeed", "fal",
    ]  # fmt: skip
    assert body["can_save"] is True


def test_a_key_is_tested_saved_per_provider_and_never_answered_back():
    c, secrets, testers = rig()
    r = c.put("/desktop/keys/music/keys/fal", json={"key": GOOD})
    assert r.status_code == 200, r.text
    assert GOOD not in r.text  # the key is never in an answer
    music = rows(c.get("/desktop/keys").json())["music"]
    assert [(k["provider"], k["state"]) for k in music["keys"]] == [("fal", "ok")]
    assert music["use"] is None  # saving a key chooses no model
    # media keys are tested against the media API; chat ones against the vendor's text API
    assert testers.calls[0][3] == own_keys.PROVIDERS["fal"].media_url
    c.put("/desktop/keys/chat/keys/openrouter", json={"key": GOOD + "-or"})
    assert testers.calls[-1][1:] == (
        "anthropic/claude-haiku-5.5",
        GOOD + "-or",
        own_keys.OPENROUTER_TEXT,
    )
    c.put("/desktop/keys/chat/keys/anthropic", json={"key": GOOD + "-an"})
    assert testers.calls[-1][1:] == (
        "claude-haiku-5-5",
        GOOD + "-an",
        "https://api.anthropic.com/v1/",
    )
    assert secrets.values == {
        "keys.music.fal": GOOD,
        "keys.chat.openrouter": GOOD + "-or",
        "keys.chat.anthropic": GOOD + "-an",
    }


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
        ("sfx", "runware", {"key": GOOD}, "no sound effects models"),
        ("images", "openai", {"key": GOOD}, "no images models"),
        ("images", "openrouter", {"key": GOOD}, "no images models"),  # no media on OpenRouter
        ("chat", "fal", {"key": GOOD}, "no chat and writing models"),  # no text through fal.ai
        ("chat", "compatible", {"key": GOOD}, "no chat and writing models"),
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
    cloud = c.get("/desktop/keys/lipsync/cloud").json()
    assert [(m["providers"], m["title"]) for m in cloud["models"]] == [
        (["fal"], "Fabric 1.0 Fast"), (["fal"], "Kling Avatar v2"), (["fal"], "OmniHuman 1.5"),
        (["fal"], "InfiniteTalk"),
    ]  # fmt: skip
    first = cloud["models"][0]
    assert first["price"] == "$0.10 per second at 480p, $0.20 at 720p"
    assert first["speed"] == "5 to 25 s per second of video at 480p (two runs)"
    assert first["provider_title"] == "fal.ai" and first["works"] and not first["chosen"]


def test_choosing_a_cloud_model_routes_the_product_and_clearing_it_keeps_the_keys():
    c, secrets, _ = rig()
    svc = c.app.state.services.own_keys  # type: ignore[attr-defined]
    c.put("/desktop/keys/music/keys/fal", json={"key": GOOD})
    # a media model is chosen, not a provider: the job runs on its cheapest keyed offer
    chosen = c.put("/desktop/keys/music/use", json={"model": "minimax-music-2.6"})
    assert chosen.status_code == 200, chosen.text
    assert [m["model"] for m in chosen.json()["models"] if m["chosen"]] == ["minimax-music-2.6"]
    route = svc.known("music")
    assert (route.provider.id, route.model, route.key) == ("fal", "minimax-music-2.6", GOOD)
    assert [(c.provider.id, c.offer.endpoint) for c in route.choices] == [
        ("fal", "fal-ai/minimax-music/v2.6")
    ]
    assert route.base_url == own_keys.PROVIDERS["fal"].media_url
    use = rows(c.get("/desktop/keys").json())["music"]["use"]
    assert use["title"] == "MiniMax Music 2.6" and use["price"] == "$0.15 per song"
    off = c.put("/desktop/keys/music/use", json={"provider": None})
    assert off.status_code == 200 and svc.known("music") is None
    assert secrets.values == {"keys.music.fal": GOOD}


@pytest.mark.parametrize(
    ("body", "status", "words"),
    [
        ({"model": "minimax-music-2.6"}, 409, "needs a Runware or WaveSpeed or fal.ai key"),
        ({"provider": "openrouter", "model": "anthropic/claude-haiku-5.5"}, 422, "no music model"),
        ({"provider": "fal", "model": "elevenlabs-music"}, 409, "needs a fal.ai key"),
        ({"provider": "anthropic", "model": "claude-haiku-5-5"}, 422, "no music model"),
    ],
)
def test_a_cloud_model_needs_its_key_and_must_be_in_the_list(body, status, words):
    c, _, _ = rig()
    r = c.put("/desktop/keys/music/use", json=body)
    assert r.status_code == status and words in r.json()["detail"]


def test_a_saved_key_that_stops_working_says_so_after_a_check():
    c, secrets, _ = rig()
    c.put("/desktop/keys/voice/keys/fal", json={"key": GOOD})
    secrets.values["keys.voice.fal"] = BAD  # revoked at the provider, say
    voice = rows(c.post("/desktop/keys/voice/keys/fal/check").json())["voice"]
    (key,) = voice["keys"]
    assert key["state"] == "bad" and key["said"] == "fal.ai did not accept the key."
    assert c.post("/desktop/keys/chat/keys/openrouter/check").status_code == 422  # none saved


def test_removing_a_key_forgets_it_and_a_model_that_used_it():
    c, secrets, _ = rig()
    svc = c.app.state.services.own_keys  # type: ignore[attr-defined]
    c.put("/desktop/keys/music/keys/fal", json={"key": GOOD})
    c.put("/desktop/keys/sfx/keys/fal", json={"key": GOOD})
    c.put("/desktop/keys/music/use", json={"provider": "fal", "model": "elevenlabs-music"})
    music = rows(c.delete("/desktop/keys/music/keys/fal").json())["music"]
    assert music["keys"] == [] and music["use"] is None
    assert svc.known("music") is None and secrets.values == {"keys.sfx.fal": GOOD}


async def test_a_row_saved_before_keys_per_provider_is_read_as_one_key_and_its_use():
    secrets, store = Store(), InMemorySettingsStore()
    await store.put(SETTINGS, {
        "music": {"mode": "key", "provider": "fal", "model": "fal-ai/elevenlabs/music",
                  "ok": True, "said": "", "tested_at": 1.0},
        "images": {"mode": "here", "provider": "fal", "model": "fal-ai/flux-2", "ok": True},
        "video": {"mode": "here"},
    }, "desktop")  # fmt: skip
    await secrets.put("keys.music", GOOD)
    await secrets.put("keys.images", GOOD)
    svc = OwnKeysService(store, secrets, {"text": FakeProviders(), "media": FakeProviders()})
    route = await svc.route("music")
    assert route is not None
    # the old choice (a provider and its endpoint) is read as the model (stage CP3)
    assert (route.provider.id, route.model) == ("fal", "elevenlabs-music")
    assert await svc.route("images") is None  # it ran on this computer; the key stays
    assert secrets.values == {"keys.music.fal": GOOD, "keys.images.fal": GOOD}
    saved = await store.get(SETTINGS)
    assert isinstance(saved, dict)
    assert saved["images"] == {"keys": {"fal": {"ok": True, "said": "", "tested_at": None}}}
    assert saved["video"] == {"keys": {}}


async def test_keys_of_providers_no_longer_offered_are_deleted_on_first_start():
    """ADR-0100: Groq, another OpenAI-compatible server and the media providers for chat go; the
    text vendors, WaveSpeed and Runware stay. A product that ran on a key that went runs on this
    computer again."""
    secrets, store = Store(), InMemorySettingsStore()
    ok = {"ok": True, "said": "", "tested_at": 1.0}
    await store.put(SETTINGS, {
        "chat": {"keys": {"fal": ok, "openai": ok, "compatible": {**ok, "base_url": "http://x"},
                          "groq": ok, "openrouter": ok},
                 "use": {"provider": "fal", "model": "openai/gpt-4o-mini"}},
        "music": {"keys": {"fal": ok, "wavespeed": ok},
                  "use": {"provider": "wavespeed", "model": "minimax/music-2.6"}},
        "images": {"keys": {"runware": ok}},
        "video": {"keys": {"runware": ok}},
    }, "desktop")  # fmt: skip
    for name in (
        "keys.chat.fal",
        "keys.chat.openai",
        "keys.chat.compatible",
        "keys.chat.groq",
        "keys.chat.openrouter",
        "keys.music.fal",
        "keys.music.wavespeed",
        "keys.images.runware",
        "keys.video.runware",
        "keys.sfx.wavespeed",
    ):  # the last one has no row
        await secrets.put(name, GOOD)
    svc = OwnKeysService(store, secrets, {"text": FakeProviders(), "media": FakeProviders()})
    assert await svc.route("chat") is None
    music = await svc.route("music")
    assert music is not None and music.provider.id == "wavespeed"
    assert secrets.values == {
        "keys.chat.openai": GOOD,
        "keys.chat.openrouter": GOOD,
        "keys.music.fal": GOOD,
        "keys.music.wavespeed": GOOD,
        "keys.images.runware": GOOD,
        "keys.video.runware": GOOD,
    }
    saved = await store.get(SETTINGS)
    assert isinstance(saved, dict)
    assert list(saved["chat"]["keys"]) == ["openai", "openrouter"] and "use" not in saved["chat"]
    assert list(saved["music"]["keys"]) == ["fal", "wavespeed"]
    assert list(saved["images"]["keys"]) == ["runware"]
    assert list(saved["video"]["keys"]) == ["runware"]  # Runware has video models (CP5)


# ---- the real testers, against fake providers ---------------------------------------------------


def _fake_http(monkeypatch, answer) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return answer(req)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        own_keys.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler))
    )
    return seen


@pytest.mark.parametrize(
    ("status", "ok", "words"),
    [(200, True, ""), (401, False, "did not accept"), (502, False, "answered 502")],
)  # fmt: skip
async def test_anthropic_is_asked_for_its_free_model_list(monkeypatch, status, ok, words):
    seen = _fake_http(monkeypatch, lambda req: httpx.Response(status, json={"data": []}))
    v = own_keys.PROVIDERS["anthropic"]
    tried = await try_anthropic(v, "claude-haiku-5-5", GOOD, v.base_url)
    assert tried.ok is ok and words in tried.said and GOOD not in tried.said
    (req,) = seen
    assert req.method == "GET" and str(req.url) == "https://api.anthropic.com/v1/models"
    assert req.headers["x-api-key"] == GOOD and req.headers["anthropic-version"] == "2023-06-01"


async def test_anthropic_has_its_own_check_and_other_vendors_one_token(monkeypatch):
    called: list[str] = []

    async def fake(name):
        async def t(provider, model, key, base_url):
            called.append(f"{name}:{provider.id}")
            return own_keys.Tried(True, 1, "")

        return t

    monkeypatch.setitem(own_keys.TEXT_TESTERS, "anthropic", await fake("own"))
    monkeypatch.setattr(own_keys, "try_text", await fake("chat"))
    for vid in ("anthropic", "deepseek", "zai"):
        v = own_keys.PROVIDERS[vid]
        await own_keys.try_vendor(v, "m", GOOD, v.base_url)
    assert called == ["own:anthropic", "chat:deepseek", "chat:zai"]


@pytest.mark.parametrize(
    ("status", "ok", "words"),
    [(200, True, ""), (401, False, "did not accept"), (500, False, "answered 500")],
)  # fmt: skip
async def test_wavespeed_is_asked_for_its_balance(monkeypatch, status, ok, words):
    seen = _fake_http(monkeypatch, lambda req: httpx.Response(status, json={"data": {}}))
    v = own_keys.PROVIDERS["wavespeed"]
    tried = await try_wavespeed(v, "minimax/music-2.6", GOOD, v.base_url)
    assert tried.ok is ok and words in tried.said
    (req,) = seen
    assert str(req.url) == "https://api.wavespeed.ai/api/v3/balance"
    assert req.headers["authorization"] == f"Bearer {GOOD}"


@pytest.mark.parametrize(
    ("status", "body", "ok", "words"),
    [(200, {"data": [{"taskType": "authentication"}]}, True, ""),
     (200, {"errors": [{"code": "invalidApiKey"}]}, False, "did not accept"),
     (401, {"errors": [{"code": "invalidApiKey"}]}, False, "did not accept")],
)  # fmt: skip
async def test_runware_is_sent_its_authentication_task(monkeypatch, status, body, ok, words):
    seen = _fake_http(monkeypatch, lambda req: httpx.Response(status, json=body))
    v = own_keys.PROVIDERS["runware"]
    tried = await try_runware(v, "runware:100@1", GOOD, v.base_url)
    assert tried.ok is ok and words in tried.said and GOOD not in tried.said
    (req,) = seen
    assert req.method == "POST" and str(req.url) == "https://api.runware.ai/v1"
    assert json.loads(req.content) == [{"taskType": "authentication", "apiKey": GOOD}]


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
