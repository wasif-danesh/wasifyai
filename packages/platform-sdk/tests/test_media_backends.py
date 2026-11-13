import httpx
import pytest
from wasifyai_platform_sdk import (
    BACKENDS,
    InvalidBackendConfig,
    SecretBox,
    SecretsUnavailable,
    backends_for,
    check_backend,
    default_backend,
    family,
    validate_config,
)

KEY = "comfyui-0123456789abcdef0123456789abcdef"


def test_which_backends_can_serve_which_capability():
    assert family("image.generate") == "image" and family("video.generate") == "video"
    assert {b.id for b in backends_for("image.generate")} == {
        "comfyui-local",
        "comfy-api",
        "openai-images",
        "fal",
    }
    assert {b.id for b in backends_for("video.generate")} == {"comfyui-local", "comfy-api", "fal"}
    # fal.ai is not set up for painting over a picture or making a clip longer (ADR-0095)
    assert "fal" not in {b.id for b in backends_for("image.inpaint")}
    assert "fal" not in {b.id for b in backends_for("video.extend")}
    # speech and 3D models: the service's engine workers, or fal.ai
    for cap in ("speech.speak", "model3d.generate"):
        assert {b.id for b in backends_for(cap)} == {"engine-workers", "fal"}
        assert default_backend(cap) == "engine-workers"
    assert default_backend("image.generate") == "comfyui-local"
    assert not BACKENDS["comfy-api"].local_gpu and BACKENDS["comfyui-local"].local_gpu


@pytest.mark.parametrize(
    ("backend", "capability", "config", "key", "saved", "message"),
    [
        ("nope", "image.generate", {}, None, False, "unknown backend"),
        ("openai-images", "video.generate", {"model": "m"}, None, False, "cannot serve"),
        ("comfy-api", "image.generate", {}, None, False, "needs an api key"),
        ("openai-images", "image.generate", {}, None, False, "Model is required"),
        ("openai-images", "image.generate", {"model": "bad model!"}, None, False, "characters"),
        (
            "openai-images",
            "image.generate",
            {"model": "m", "size": "big"},
            None,
            False,
            "1024x1024",
        ),
        ("comfy-api", "image.generate", {"base_url": "ftp://x"}, KEY, False, "http"),
        ("comfy-api", "image.generate", {"base_url": "http://u:p@x"}, KEY, False, "credentials"),
        (
            "comfy-api",
            "image.generate",
            {"base_url": "http://169.254.169.254"},
            KEY,
            False,
            "not allowed",
        ),
        ("comfy-api", "image.generate", {"surprise": "1"}, KEY, False, "unknown setting"),
        ("comfy-api", "image.generate", {}, "two words", False, "one token"),
        ("comfyui-local", "image.generate", {}, KEY, False, "does not use an API key"),
    ],
)
def test_bad_configurations_are_rejected(backend, capability, config, key, saved, message):
    with pytest.raises(InvalidBackendConfig, match=message):
        validate_config(backend, capability, config, key, saved)


def test_good_configurations_come_back_clean_and_without_secrets():
    clean = validate_config(
        "openai-images",
        "image.generate",
        {"base_url": " https://api.example/v1/ ", "model": "gpt-image-1", "size": "1024x1024"},
        KEY,
        False,
    )
    assert clean == {
        "base_url": "https://api.example/v1",
        "model": "gpt-image-1",
        "size": "1024x1024",
    }
    assert KEY not in str(clean)
    assert (
        validate_config("comfy-api", "video.generate", {}, None, True) == {}
    )  # a saved key counts
    assert validate_config("comfyui-local", "image.generate", {}, None, False) == {}


def client(status):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


