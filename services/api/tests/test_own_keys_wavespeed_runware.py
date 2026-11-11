"""Music, lip sync and pictures on WaveSpeed and Runware with the person's key
(`docs/own-keys-cloud-tab-plan.md`, CT3), against fakes of both: what each is sent, how the answer
is followed, and that the key goes to the provider only, never to the file's host."""

import io
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from wasifyai_api.own_keys import OwnKeysService, Provider, Tried
from wasifyai_api.own_keys_engines import KEYED_LIPSYNC, KEYED_MUSIC, KeyedSpeechEngine
from wasifyai_api.own_keys_media import KeyedMediaRouter
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import (
    InMemorySecretStore,
    JobRequest,
    VoiceEngineError,
    check_lipsync,
    check_music,
)

KEY = "ws-or-rw-key"


def a_wav(seconds: float, rate: int = 44100) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def mp4(w: int, h: int) -> bytes:
    tkhd = bytes([0]) + b"\0\0\0" + b"\0" * 20 + b"\0" * 52
    tkhd += (w << 16).to_bytes(4, "big") + (h << 16).to_bytes(4, "big")
    return b"\0\0\0\x5ctkhd" + tkhd


def a_png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 64), (1, 2, 3)).save(out, "PNG")
    return out.getvalue()


class WaveSpeed:
    """A fake WaveSpeed: one prediction, processing once, then done (or failed)."""

    def __init__(self, file: bytes, ctype: str, fail: str | None = None):
        self.file, self.ctype, self.fail = file, ctype, fail
        self.requests: list[httpx.Request] = []
        self.polls = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        url = str(req.url)
        if req.method == "POST":
            return httpx.Response(
                200, json={"code": 200, "data": {"id": "p1", "status": "created"}}
            )
        if url.endswith("/predictions/p1/result"):
            self.polls += 1
            if self.polls == 1:
                return httpx.Response(200, json={"data": {"status": "processing", "outputs": []}})
            if self.fail:
                return httpx.Response(200, json={"data": {"status": "failed", "error": self.fail}})
            out = "https://d1.wavespeed.ai/out/file"
            return httpx.Response(200, json={"data": {"status": "completed", "outputs": [out]}})
        return httpx.Response(200, content=self.file, headers={"content-type": self.ctype})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def posts(self) -> list[tuple[str, dict]]:
        return [(str(r.url), json.loads(r.content)) for r in self.requests if r.method == "POST"]


class Runware:
    """A fake Runware: the task is taken, `getResponse` says processing once, then the URL."""

    def __init__(self, field: str, file: bytes, ctype: str):
        self.field, self.file, self.ctype = field, file, ctype
        self.requests: list[httpx.Request] = []
        self.task = ""
        self.asks = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if str(req.url) == "https://api.runware.ai/v1":
            (task,) = json.loads(req.content)
            if task["taskType"] == "getResponse":
                self.asks += 1
                if self.asks == 1:
                    return httpx.Response(
                        200, json={"data": [{"taskUUID": self.task, "status": "processing"}]}
                    )
                url = "https://im.runware.ai/out/file"
                return httpx.Response(
                    200, json={"data": [{"taskUUID": self.task, self.field: url}]}
                )
            self.task = task["taskUUID"]
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, content=self.file, headers={"content-type": self.ctype})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def tasks(self) -> list[dict]:
        return [json.loads(r.content)[0] for r in self.requests if r.method == "POST"]


async def accept(provider: Provider, model: str, key: str, base: str) -> Tried:
    return Tried(True, 1)


async def on(product: str, provider: str, model: str) -> OwnKeysService:
    keys = OwnKeysService(
        InMemorySettingsStore(), InMemorySecretStore(), {"text": accept, "media": accept}
    )
    await keys.save_key(product, provider, KEY)
    await keys.use(product, provider, model)
    return keys


class LocalVoice:
    def models(self, task=None):
        return []

    def resolve(self, task, model_id):
        return SimpleNamespace(id=model_id or f"local:{task}", tasks=(task,))


def key_only_to_provider(requests: list[httpx.Request], host: str) -> None:
    for r in requests:
        to_provider = r.url.host == host
        assert (r.headers.get("authorization") == f"Bearer {KEY}") is to_provider


# ---- WaveSpeed ----------------------------------------------------------------------------------


async def test_a_song_on_wavespeed_goes_to_its_minimax_and_is_followed_to_the_end():
    ws = WaveSpeed(a_wav(3.0), "audio/wav")
    keys = await on("music", "wavespeed", "minimax/music-2.6")
    engine = KeyedSpeechEngine(LocalVoice(), keys, ws.client, poll_s=0)
    model = engine.resolve("music", None)
    assert model.id == KEYED_MUSIC and model.family == "wavespeed"
    req = check_music(model, "song", "Warm city pop at night", "La la la", False, None, None, None)
    res = await engine.music(model, req)
    assert ws.posts() == [(
        "https://api.wavespeed.ai/api/v3/minimax/music-2.6",
        {"prompt": "Warm city pop at night", "is_instrumental": False, "lyrics": "La la la"},
    )]  # fmt: skip
    assert ws.polls == 2 and res.seconds == pytest.approx(3.0)
    key_only_to_provider(ws.requests, "api.wavespeed.ai")


