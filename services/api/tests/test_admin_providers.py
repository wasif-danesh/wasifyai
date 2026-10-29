"""The web's media on the provider the admin chose (ADR-0095, stage K5): fal.ai in Admin › Media for
pictures and clips (run by the media worker), for speaking and for 3D models (run by the API); a
key shared between rows; the last test of each row; what people see on the model button."""

from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from wasifyai_api.admin_providers import AdminProviders
from wasifyai_api.logging import tenant_id as current_tenant
from wasifyai_api.media_access import (
    API_ROWS,
    MediaAccess,
    MediaAccessError,
    MediaBindingIn,
    MediaCapability,
    media_capabilities_from,
)
from wasifyai_api.models_in_use import in_use
from wasifyai_api.own_keys_engines import KEYED_VOICE, KeyedModel3d, KeyedSpeechEngine
from wasifyai_api.services import ApiServices
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import InMemoryMediaBindingStore, SecretBox

from tests.test_own_keys_engines import WAV, Fal, Local3d, LocalSpeech

KEY = "fal-admin-key-123"
T = "t1"
CAPS = [
    MediaCapability(product_id="wasifyai-image", capability="image.generate", workflow="flux2"),
    MediaCapability(product_id="wasifyai-image", capability="image.inpaint", workflow="inpaint"),
    MediaCapability(product_id="wasifyai-video", capability="video.generate", workflow="ltx"),
    *(MediaCapability(product_id=p, capability=c) for p, c in API_ROWS),
]


def fal_status(status: int):
    seen: list[httpx.Request] = []

    def answer(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, json={})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer)), seen


def rig(status: int = 404):
    box = SecretBox(SecretBox.generate_key())
    store = InMemoryMediaBindingStore()
    providers = AdminProviders(store, box, T)
    http, seen = fal_status(status)
    media = MediaAccess(
        store, box, lambda: CAPS, "http://c", http, checks=InMemorySettingsStore(),
        changed=providers.changed,
    )  # fmt: skip
    return media, providers, seen


def fal(model: str, key: str | None = KEY, key_from: str | None = None) -> MediaBindingIn:
    return MediaBindingIn(backend="fal", config={"model": model}, api_key=key, key_from=key_from)


@pytest.fixture(autouse=True)
def tenant():
    token = current_tenant.set(T)
    yield
    current_tenant.reset(token)


# ---- the rows ----------------------------------------------------------------------------------


async def test_speaking_and_3d_are_rows_that_start_on_the_engine_workers():
    media, _, _ = rig()
    rows = {(i.product_id, i.capability): i for i in (await media.list(T)).items}
    for pid, cap in API_ROWS:
        assert rows[pid, cap].backend == "engine-workers" and rows[pid, cap].source == "default"
        assert set(rows[pid, cap].allowed_backends) == {"engine-workers", "fal"}
    assert "fal" in rows["wasifyai-image", "image.generate"].allowed_backends
    assert "fal" not in rows["wasifyai-image", "image.inpaint"].allowed_backends


def test_the_api_rows_appear_only_for_products_that_are_there(tmp_path):
    registry = SimpleNamespace(products=lambda: ["wasifyai-voice"])
    found = media_capabilities_from(registry, tmp_path, "dev")
    assert [(c.product_id, c.capability) for c in found] == [("wasifyai-voice", "speech.speak")]


async def test_a_row_may_use_the_key_saved_for_another_fal_row():
    media, _, seen = rig()
    await media.set(T, "wasifyai-image", "image.generate", fal("fal-ai/flux-2"), "admin")
    view = await media.set(
        T, "wasifyai-voice", "speech.speak",
        fal("fal-ai/kokoro", key=None, key_from="wasifyai-image/image.generate"), "admin",
    )  # fmt: skip
    assert view.backend == "fal" and view.key_set and view.config == {"model": "fal-ai/kokoro"}
    out = await media.test(T, "wasifyai-voice", "speech.speak", None)
    assert out.ok and seen[-1].headers["authorization"] == f"Key {KEY}"  # the same key, copied


async def test_a_key_can_only_be_borrowed_from_a_row_of_the_same_service():
    media, _, _ = rig()
    with pytest.raises(MediaAccessError, match="no key saved"):
        await media.set(
            T, "wasifyai-voice", "speech.speak",
            fal("fal-ai/kokoro", key=None, key_from="wasifyai-image/image.generate"), "admin",
        )  # fmt: skip


