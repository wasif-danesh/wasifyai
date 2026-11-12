"""Music and pictures on WaveSpeed and Runware with the person's key
(`docs/own-keys-cloud-tab-plan.md`, CT3), against fakes of both: what each is sent, how the answer
is followed, and that the key goes to the provider only, never to the file's host. Lip sync is
fal.ai only (owner, 2026-11-12)."""

import io
import json
import wave
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from wasifyai_api.own_keys import OwnKeysService, Provider, Tried
from wasifyai_api.own_keys_engines import KEYED_MUSIC, KeyedSpeechEngine
from wasifyai_api.own_keys_media import KeyedMediaRouter
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import (
    InMemorySecretStore,
    JobRequest,
    VoiceEngineError,
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
        self.uploads: list[dict] = []
        self.polls = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        url = str(req.url)
        if url.endswith("/media/uploads"):  # a place for an input file, then its address
            n = len(self.uploads)
            self.uploads.append(json.loads(req.content))
            return httpx.Response(200, json={"data": {
                "upload": {"url": f"https://up.wavespeed.ai/put/{n}"},
                "download_url": f"https://d1.wavespeed.ai/in/{n}"}})  # fmt: skip
        if req.method == "PUT":
            assert "authorization" not in req.headers  # the key goes to WaveSpeed's API only
            return httpx.Response(200)
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
        return [
            (str(r.url), json.loads(r.content))
            for r in self.requests
            if r.method == "POST" and not str(r.url).endswith("/media/uploads")
        ]


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
    keys = await on("images", "runware", "flux-3-klein")
    async with rw.client() as http:
        runner = await KeyedMediaRouter(object(), keys, http, 60, 0).resolve(
            job(width=1000, height=700)
        )
        files = await runner.run(job(width=1000, height=700), _progress)
    task = rw.tasks()[0]
    assert (task["taskType"], task["model"]) == ("imageInference", "bfl:flux@3-image-klein")
    assert (task["width"], task["height"]) == (1024, 704)  # multiples of 64
    assert task["includeCost"] is True and "inputs" not in task
    assert files["image"][1:] == ("image/png", "png")
    assert runner.cost.offer.provider == "runware" and runner.cost.cost == 0.006


async def test_a_picture_changed_on_runware_carries_its_references_in_the_task():
    rw = Runware("imageURL", a_png(), "image/png")
    keys = await on("images", "runware", "nano-banana-2.1")
    async with rw.client() as http:
        runner = await KeyedMediaRouter(object(), keys, http, 60, 0).resolve(job("image.edit"))
        await runner.run(job("image.edit"), _progress, {"image": a_png(), "image2": a_png()})
    task = rw.tasks()[0]
    assert task["model"] == "google:nano-banana@2.1"
    refs = task["inputs"]["referenceImages"]
    assert len(refs) == 2 and all(r.startswith("data:image/png;base64,") for r in refs)


async def test_gpt_image_paints_on_wavespeed_with_its_picture_and_mask_uploaded_first():
    ws = WaveSpeed(a_png(), "image/png")
    keys = await on("images", "wavespeed", "gpt-image-2.5")
    async with ws.client() as http:
        router = KeyedMediaRouter(object(), keys, http, 60, 0)
        runner = await router.resolve(job("image.inpaint"))
        mask = io.BytesIO()
        Image.new("L", (64, 64), 255).save(mask, "PNG")
        await runner.run(
            job("image.inpaint"), _progress, {"image": a_png(), "mask": mask.getvalue()}
        )
    ((url, body),) = ws.posts()
    assert url == "https://api.wavespeed.ai/api/v3/openai/gpt-image-2.5-sunburst/edit"
    assert body["images"] == ["https://d1.wavespeed.ai/in/0"]
    assert body["mask_image"] == "https://d1.wavespeed.ai/in/1"
    assert [u["content_type"] for u in ws.uploads] == ["image/png", "image/png"]
    key_only_to_provider([r for r in ws.requests if r.method != "PUT"], "api.wavespeed.ai")


async def test_a_job_the_model_cannot_do_is_refused_before_anything_is_sent():
    ws = WaveSpeed(a_png(), "image/png")
    keys = await on("images", "wavespeed", "nano-banana-2.1")
    async with ws.client() as http:
        runner = await KeyedMediaRouter(object(), keys, http, 60, 0).resolve(job("image.inpaint"))
        with pytest.raises(Exception, match="Nano Banana 2.1 cannot do mask"):
            await runner.run(job("image.inpaint"), _progress, {"image": a_png(), "mask": a_png()})
    assert ws.requests == []


async def _progress(_p: float) -> None:
    return None


# ---- the cheapest offer, and the next on a refusal before running (ADR-0100, CP3) ---------------


class Both:
    """Runware refusing the key (an error answer before anything runs) and WaveSpeed making it."""

    def __init__(self):
        self.ws = WaveSpeed(a_wav(3.0), "audio/wav")
        self.hosts: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.hosts.append(req.url.host)
        if req.url.host == "api.runware.ai":
            return httpx.Response(401, json={"errors": [{"message": "Invalid API key"}]})
        return self.ws(req)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


async def test_a_song_goes_to_the_next_offer_when_the_cheapest_refuses_and_its_cost_is_kept():
    from wasifyai_platform_sdk.usage import InMemoryUsageRecorder

    both = Both()
    keys = OwnKeysService(
        InMemorySettingsStore(), InMemorySecretStore(), {"text": accept, "media": accept}
    )
    await keys.save_key("media", "runware", KEY)  # one key for every media product
    await keys.save_key("music", "wavespeed", KEY)
    await keys.use("music", None, "minimax-music-2.6")
    await keys.warm()
    usage = InMemoryUsageRecorder()
    engine = KeyedSpeechEngine(LocalVoice(), keys, both.client, poll_s=0, usage=usage)
    model = engine.resolve("music", None)
    req = check_music(model, "song", "Warm city pop at night", None, True, None, None, None)
    res = await engine.music(model, req)
    # the same price on both: the tie goes to Runware, which refused, so WaveSpeed made it
    assert both.hosts[0] == "api.runware.ai" and "api.wavespeed.ai" in both.hosts
    assert res.model_id == "minimax/music-2.6"
    (cost,) = usage.events
    assert (cost.kind, cost.quantity, cost.unit) == ("cloud.cost", 0.15, "dollars")
    assert cost.meta == {
        "provider": "wavespeed", "model": "minimax-music-2.6", "endpoint": "minimax/music-2.6",
    }  # fmt: skip