@pytest.mark.parametrize(
    ("backend", "status", "ok", "words"),
    [
        ("comfyui-local", 200, True, "answered"),
        ("comfyui-local", 500, False, "500"),
        ("comfy-api", 404, True, "accepted"),
        ("comfy-api", 401, False, "rejected"),
        ("comfy-api", 402, False, "no credits"),
        ("comfy-api", 429, False, "subscription"),
        ("openai-images", 200, True, "accepted"),
        ("openai-images", 404, True, "does not list"),
        ("openai-images", 401, False, "rejected"),
    ],
)
async def test_checks_judge_each_backend(backend, status, ok, words):
    http, seen = client(status)
    out = await check_backend(backend, {}, KEY, "http://local:8188", http)
    assert out.ok is ok and words in out.message
    assert KEY not in out.message
    if backend != "comfyui-local":
        assert seen[0].headers["authorization"] == f"Bearer {KEY}"


async def test_checks_use_the_configured_address_and_the_local_default():
    http, seen = client(200)
    await check_backend("comfy-api", {"base_url": "https://serverless.example"}, KEY, "x", http)
    assert str(seen[0].url).startswith("https://serverless.example/api/v2/jobs/")
    await check_backend("comfyui-local", {}, None, "http://local:8188", http)
    assert str(seen[1].url) == "http://local:8188/system_stats"
    await check_backend("comfy-api", {}, KEY, "x", http)
    assert str(seen[2].url).startswith("https://cloud.comfy.org/")


@pytest.mark.parametrize(
    ("status", "ok", "words"),
    [(404, True, "fal.ai accepted the key"), (401, False, "did not accept the key"),
     (403, False, "did not accept the key"), (429, False, "too many requests"),
     (500, False, "answered 500")],
)  # fmt: skip
async def test_a_fal_key_is_checked_without_making_anything(status, ok, words):
    http, seen = client(status)
    out = await check_backend("fal", {"model": "fal-ai/ltx-2/text-to-video/fast"}, KEY, "x", http)
    assert out.ok is ok and words in out.message and KEY not in out.message
    assert str(seen[0].url) == (
        "https://queue.fal.run/fal-ai/ltx-2/requests/00000000-0000-0000-0000-000000000000/status"
    )
    assert seen[0].headers["authorization"] == f"Key {KEY}"


async def test_the_engine_workers_need_no_check():
    http, seen = client(500)
    assert (await check_backend("engine-workers", {}, None, "x", http)).ok and seen == []


def test_fal_needs_a_model_and_a_key_and_is_offered_only_where_it_can_run():
    config = validate_config("fal", "speech.speak", {"model": "fal-ai/kokoro"}, KEY, False)
    assert config == {"model": "fal-ai/kokoro"}
    for capability, cfg, key, words in [
        ("image.generate", {}, KEY, "Model is required"),
        ("image.generate", {"model": "fal-ai/flux-2"}, None, "fal.ai needs an api key"),
        ("image.inpaint", {"model": "fal-ai/flux-2"}, KEY, "cannot serve image.inpaint"),
    ]:
        with pytest.raises(InvalidBackendConfig, match=words):
            validate_config("fal", capability, cfg, key, False)


async def test_an_unreachable_backend_is_reported_not_raised():
    def boom(request):
        raise httpx.ConnectError("no route", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    out = await check_backend("comfy-api", {}, KEY, "x", http)
    assert not out.ok and "unreachable" in out.message and KEY not in out.message


def test_secrets_round_trip_and_never_look_like_the_plain_text():
    box = SecretBox(SecretBox.generate_key())
    token = box.encrypt(KEY)
    assert KEY not in token and box.decrypt(token) == KEY
    assert box.encrypt(KEY) != token  # a fresh nonce every time


def test_secrets_need_the_right_key():
    token = SecretBox(SecretBox.generate_key()).encrypt(KEY)
    other = SecretBox(SecretBox.generate_key())
    with pytest.raises(SecretsUnavailable, match="enter it again"):
        other.decrypt(token)
    for bad in ("", "change-me", "not a key"):
        box = SecretBox(bad)
        assert not box.ready
        with pytest.raises(SecretsUnavailable, match="MEDIA_SECRETS_KEY"):
            box.encrypt("x")
