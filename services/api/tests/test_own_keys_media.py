"""Images and video follow Settings › Your keys (ADR-0095, stage K3): a job of a product on a key
goes to fal.ai with that key; every other job stays here; a change applies to the next job."""

from wasifyai_api.own_keys import OwnKeysService, Provider, Tried
from wasifyai_api.own_keys_media import KeyedMediaRouter
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_media_worker.backends import FalRunner
from wasifyai_platform_sdk import InMemorySecretStore, JobRequest


async def accept(provider: Provider, model: str, key: str, base: str) -> Tried:
    return Tried(True, 1)


def job(product: str, capability: str) -> JobRequest:
    return JobRequest(
        tenant_id="local", product_id=product, user_id="u1", capability=capability,
        workflow="w", prompt={}, inputs={"prompt": "x"}, outputs={"image": {"node": "1"}},
    )  # fmt: skip


def rig():
    keys = OwnKeysService(
        InMemorySettingsStore(), InMemorySecretStore(), {"text": accept, "media": accept}
    )
    local = object()
    return KeyedMediaRouter(local, keys, http=None, timeout_s=60), keys, local  # type: ignore[arg-type]


async def test_with_no_key_every_job_stays_on_this_computer():
    router, _, local = rig()
    for product, cap in (
        ("wasifyai-image", "image.generate"),
        ("wasifyai-video", "video.generate"),
    ):
        assert await router.resolve(job(product, cap)) is local


async def test_a_product_on_its_key_runs_on_fal_with_its_own_model_and_key():
    router, keys, local = rig()
    await keys.save("images", "key", "fal", "fal-ai/flux-2", None, "img-key")
    await keys.save("video", "key", "fal", "fal-ai/ltx-2/text-to-video/fast", None, "vid-key")
    pic = await router.resolve(job("wasifyai-image", "image.generate"))
    clip = await router.resolve(job("wasifyai-video", "video.animate"))
    assert isinstance(pic, FalRunner) and isinstance(clip, FalRunner)
    assert pic._model == "fal-ai/flux-2" and pic._headers == {"Authorization": "Key img-key"}
    assert clip._model == "fal-ai/ltx-2/text-to-video/fast"
    assert clip._headers == {"Authorization": "Key vid-key"}
    assert pic.local_gpu is False  # the processor takes no GPU lock for it
    # other products are not affected by these keys
    assert await router.resolve(job("wasifyai-voice", "music.generate")) is local


async def test_back_to_this_computer_applies_to_the_next_job():
    router, keys, local = rig()
    await keys.save("images", "key", "fal", "fal-ai/flux-2", None, "img-key")
    assert isinstance(await router.resolve(job("wasifyai-image", "image.generate")), FalRunner)
    await keys.save("images", "here", None, None, None, None)
    assert await router.resolve(job("wasifyai-image", "image.generate")) is local
    await keys.save("images", "key", "fal", "fal-ai/flux-2", None, None)  # the key stayed saved
    await keys.remove("images")
    assert await router.resolve(job("wasifyai-image", "image.generate")) is local
