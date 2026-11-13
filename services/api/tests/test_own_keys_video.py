"""Video on the cloud models (ADR-0100, stage CP5): each model of the Video table makes, animates
and extends a clip on each of its offers, against fakes of Runware, WaveSpeed and fal.ai; a job an
offer cannot take goes to the one that can before anything is sent; Extend answers the clip it was
sent with the new part after it (`extended`), which the video product joins."""

import base64
import json

import httpx
import pytest
from wasifyai_api.own_keys import OwnKeysService, Provider, Tried
from wasifyai_api.own_keys_catalogue import CATALOGUE
from wasifyai_api.own_keys_media import KeyedMediaRouter
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import InMemorySecretStore, JobRequest

from tests.test_own_keys_engines import Fal
from tests.test_own_keys_wavespeed_runware import Runware, WaveSpeed

CLIP = b"\0\0\0\x18ftypmp42" + b"0" * 64  # what the providers answer; never opened here
PIC = b"\x89PNG\r\n\x1a\n" + b"0" * 32

VIDEO = {m.model: m for m in CATALOGUE if m.product == "video"}
VERB = {"make": "video.generate", "animate": "video.animate", "extend": "video.extend"}


async def accept(provider: Provider, model: str, key: str, base: str) -> Tried:
    return Tried(True, 1)


def job(capability: str, seconds: int = 5) -> JobRequest:
    return JobRequest(
        tenant_id="local", product_id="wasifyai-video", user_id="u1", capability=capability,
        workflow="w", prompt={}, inputs={"prompt": "A fox runs", "length": seconds * 24 + 1,
                                        "width": 1280, "height": 720, "seed": 3},
        outputs={"video": {"node": "1", "type": "video"}},
    )  # fmt: skip


def files_for(capability: str) -> dict[str, bytes]:
    return {"video.animate": {"image": PIC}, "video.extend": {"video": CLIP}}.get(capability, {})


def fake(provider: str):
    if provider == "runware":
        return Runware("videoURL", CLIP, "video/mp4")
    if provider == "wavespeed":
        return WaveSpeed(CLIP, "video/mp4")
    return Fal({"video": {"url": "https://files.example/out.mp4"}}, CLIP)


def sent(provider: str, f) -> tuple[str, dict]:
    """The one request that asked for the clip: where it went and what it said."""
    if provider == "runware":
        (task,) = [t for t in f.tasks() if t["taskType"] == "videoInference"]
        return task["model"], task
    (one,) = f.posts()
    return one


# what Runware's video models take beyond the clip itself: a field one does not take is refused
# (found in CP13)
RUNWARE_TAKES = {
    "seedance-2.5": {"seed", "audio"}, "gemini-omni-flash-1.2": set(),
    "minimax-h3-max": {"seed"}, "minimax-h3-max-turbo": {"seed"},
    "grok-imagine-video-1.5-lite": set(),
}  # fmt: skip

CASES = [
    (m.model, o.provider, verb)
    for m in VIDEO.values()
    for o in m.offers
    for verb in ("make", *sorted(o.can))
]


async def keyed(provider: str, model: str) -> OwnKeysService:
    keys = OwnKeysService(
        InMemorySettingsStore(), InMemorySecretStore(), {"text": accept, "media": accept}
    )
    await keys.save_key("video", provider, "k")
    await keys.use("video", None, model)
    return keys


async def _progress(_p: float) -> None:
    return None


def test_the_video_table_is_the_catalogue():
    assert set(VIDEO) == {
        "gemini-omni-flash-1.2", "seedance-2.5", "minimax-h3-max", "minimax-h3-max-turbo",
        "grok-imagine-video-1.5-lite",
    }  # fmt: skip
    extend = {m: sorted(o.provider for o in VIDEO[m].offers if "extend" in o.can) for m in VIDEO}
    assert extend == {
        "gemini-omni-flash-1.2": ["runware"], "seedance-2.5": ["runware", "wavespeed"],
        "minimax-h3-max": ["fal"], "minimax-h3-max-turbo": ["fal"],
        "grok-imagine-video-1.5-lite": [],
    }  # fmt: skip
    assert all(all("animate" in o.can for o in m.offers) for m in VIDEO.values())


@pytest.mark.parametrize(("model", "provider", "verb"), CASES)
async def test_each_offer_makes_animates_and_extends_what_it_can(model, provider, verb):
    capability = VERB[verb]
    keys = await keyed(provider, model)
    f = fake(provider)
    async with f.client() as http:
        runner = await KeyedMediaRouter(object(), keys, http, 60, 0).resolve(job(capability))
        out = await runner.run(job(capability), _progress, files_for(capability))
    offer = next(o for o in VIDEO[model].offers if o.provider == provider)
    where, body = sent(provider, f)
    if provider == "runware":
        assert where == offer.endpoint and body["includeCost"] is True
        takes = RUNWARE_TAKES[model]
        assert ("seed" in body) == ("seed" in takes)
        if "audio" in takes:
            assert body["settings"]["audio"] is False  # no sound: the video product has none
        else:
            assert "audio" not in body.get("settings", {})
        if verb == "animate":
            (first,) = body["inputs"]["frameImages"]
            assert first["frame"] == "first" and first["image"].startswith("data:image/png")
        if verb == "extend":
            # a clip goes up first (`mediaStorage`) and is named by its id
            assert body["inputs"]["video"] == "media-0"
            assert isinstance(f, Runware) and f.stored == [
                f"data:video/mp4;base64,{base64.b64encode(CLIP).decode()}"
            ]
    else:
        base = (
            "https://api.wavespeed.ai/api/v3/"
            if provider == "wavespeed"
            else "https://queue.fal.run/"
        )
        assert where == base + offer.endpoint_for(verb)
        picture = body.get("image") or body.get("image_url")
        clip = body.get("video") or body.get("video_url")
        assert (picture is not None) is (verb == "animate")
        assert (clip is not None) is (verb == "extend")
    # the length asked for, within what the model takes
    duration = body["duration"]
    assert 1 <= float(duration) <= 30
    # Seedance answers only the new part (CP13); every other offer, the clip and then the new part
    name = "video" if verb != "extend" else ("continued" if model == "seedance-2.5" else "extended")
    assert list(out) == [name] and out[name][1] == "video/mp4"
    assert runner.cost.offer.provider == provider
    assert runner.cost.cost == pytest.approx(offer.price.amount * (5 + 1 / 24), abs=1e-6)