async def test_the_last_test_of_a_saved_row_is_its_state_until_the_key_changes():
    media, _, _ = rig(status=401)
    await media.set(T, "wasifyai-model3d", "model3d.generate", fal("fal-ai/pixal3d"), "admin")
    assert (await media.get(T, "wasifyai-model3d", "model3d.generate")).check is None
    out = await media.test(T, "wasifyai-model3d", "model3d.generate", None)
    assert not out.ok and out.message == "fal.ai did not accept the key"
    view = await media.get(T, "wasifyai-model3d", "model3d.generate")
    assert view.check is not None and not view.check.ok
    assert view.check.message == "fal.ai did not accept the key"
    # a new key has not been tested yet: the old answer goes
    await media.set(
        T, "wasifyai-model3d", "model3d.generate", fal("fal-ai/pixal3d", key="new-key"), "admin"
    )
    assert (await media.get(T, "wasifyai-model3d", "model3d.generate")).check is None


async def test_a_proposed_row_is_tested_without_keeping_the_answer():
    media, _, _ = rig(status=401)
    await media.test(T, "wasifyai-voice", "speech.speak", fal("fal-ai/kokoro"))
    assert (await media.get(T, "wasifyai-voice", "speech.speak")).check is None


# ---- speaking and 3D follow the rows -----------------------------------------------------------


async def test_saving_a_row_moves_speaking_to_fal_at_once_and_reset_moves_it_back():
    media, providers, _ = rig()
    speech = KeyedSpeechEngine(LocalSpeech(), providers, admin=True)
    assert speech.models("speak")[0]["id"] == "kokoro-82m"  # the engine workers
    await media.set(T, "wasifyai-voice", "speech.speak", fal("fal-ai/kokoro"), "admin")
    (only,) = speech.models("speak")
    assert only["id"] == KEYED_VOICE and only["title"] == "fal-ai/kokoro · fal.ai"
    await media.reset(T, "wasifyai-voice", "speech.speak")
    assert speech.models("speak")[0]["id"] == "kokoro-82m"


async def test_speech_runs_on_fal_with_the_admins_key():
    media, providers, _ = rig()
    await media.set(T, "wasifyai-voice", "speech.speak", fal("fal-ai/kokoro"), "admin")
    queue = Fal({"audio": {"url": "https://v3.fal.media/s.wav"}}, WAV)
    speech = KeyedSpeechEngine(LocalSpeech(), providers, queue.client, poll_s=0, admin=True)
    res = await speech.speak(speech.resolve("speak", None), "Hello.", "af_heart", {})
    assert res.wav == WAV
    assert queue.requests[0].headers["authorization"] == f"Key {KEY}"


async def test_3d_on_fal_says_the_admin_chose_it_and_keeps_the_workers_job_words(tmp_path):
    media, providers, _ = rig()
    await media.set(T, "wasifyai-model3d", "model3d.generate", fal("fal-ai/pixal3d"), "admin")
    queue = Fal({"model_glb": {"url": "https://v3.fal.media/m.glb"}}, b"glTF")
    engine = KeyedModel3d(Local3d(), providers, queue.client, poll_s=0, admin=True)
    assert engine.ready() and "chosen by your admin" in engine.fit()["reason"]
    cutout = tmp_path / "cutout.png"
    cutout.write_bytes(b"\x89PNG")
    # the web's product passes the worker job's key: on fal.ai the run is simply made
    res = await engine.generate(cutout, tmp_path / "m.glb", job_key="row-1", resume=True)
    assert res.ok and (tmp_path / "m.glb").read_bytes() == b"glTF"


async def test_stopping_the_service_reaches_the_workers_engine():
    _, providers, _ = rig()
    local = Local3d()
    engine = KeyedModel3d(local, providers, admin=True)
    engine.closing = True
    assert cast("Any", local).closing is True


async def test_each_tenant_reads_its_own_rows():
    media, providers, _ = rig()
    await media.set(T, "wasifyai-voice", "speech.speak", fal("fal-ai/kokoro"), "admin")
    other = current_tenant.set("t2")
    try:
        assert providers.known("voice") is None
        await providers.refresh("t2")
        assert providers.known("voice") is None
    finally:
        current_tenant.reset(other)
    assert providers.known("voice") is not None


# ---- the model button ----------------------------------------------------------------------------


async def test_the_model_button_names_the_admins_fal_model():
    media, _, _ = rig()
    await media.set(T, "wasifyai-image", "image.generate", fal("fal-ai/flux-2"), "admin")
    await media.set(T, "wasifyai-model3d", "model3d.generate", fal("fal-ai/pixal3d"), "admin")
    services = ApiServices(media=media)
    request = cast(
        "Any", SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=services)))
    )
    out = await in_use(request, cast("Any", SimpleNamespace(tenant_id=T, user_id="u")))
    (picture,) = out.images
    assert picture.title == "FLUX.2 · fal.ai" and picture.ready
    assert picture.plain.startswith("Chosen by your admin.") and "fal.ai" in picture.plain
    assert [m.title for m in out.three_d] == ["Pixal3D · fal.ai"]
