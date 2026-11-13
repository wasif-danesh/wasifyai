"""The models this service uses, shown to everyone signed in (the web's model button)."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from wasifyai_api.config import get_settings
from wasifyai_api.litellm_admin import InMemoryModelBackend
from wasifyai_api.media_access import MediaAccess, MediaCapability
from wasifyai_api.model_access import ModelAccess
from wasifyai_api.models_in_use import in_use
from wasifyai_api.services import ApiServices
from wasifyai_api.users import InMemoryUserStore
from wasifyai_platform_sdk import InMemoryMediaBindingStore, InMemoryUsageRecorder, SecretBox

from tests.test_auth import SECRET, token
from tests.test_runs import hello_registry, mem_app

DEFAULTS = {
    "default-chat": {
        "purpose": "General chat",
        "kind": "chat",
        "litellm_params": {"model": "ollama_chat/gemma4:e4b"},
    }
}
CAPS = [
    MediaCapability(product_id="wasifyai-image", capability="image.generate", workflow="flux2"),
    MediaCapability(product_id="wasifyai-video", capability="video.generate", workflow="ltx"),
]
WHO = cast("Any", SimpleNamespace(tenant_id="t", user_id="u"))


def request_with(products, caps=CAPS):
    media = MediaAccess(
        InMemoryMediaBindingStore(), SecretBox(SecretBox.generate_key()), lambda: caps, "http://c"
    )
    models = ModelAccess(InMemoryModelBackend(), DEFAULTS)
    services = ApiServices(models=models, media=media, products_dir=products)
    return cast(
        "Any", SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=services)))
    )


def catalogue(tmp_path):
    for pid, title in (("wasifyai-image", "FLUX.2 klein 4B"), ("wasifyai-video", "LTX-Video 2B")):
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "models.yaml").write_text(
            f"models:\n  - id: m\n    title: {title}\n    licence: Apache-2.0\n"
            "    source: https://example.test\n    files: []\n"
        )
    return tmp_path


async def test_it_names_the_chat_model(tmp_path):
    out = await in_use(request_with(catalogue(tmp_path)), WHO)
    assert [m.title for m in out.chat] == ["gemma4:e4b"]  # the provider's prefix is not shown
    # pictures, clips and 3D name the service's cloud model: tests/test_admin_providers.py
    assert out.images == [] and out.video == []  # no cloud keys service here


async def test_the_model_an_admin_chose_is_checked(tmp_path):
    """The desktop keeps a product's chosen model with the same service (ADR-0097, MV6)."""
    from wasifyai_api.media_access import MediaAccessError, ModelOption
    from wasifyai_api.settings_store import InMemorySettingsStore

    options = {
        "wasifyai-image": [
            ModelOption(id="klein", title="FLUX.2 klein 4B", can=["image.generate"]),
            ModelOption(id="qwen", title="Qwen-Image 2.1", can=["image.generate"]),
        ]
    }
    media = MediaAccess(
        InMemoryMediaBindingStore(), SecretBox(SecretBox.generate_key()), lambda: CAPS,
        "http://c", checks=InMemorySettingsStore(), models=lambda: options,
    )  # fmt: skip
    await media.choose_model("wasifyai-image", "qwen", "admin")
    assert await media.chosen_model("wasifyai-image") == "qwen"
    with pytest.raises(MediaAccessError):
        await media.choose_model("wasifyai-image", "nope", "admin")
    assert [c.chosen for c in await media.model_choices()] == ["qwen"]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("API_AUTH_SECRET", SECRET)
    get_settings.cache_clear()
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
    )
    app = mem_app(hello_registry(), tmp_path, InMemoryUsageRecorder(), users=InMemoryUserStore())
    with TestClient(app) as c:
        yield c
    monkeypatch.undo()
    get_settings.cache_clear()


def test_it_needs_a_signed_in_person_but_not_an_admin(client):
    assert client.get("/models/in-use").status_code == 401
    h = {"authorization": "Bearer " + token(sub="google:1", email="ann@example.com")}
    r = client.get("/models/in-use", headers=h)
    assert r.status_code == 200 and set(r.json()) == {"chat", "images", "video", "three_d"}