@pytest.mark.parametrize(
    ("model", "shortest"),
    [("gemini-omni-flash-1.2", 3), ("seedance-2.5", 4), ("minimax-h3-max", 5),
     ("minimax-h3-max-turbo", 5), ("grok-imagine-video-1.5-lite", 1)],
)  # fmt: skip
def test_a_clip_shorter_than_a_model_makes_costs_its_shortest(model, shortest):
    """A one-second ask is made at the model's shortest length, and costs that (CP13: the cost
    was first written for the second asked for)."""
    for o in VIDEO[model].offers:
        assert o.price.of({"seconds": 1.0}) == pytest.approx(o.price.amount * shortest)


@pytest.mark.parametrize("model", ["minimax-h3-max", "minimax-h3-max-turbo"])
async def test_h3_extends_on_fal_even_when_runware_is_cheaper_or_tied(model):
    keys = await keyed("runware", model)
    await keys.save_key("video", "fal", "fk")
    hosts: list[str] = []
    rw, fal = Runware("videoURL", CLIP, "video/mp4"), fake("fal")

    def both(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        return rw(req) if req.url.host.endswith("runware.ai") else fal(req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(both)) as http:
        router = KeyedMediaRouter(object(), keys, http, 60, 0)
        runner = await router.resolve(job("video.extend"))
        await runner.run(job("video.extend"), _progress, {"video": CLIP})
        assert runner.cost.offer.provider == "fal" and "api.runware.ai" not in hosts
        runner = await router.resolve(job("video.generate"))
        await runner.run(job("video.generate"), _progress)
        assert runner.cost.offer.provider == "runware"  # the tie goes to Runware


async def test_grok_video_cannot_extend_and_nothing_is_sent():
    keys = await keyed("fal", "grok-imagine-video-1.5-lite")
    f = fake("fal")
    async with f.client() as http:
        runner = await KeyedMediaRouter(object(), keys, http, 60, 0).resolve(job("video.extend"))
        with pytest.raises(Exception, match="cannot do extend"):
            await runner.run(job("video.extend"), _progress, {"video": CLIP})
    assert f.requests == []


async def test_the_cloud_tab_says_which_clips_a_model_can_extend_with_the_keys_there_are():
    keys = await keyed("runware", "seedance-2.5")
    rows = {m["model"]: m for m in (await keys.cloud("video"))["models"]}
    assert rows["seedance-2.5"]["can"] == ["video.generate", "video.animate", "video.extend"]
    assert rows["minimax-h3-max"]["can"] == ["video.generate", "video.animate"]  # fal.ai extends
    # Runware's price, measured in CP13
    assert rows["grok-imagine-video-1.5-lite"]["price"] == "$0.04 per second"


async def test_seedance_extends_on_wavespeed_with_the_clip_uploaded_first():
    keys = await keyed("wavespeed", "seedance-2.5")
    ws = WaveSpeed(CLIP, "video/mp4")
    async with ws.client() as http:
        runner = await KeyedMediaRouter(object(), keys, http, 60, 0).resolve(job("video.extend"))
        await runner.run(job("video.extend"), _progress, {"video": CLIP})
    ((url, body),) = ws.posts()
    assert url.endswith("/bytedance/seedance-2.5/video-extend")
    assert body["video"] == "https://d1.wavespeed.ai/in/0" and body["generate_audio"] is False
    assert [u["content_type"] for u in ws.uploads] == ["video/mp4"]
    assert json.loads(ws.requests[0].content)["filename"] == "clip.mp4"


async def test_a_clip_runware_will_not_keep_goes_to_the_next_offer_before_anything_runs():
    keys = await keyed("runware", "seedance-2.5")
    await keys.save_key("video", "wavespeed", "wk")
    ws = WaveSpeed(CLIP, "video/mp4")
    asked: list[str] = []

    def both(req: httpx.Request) -> httpx.Response:
        if req.url.host == "api.runware.ai":
            asked.append(json.loads(req.content)[0]["taskType"])
            return httpx.Response(400, json={"errors": [{"message": "Media too large"}]})
        return ws(req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(both)) as http:
        runner = await KeyedMediaRouter(object(), keys, http, 60, 0).resolve(job("video.extend"))
        await runner.run(job("video.extend"), _progress, {"video": CLIP})
    assert asked == ["mediaStorage"]  # the clip was refused; nothing was made there
    assert runner.cost.offer.provider == "wavespeed"
