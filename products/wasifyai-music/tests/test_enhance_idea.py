import json

import yaml
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from wasifyai_music import prompts
from wasifyai_music.routes import build_routes
from wasifyai_platform_sdk import (
    Identity,
    InMemoryUploadLimiter,
    InMemoryUsageRecorder,
    ProviderDeps,
    RouteDeps,
    ScopedStorage,
    build_capabilities,
    load_product_config,
    memory_storage,
)


def who(x_user: str = Header("u1")) -> Identity:
    return Identity(tenant_id="t1", user_id=x_user)


def make(tmp_path, moderate, enhance):
    d = tmp_path / "wasifyai-music"
    d.mkdir()
    (d / "product.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "wasifyai-music",
                "capabilities": {
                    "text.moderate": {"provider": "fake", "defaults": {"replies": [moderate]}},
                    "text.enhance": {"provider": "fake", "defaults": {"replies": [enhance]}},
                },
                "enhance": {"song_idea": {"prompt": "enhance_song_idea", "max_chars": 500}},
            }
        )
    )
    usage = InMemoryUsageRecorder()
    deps = ProviderDeps(tmp_path, usage=usage, storage=ScopedStorage(memory_storage()))
    caps = build_capabilities(load_product_config(tmp_path, "wasifyai-music", environ={}), deps)
    app = FastAPI()
    app.state.caps = {"wasifyai-music": caps}
    app.state.enhance_limiter = InMemoryUploadLimiter(40)
    app.include_router(build_routes(RouteDeps(app.state, who)), prefix="/products/wasifyai-music")
    return TestClient(app), usage


OK = json.dumps({"allowed": True, "category": "ok", "reason": ""})
NO = json.dumps({"allowed": False, "category": "artist_voice", "reason": "x"})
URL = "/products/wasifyai-music/prompt/enhance"


def test_the_idea_stays_in_the_users_language_per_its_instructions():
    text = prompts.load("enhance_song_idea")
    assert "same language" in text and "Never translate" in text and "<user_text>" in text


def test_a_song_idea_is_checked_then_rewritten(tmp_path):
    client, usage = make(tmp_path, OK, "Una canción sobre la lluvia en Madrid y un adiós.")
    r = client.post(URL, json={"kind": "song_idea", "prompt": "lluvia"})
    assert r.status_code == 200 and r.json()["prompt"].startswith("Una canción")
    assert any(e.kind == "prompt.enhanced" for e in usage.events)


def test_an_artist_imitation_request_is_refused_with_the_fixed_text(tmp_path):
    client, usage = make(tmp_path, NO, "never used")
    r = client.post(URL, json={"kind": "song_idea", "prompt": "sing like a famous artist"})
    assert r.status_code == 422 and "artist's voice" in r.json()["detail"]
    assert not any(e.kind == "prompt.enhanced" for e in usage.events)
