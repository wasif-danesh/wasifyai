"""Lip sync on the cheaper offers beside fal.ai (ADR-0100, stage CP6): Fabric and InfiniteTalk on
WaveSpeed, Kling Avatar and OmniHuman on Runware, against fakes. The picture and the voice go up
the provider's way; the screen's price per second is the cheapest offer with a key; a refusal
before running hands the job to fal.ai."""

from pathlib import Path

import httpx
import pytest
from wasifyai_api.own_keys_engines import LIPSYNC_PROMPT, KeyedSpeechEngine
from wasifyai_platform_sdk import check_lipsync

from tests.test_own_keys_music_lipsync import (
    KEY,
    Fal,
    LocalVoice,
    a_picture,
    a_wav,
    keys_service,
    mp4,
)
from tests.test_own_keys_wavespeed_runware import Runware, WaveSpeed


async def on(provider: str, model: str, *more: str):
    keys = keys_service()
    for p in (provider, *more):
        await keys.save_key("lipsync", p, KEY)
    await keys.use("lipsync", None, model)
    return keys


def voice_file(tmp_path: Path, seconds: float = 3.0) -> Path:
    v = tmp_path / "v.wav"
    v.write_bytes(a_wav(seconds, 16000))
    return v


@pytest.mark.parametrize(
    ("model", "endpoint", "size", "price"),
    [("fabric-1.0", "veed/fabric-1.0", 480, 0.07),
     ("infinitalk", "wavespeed-ai/infinitetalk", 480, 0.03)],
)  # fmt: skip
async def test_fabric_and_infinitetalk_on_wavespeed(tmp_path, model, endpoint, size, price):
    ws = WaveSpeed(mp4(640, 640), "video/mp4")
    keys = await on("wavespeed", model)
    engine = KeyedSpeechEngine(LocalVoice(), keys, ws.client, poll_s=0)
    m = engine.resolve("lipsync", None)
    assert m.lipsync["where"] == "WaveSpeed" and m.lipsync["price_per_s"][str(size)] == price
    req = check_lipsync(m, 3.0, picture=(1024, 924), shape="1:1", size=size)
    res = await engine.lipsync(m, req, a_picture(tmp_path), voice_file(tmp_path))
    ((url, body),) = ws.posts()
    assert url == f"https://api.wavespeed.ai/api/v3/{endpoint}"
    assert body["image"] == "https://d1.wavespeed.ai/in/0"
    assert body["audio"] == "https://d1.wavespeed.ai/in/1"
    assert body["resolution"] == "480p"
    assert ("prompt" in body) is (model == "infinitalk")
    assert [u["content_type"] for u in ws.uploads] == ["image/png", "audio/wav"]
    assert res.model_id == endpoint and (res.width, res.height) == (640, 640)


@pytest.mark.parametrize(
    ("model", "air", "price"),
    [("kling-avatar-v2", "klingai:avatar@2.0-standard", 0.044),
     ("omnihuman-1.5", "bytedance:5@2", 0.132)],
)  # fmt: skip
async def test_kling_and_omnihuman_on_runware(tmp_path, model, air, price):
    rw = Runware("videoURL", mp4(720, 720), "video/mp4")
    keys = await on("runware", model)
    engine = KeyedSpeechEngine(LocalVoice(), keys, rw.client, poll_s=0)
    m = engine.resolve("lipsync", None)
    assert m.lipsync["where"] == "Runware" and m.lipsync["price_per_s"]["720"] == price
    req = check_lipsync(m, 3.0, picture=(1024, 924), shape="1:1", size=720)
    await engine.lipsync(m, req, a_picture(tmp_path), voice_file(tmp_path))
    (task,) = [t for t in rw.tasks() if t["taskType"] == "videoInference"]
    assert task["model"] == air and task["positivePrompt"] == LIPSYNC_PROMPT
    assert task["inputs"]["image"].startswith("data:image/png;base64,")  # inside the task
    assert task["inputs"]["audio"] == "media-0"  # the voice went up first
    assert rw.stored[0].startswith("data:audio/wav;base64,") and task["includeCost"] is True


async def test_the_cheaper_offer_is_shown_and_a_refusal_before_running_goes_to_fal(tmp_path):
    fal = Fal({"video": {"url": "https://v3.fal.media/v.mp4"}}, mp4(720, 720))
    hosts: list[str] = []

    def both(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        if req.url.host == "api.runware.ai":
            return httpx.Response(401, json={"errors": [{"message": "Invalid API key"}]})
        return fal(req)

    keys = await on("runware", "kling-avatar-v2", "fal")
    engine = KeyedSpeechEngine(
        LocalVoice(), keys, lambda: httpx.AsyncClient(transport=httpx.MockTransport(both)), poll_s=0
    )
    m = engine.resolve("lipsync", None)
    assert m.lipsync["where"] == "Runware" and m.lipsync["price_per_s"]["720"] == 0.044
    req = check_lipsync(m, 3.0, picture=(1024, 924), shape="1:1", size=720)
    res = await engine.lipsync(m, req, a_picture(tmp_path), voice_file(tmp_path))
    assert hosts[0] == "api.runware.ai" and "queue.fal.run" in hosts
    assert res.model_id == "fal-ai/kling-video/ai-avatar/v2/standard"
