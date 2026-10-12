import time

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from wasifyai_api.admin import InMemoryAdminStore
from wasifyai_api.config import get_settings
from wasifyai_api.media_access import MediaAccess, MediaAccessError, MediaBindingIn, MediaCapability
from wasifyai_api.users import InMemoryUserStore
from wasifyai_platform_sdk import InMemoryMediaBindingStore, InMemoryUsageRecorder, SecretBox

from tests.test_auth import SECRET
from tests.test_runs import hello_registry, mem_app

KEY = "comfyui-0123456789abcdef0123456789abcdef"
CAPS = [
    MediaCapability(product_id="wasifyai-music", capability="image.generate", workflow="flux2"),
    MediaCapability(product_id="wasifyai-music", capability="music.generate", workflow="ace"),
]


def make(ready=True, handler=None):
    box = SecretBox(SecretBox.generate_key() if ready else "")
    store = InMemoryMediaBindingStore()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler)) if handler else None
    return MediaAccess(store, box, lambda: CAPS, "http://local:8188", http), store, box


T = "tenant"
IMG = ("wasifyai-music", "image.generate")
MUS = ("wasifyai-music", "music.generate")


async def test_everything_starts_on_the_product_default():
    media, _, _ = make()
    listing = await media.list(T)
    assert [(i.capability, i.backend, i.source) for i in listing.items] == [
        ("image.generate", "comfyui-local", "default"),
        ("music.generate", "comfyui-local", "default"),
    ]
    assert listing.secrets_ready and {b.id for b in listing.backends} >= {
        "comfy-api",
        "openai-images",
    }
    image = listing.items[0]
    assert set(image.allowed_backends) == {"comfyui-local", "comfy-api", "openai-images"}
    assert set(listing.items[1].allowed_backends) == {"comfyui-local", "comfy-api"}


async def test_a_hosted_backend_is_saved_with_its_key_encrypted():
    media, store, box = make()
    view = await media.set(
        T,
        *IMG,
        MediaBindingIn(backend="comfy-api", config={"base_url": "https://c.example"}, api_key=KEY),
        "admin-1",
    )
    assert (view.backend, view.source, view.key_set, view.updated_by) == (
        "comfy-api",
        "custom",
        True,
        "admin-1",
    )
    assert view.config == {"base_url": "https://c.example"}
    assert KEY not in view.model_dump_json()
    stored = await store.get(T, *IMG)
    assert stored and stored.secret_enc and KEY not in stored.secret_enc
    assert box.decrypt(stored.secret_enc) == KEY


async def test_saving_again_without_a_key_keeps_the_key_for_the_same_backend_only():
    media, store, box = make()
    await media.set(T, *IMG, MediaBindingIn(backend="comfy-api", api_key=KEY), "a")
    kept = await media.set(
        T, *IMG, MediaBindingIn(backend="comfy-api", config={"base_url": "https://n.example"}), "a"
    )
    assert kept.key_set and box.decrypt((await store.get(T, *IMG)).secret_enc) == KEY  # type: ignore[union-attr, arg-type]
    # a different backend must not inherit the key: it would be sent to another service
    await media.set(T, *IMG, MediaBindingIn(backend="openai-images", config={"model": "m"}), "a")
    assert (await store.get(T, *IMG)).secret_enc is None  # type: ignore[union-attr]
    with pytest.raises(MediaAccessError, match="needs an api key"):
        await media.set(T, *IMG, MediaBindingIn(backend="comfy-api"), "a")


@pytest.mark.parametrize(
    ("binding", "message"),
    [
        (MediaBindingIn(backend="openai-images", config={"model": "m"}), None),
        (MediaBindingIn(backend="nope"), "unknown backend"),
        (MediaBindingIn(backend="comfy-api"), "needs an api key"),
        (
            MediaBindingIn(backend="comfy-api", api_key=KEY, config={"base_url": "http://u:p@x"}),
            "credentials",
        ),
    ],
)
async def test_validation_errors_reach_the_admin(binding, message):
    media, _, _ = make()
    if message is None:
        await media.set(T, *IMG, binding, "a")
        return
    with pytest.raises(MediaAccessError, match=message):
        await media.set(T, *IMG, binding, "a")


async def test_a_music_capability_cannot_use_an_image_only_backend():
    media, _, _ = make()
    with pytest.raises(MediaAccessError, match="cannot serve"):
        await media.set(
            T, *MUS, MediaBindingIn(backend="openai-images", config={"model": "m"}), "a"
        )


async def test_a_key_is_refused_while_the_encryption_key_is_missing():
    media, store, _ = make(ready=False)
    with pytest.raises(MediaAccessError, match="MEDIA_SECRETS_KEY"):
        await media.set(T, *IMG, MediaBindingIn(backend="comfy-api", api_key=KEY), "a")
    assert await store.get(T, *IMG) is None
    assert (await media.list(T)).secrets_ready is False
    # a backend without a key still works
    await media.set(
        T,
        *IMG,
        MediaBindingIn(backend="comfyui-local", config={"base_url": "http://gpu:8188"}),
        "a",
    )