async def test_lip_sync_on_wavespeed_sends_the_picture_and_voice_and_keeps_the_video(
    tmp_path: Path,
):
    ws = WaveSpeed(mp4(720, 1280), "video/mp4")
    keys = await on("lipsync", "wavespeed", "wavespeed-ai/infinitetalk")
    engine = KeyedSpeechEngine(LocalVoice(), keys, ws.client, poll_s=0)
    model = engine.resolve("lipsync", None)
    assert model.id == KEYED_LIPSYNC and model.lipsync["max_voice_s"] == 600.0
    req = check_lipsync(model, 90.0, picture=(1024, 924), shape="9:16", size=720)
    picture, voice = tmp_path / "f.png", tmp_path / "v.wav"
    Image.new("RGB", (1024, 924)).save(picture)
    voice.write_bytes(a_wav(2.0, 16000))
    res = await engine.lipsync(model, req, picture, voice)
    ((url, body),) = ws.posts()
    assert url == "https://api.wavespeed.ai/api/v3/wavespeed-ai/infinitetalk"
    assert set(body) == {"image", "audio", "prompt", "resolution"} and body["resolution"] == "720p"
    assert body["image"].startswith("data:image/png") and body["audio"].startswith("data:")
    assert (res.width, res.height) == (720, 1280)
    key_only_to_provider(ws.requests, "api.wavespeed.ai")


async def test_a_wavespeed_failure_is_said_in_its_words():
    ws = WaveSpeed(b"", "audio/wav", fail="lyrics too long")
    keys = await on("music", "wavespeed", "minimax/music-2.6")
    engine = KeyedSpeechEngine(LocalVoice(), keys, ws.client, poll_s=0)
    model = engine.resolve("music", None)
    req = check_music(model, "song", "Warm city pop at night", None, True, None, None, None)
    with pytest.raises(VoiceEngineError, match="WaveSpeed could not make it: lyrics too long"):
        await engine.music(model, req)


# ---- Runware -----------------------------------------------------------------------------------


async def test_a_song_on_runware_is_an_audio_task_followed_with_get_response():
    rw = Runware("audioURL", a_wav(2.0), "audio/wav")
    keys = await on("music", "runware", "minimax:music@2.6")
    engine = KeyedSpeechEngine(LocalVoice(), keys, rw.client, poll_s=0)
    model = engine.resolve("music", None)
    req = check_music(model, "song", "A happy folk song", None, False, None, None, None)
    res = await engine.music(model, req)
    first, *asks = rw.tasks()
    assert first["taskType"] == "audioInference" and first["model"] == "minimax:music@2.6"
    assert first["positivePrompt"] == "A happy folk song" and first["deliveryMethod"] == "async"
    assert first["settings"] == {"instrumental": False, "lyricsOptimizer": True}
    assert [a["taskType"] for a in asks] == ["getResponse", "getResponse"]
    assert {a["taskUUID"] for a in asks} == {first["taskUUID"]}
    assert res.seconds == pytest.approx(2.0)
    key_only_to_provider(rw.requests, "api.runware.ai")


def job(capability: str = "image.generate", **inputs) -> JobRequest:
    return JobRequest(
        tenant_id="local", product_id="wasifyai-image", user_id="u1", capability=capability,
        workflow="w", prompt={}, inputs={"prompt": "A red apple", **inputs},
        outputs={"image": {"node": "1", "type": "image"}},
    )  # fmt: skip


async def test_a_picture_on_runware_is_an_image_task_of_the_sides_it_takes():
    rw = Runware("imageURL", a_png(), "image/png")
    keys = await on("images", "runware", "runware:100@1")
    async with rw.client() as http:
        runner = await KeyedMediaRouter(object(), keys, http, 60, 0).resolve(
            job(width=1000, height=700)
        )
        files = await runner.run(job(width=1000, height=700), _progress)
    task = rw.tasks()[0]
    assert (task["taskType"], task["model"]) == ("imageInference", "runware:100@1")
    assert (task["width"], task["height"]) == (1024, 704)  # multiples of 64
    assert files["image"][1:] == ("image/png", "png")


async def test_a_picture_on_wavespeed_has_its_size_and_changing_one_is_refused():
    ws = WaveSpeed(a_png(), "image/png")
    keys = await on("images", "wavespeed", "wavespeed-ai/z-image/turbo")
    async with ws.client() as http:
        router = KeyedMediaRouter(object(), keys, http, 60, 0)
        runner = await router.resolve(job(width=1024, height=768, seed=5))
        await runner.run(job(width=1024, height=768, seed=5), _progress)
        with pytest.raises(Exception, match="Only making a picture runs on WaveSpeed"):
            await runner.run(job("image.edit"), _progress)
    ((url, body),) = ws.posts()
    assert url == "https://api.wavespeed.ai/api/v3/wavespeed-ai/z-image/turbo"
    assert body == {"prompt": "A red apple", "output_format": "png", "size": "1024*768", "seed": 5}


async def _progress(_p: float) -> None:
    return None
