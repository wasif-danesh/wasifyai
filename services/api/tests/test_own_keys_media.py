"""Images and video follow Settings › Your keys (ADR-0095, stage K3; ADR-0100, stage CP3): a job of
a product on a cloud model runs on the cheapest of that model's offers with a key; every other job
stays here; a change applies to the next job. A key saved under "Every media product" serves them
all, and a product's own key for the same provider wins."""

import httpx
import pytest
from wasifyai_api.own_keys import OwnKeysService, Provider, Tried
from wasifyai_api.own_keys_media import KeyedMediaRouter
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_media_worker.backends import CloudChoice, OfferRunner, RecipeRunner
from wasifyai_platform_sdk import InMemorySecretStore, JobRequest
from wasifyai_platform_sdk.offers import offer


async def accept(provider: Provider, model: str, key: str, base: str) -> Tried:
    return Tried(True, 1)


def job(product: str, capability: str, **inputs) -> JobRequest:
    return JobRequest(
        tenant_id="local", product_id=product, user_id="u1", capability=capability,
        workflow="w", prompt={}, inputs={"prompt": "x", **inputs},
        outputs={"image": {"node": "1", "type": "image"}},
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


async def test_a_product_on_a_cloud_model_runs_its_offers_with_its_own_key():
    router, keys, local = rig()
    await keys.save_key("images", "fal", "img-key")
    await keys.use("images", None, "flux-3-klein")
    await keys.save_key("video", "fal", "vid-key")
    await keys.use("video", None, "minimax-h3-max")
    pic = await router.resolve(job("wasifyai-image", "image.generate"))
    clip = await router.resolve(job("wasifyai-video", "video.animate"))
    assert isinstance(pic, OfferRunner) and isinstance(clip, OfferRunner)
    assert pic.local_gpu is False  # the processor takes no GPU lock for it
    fal_pic = pic._runner(pic._choices[0])
    fal_clip = clip._runner(clip._choices[0])
    # a catalogue model goes out as its recipe for the provider (CP4, CP5)
    assert isinstance(fal_pic, RecipeRunner) and isinstance(fal_clip, RecipeRunner)
    assert fal_pic.backend == "fal" and fal_pic._queue._headers == {"Authorization": "Key img-key"}
    assert fal_pic._offer.endpoint_for("edit") == "blackforestlabs/flux-3/klein/edit-image"
    assert fal_clip._offer.endpoint_for("extend") == "minimax/h3-max/extend-video"
    assert fal_clip._queue._headers == {"Authorization": "Key vid-key"}
    # other products are not affected by these keys
    assert await router.resolve(job("wasifyai-voice", "music.generate")) is local


async def test_back_to_this_computer_applies_to_the_next_job():
    router, keys, local = rig()
    await keys.save_key("images", "fal", "img-key")
    await keys.use("images", None, "flux-3-klein")
    assert isinstance(await router.resolve(job("wasifyai-image", "image.generate")), OfferRunner)
    await keys.use("images", None, None)
    assert await router.resolve(job("wasifyai-image", "image.generate")) is local
    await keys.use("images", None, "flux-3-klein")  # the key stayed saved
    await keys.remove_key("images", "fal")
    assert await router.resolve(job("wasifyai-image", "image.generate")) is local


async def test_one_key_under_every_media_product_serves_them_all_and_a_products_own_wins():
    router, keys, local = rig()
    await keys.save_key("media", "fal", "shared-key")
    view = {p["id"]: p for p in (await keys.view())["products"]}
    assert [k["provider"] for k in view["media"]["keys"]] == ["fal"]
    cloud = await keys.cloud("lipsync")
    assert cloud["has_keys"] and len(cloud["models"]) == 4  # offered with no key of its own
    await keys.use("images", None, "flux-3-klein")
    route = await keys.route("images")
    assert route is not None and route.key == "shared-key"
    await keys.save_key("images", "fal", "own-key")
    route = await keys.route("images")
    assert route is not None and route.key == "own-key"
    # a model none of the keys can run is refused in words
    with pytest.raises(Exception, match="Nano Banana 2.1 needs a Runware or WaveSpeed key"):
        await keys.use("images", None, "nano-banana-2.1")
    # the shared key gone, its products run here again (unless they have their own)
    await keys.remove_key("images", "fal")
    await keys.remove_key("media", "fal")
    assert await router.resolve(job("wasifyai-image", "image.generate")) is local


async def test_the_cloud_tab_says_when_another_key_would_be_cheaper():
    _, keys, _ = rig()
    await keys.save_key("music", "fal", "k")
    (minimax, *_) = (await keys.cloud("music"))["models"]
    assert minimax["model"] == "minimax-music-2.6" and minimax["providers"] == ["fal"]
    assert minimax["cheaper_with"] is None  # a tie is not cheaper
    await keys.save_key("music", "runware", "k2")
    (minimax, *_) = (await keys.cloud("music"))["models"]
    assert minimax["providers"] == ["runware", "fal"]  # the tie goes to Runware
    assert minimax["provider_title"] == "Runware" and minimax["price"] == "$0.15 per song"


# ---- the router of a picture: the cheapest offer, the next on a refusal before running ---------


def a_png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * 32


class Providers:
    """fal.ai and WaveSpeed as fakes; `refuse` answers a provider's requests with that status."""

    def __init__(self, refuse: dict[str, int] | None = None):
        self.refuse = refuse or {}
        self.hosts: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        host = req.url.host
        self.hosts.append(host)
        if host in self.refuse:
            return httpx.Response(self.refuse[host], json={"detail": "no", "message": "no"})
        if host == "files.example":
            return httpx.Response(200, content=a_png(), headers={"content-type": "image/png"})
        if host == "api.wavespeed.ai":
            if req.method == "POST":
                return httpx.Response(200, json={"data": {"id": "p1"}})
            return httpx.Response(200, json={"data": {
                "status": "completed", "outputs": ["https://files.example/a.png"]}})  # fmt: skip
        # fal.ai's queue: submitted, done, the result
        path = req.url.path
        if req.method == "POST":
            return httpx.Response(200, json={
                "request_id": "r1", "status_url": "https://queue.fal.run/x/requests/r1/status",
                "response_url": "https://queue.fal.run/x/requests/r1"})  # fmt: skip
        if path.endswith("/status"):
            return httpx.Response(200, json={"status": "COMPLETED"})
        return httpx.Response(200, json={"images": [{"url": "https://files.example/a.png"}]})


def choices() -> list[CloudChoice]:
    return [
        CloudChoice(
            "fal", "fk", "https://queue.fal.run", offer("fal", "fal-ai/m", 0.009, "picture")
        ),
        CloudChoice(
            "wavespeed", "wk", "https://api.wavespeed.ai/api/v3",
            offer("wavespeed", "ws/m", 0.005, "picture"),
        ),
    ]  # fmt: skip


async def _progress(_p: float) -> None:
    return None


async def test_a_picture_runs_on_the_cheapest_offer_and_its_price_is_kept():
    fake = Providers()
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as http:
        runner = OfferRunner("m", "Model", choices(), http, 60, 0)
        files = await runner.run(job("wasifyai-image", "image.generate"), _progress)
    assert files["image"][1] == "image/png"
    assert fake.hosts[0] == "api.wavespeed.ai" and "queue.fal.run" not in fake.hosts
    assert runner.cost is not None
    assert (runner.cost.offer.provider, runner.cost.cost) == ("wavespeed", 0.005)
    assert runner.backend == "wavespeed"


async def test_a_refusal_before_running_goes_to_the_next_offer():
    fake = Providers(refuse={"api.wavespeed.ai": 401})
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as http:
        runner = OfferRunner("m", "Model", choices(), http, 60, 0)
        await runner.run(job("wasifyai-image", "image.generate"), _progress)
    assert fake.hosts[0] == "api.wavespeed.ai" and "queue.fal.run" in fake.hosts
    assert runner.cost is not None and runner.cost.offer.provider == "fal"


async def test_a_job_that_may_have_run_is_not_sent_again():
    fake = Providers(refuse={"api.wavespeed.ai": 500})
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as http:
        runner = OfferRunner("m", "Model", choices(), http, 60, 0)
        with pytest.raises(Exception):  # noqa: B017 - the worker retries a busy service itself
            await runner.run(job("wasifyai-image", "image.generate"), _progress)
    assert "queue.fal.run" not in fake.hosts and runner.cost is None


async def test_z_image_paints_on_fal_with_the_picture_and_mask_in_its_file_store():
    from tests.test_own_keys_engines import Fal

    fal = Fal({"images": [{"url": "https://files.example/out.png"}]}, a_png())
    _, keys, _ = rig()
    await keys.save_key("images", "fal", "img-key")
    await keys.use("images", None, "z-image-turbo")
    route = await keys.route("images")
    assert route is not None
    async with fal.client() as http:
        runner = await KeyedMediaRouter(object(), keys, http, 60, 0).resolve(  # type: ignore[arg-type]
            job("wasifyai-image", "image.inpaint")
        )
        await runner.run(
            job("wasifyai-image", "image.inpaint"), _progress, {"image": a_png(), "mask": a_png()}
        )
    ((url, body),) = fal.posts()
    assert url == "https://queue.fal.run/fal-ai/z-image/turbo/inpaint"
    assert body["image_url"] == "https://v3.fal.media/files/in0"
    assert body["mask_image_url"] == "https://v3.fal.media/files/in1"
    assert runner.cost.offer.provider == "fal" and runner.cost.cost == 0.005


async def test_the_cloud_tab_says_what_each_picture_model_can_do_with_the_keys_there_are():
    _, keys, _ = rig()
    await keys.save_key("images", "wavespeed", "k")
    rows = {m["model"]: m for m in (await keys.cloud("images"))["models"]}
    assert rows["gpt-image-2.5"]["can"] == [
        "image.generate", "image.edit", "image.reference", "image.inpaint",
    ]  # fmt: skip
    assert rows["nano-banana-2.1"]["can"] == ["image.generate", "image.edit", "image.reference"]
    assert "z-image-turbo" not in rows  # no WaveSpeed offer