async def test_unknown_capabilities_and_reset():
    media, store, _ = make()
    with pytest.raises(MediaAccessError, match="no media capability"):
        await media.get(T, "wasifyai-music", "video.generate")
    await media.set(T, *IMG, MediaBindingIn(backend="comfyui-local"), "a")
    view = await media.reset(T, *IMG)
    assert (view.backend, view.source) == ("comfyui-local", "default") and await store.get(
        T, *IMG
    ) is None


async def test_tenants_do_not_see_each_others_bindings():
    media, _, _ = make()
    await media.set("a", *IMG, MediaBindingIn(backend="comfy-api", api_key=KEY), "x")
    assert (await media.list("b")).items[0].source == "default"


async def test_test_connection_uses_a_proposed_binding_or_the_saved_one_and_never_leaks_the_key():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(404)

    media, _, _ = make(handler=handler)
    out = await media.test(T, *IMG, MediaBindingIn(backend="comfy-api", api_key=KEY))
    assert out.ok and seen[-1].headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in out.message
    await media.set(T, *IMG, MediaBindingIn(backend="comfy-api", api_key=KEY), "a")
    saved = await media.test(T, *IMG, None)  # the saved key is decrypted for the check
    assert saved.ok and seen[-1].headers["authorization"] == f"Bearer {KEY}"
    again = await media.test(
        T, *IMG, MediaBindingIn(backend="comfy-api")
    )  # same backend: saved key
    assert again.ok and seen[-1].headers["authorization"] == f"Bearer {KEY}"
    default = await media.test(T, *MUS, None)  # nothing saved: the default local ComfyUI
    assert str(seen[-1].url) == "http://local:8188/system_stats" and not default.ok


# ---- the HTTP routes ----------------------------------------------------------------------


def _token(sub, email, verified):
    now = int(time.time())
    claims = {
        "iss": "wasifyai-web", "aud": "wasifyai-api", "iat": now, "exp": now + 300,
        "sub": sub, "email": email, "email_verified": verified,
    }  # fmt: skip
    return "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")


ADMIN = {"authorization": _token("google:9", "boss@example.com", True)}
USER = {"authorization": _token("google:1", "ann@example.com", True)}


@pytest.fixture
def routes(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("API_AUTH_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    get_settings.cache_clear()
    (tmp_path / "hello").mkdir()
    (tmp_path / "hello" / "product.yaml").write_text(
        "id: hello\ncapabilities:\n  text.chat: { provider: fake, defaults: { reply: hi } }\n"
    )
    media, _, _ = make(handler=lambda request: httpx.Response(404))
    admin = InMemoryAdminStore()
    app = mem_app(
        hello_registry(), tmp_path, InMemoryUsageRecorder(), users=InMemoryUserStore(),
        admin_store=admin, media_access=media,
    )  # fmt: skip
    with TestClient(app) as client:
        client.audit = admin  # type: ignore[attr-defined]
        yield client
    monkeypatch.undo()
    get_settings.cache_clear()


PATH = "/admin/media/wasifyai-music/image.generate"


def test_routes_are_for_admins_only(routes):
    for method, path in [
        ("get", "/admin/media"),
        ("put", PATH),
        ("post", PATH + "/test"),
        ("post", PATH + "/reset"),
    ]:
        assert getattr(routes, method)(path).status_code == 401
        assert getattr(routes, method)(path, headers=USER).status_code == 403


def test_list_save_test_and_reset_through_the_api(routes):
    body = routes.get("/admin/media", headers=ADMIN).json()
    assert [i["capability"] for i in body["items"]] == ["image.generate", "music.generate"]

    saved = routes.put(
        PATH, json={"backend": "comfy-api", "api_key": KEY, "config": {}}, headers=ADMIN
    )
    assert saved.status_code == 200 and saved.json()["key_set"] is True and KEY not in saved.text
    assert KEY not in routes.get("/admin/media", headers=ADMIN).text

    tested = routes.post(PATH + "/test", headers=ADMIN).json()
    assert tested["ok"] is True and KEY not in str(tested)

    reset = routes.post(PATH + "/reset", headers=ADMIN)
    assert reset.status_code == 200 and reset.json()["source"] == "default"


def test_the_audit_log_records_settings_but_never_the_key(routes):
    routes.put(PATH, json={"backend": "comfy-api", "api_key": KEY, "config": {}}, headers=ADMIN)
    routes.post(PATH + "/test", headers=ADMIN)
    routes.post(PATH + "/reset", headers=ADMIN)
    entries = {e.action: e for e in routes.audit.entries}
    assert {"admin.media.update", "admin.media.test", "admin.media.reset"} <= set(entries)
    update = entries["admin.media.update"]
    assert (
        update.target_id == "wasifyai-music/image.generate"
        and update.detail["key_provided"] is True
    )
    assert all(KEY not in e.model_dump_json() for e in routes.audit.entries)


@pytest.mark.parametrize(
    "body",
    [
        {"backend": "nope"},
        {"backend": "comfy-api"},
        {"backend": "openai-images", "config": {"model": "bad model!"}},
    ],
)
def test_bad_input_is_422(routes, body):
    assert routes.put(PATH, json=body, headers=ADMIN).status_code == 422


def test_unknown_capability_is_422(routes):
    r = routes.put(
        "/admin/media/wasifyai-music/video.generate",
        json={"backend": "comfyui-local"},
        headers=ADMIN,
    )
    assert r.status_code == 422
