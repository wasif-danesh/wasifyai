"""Voice and 3D on the person's key (ADR-0095, stage K4), against a fake fal.ai: while a product is
on its key, speaking and 3D models go to fal.ai with that key; everything else, and everything once
it is back on this computer, is done here."""

import io
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from wasifyai_api.own_keys import OwnKeysService, Provider, Tried
from wasifyai_api.own_keys_engines import KEYED_VOICE, KeyedModel3d, KeyedSpeechEngine
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import InMemorySecretStore, SpeechResult, VoiceEngineError

KEY = "fal-key-voice"
PNG = b"\x89PNG\r\n\x1a\nPICTURE"
GLB = b"glTF\x02\x00\x00\x00MODEL"


def a_wav(seconds: float = 0.5, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


WAV = a_wav()


async def accept(provider: Provider, model: str, key: str, base: str) -> Tried:
    return Tried(True, 1)


class Fal:
    """A fake fal.ai queue; the result names a file on another host."""

    def __init__(self, result: dict, file: bytes, submit: int = 200):
        self.result, self.file, self.submit = result, file, submit
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        url = str(req.url)
        if req.method == "POST":
            if self.submit != 200:
                return httpx.Response(self.submit, json={})
            q = "https://queue.fal.run/x/requests/r1"
            return httpx.Response(200, json={"status_url": f"{q}/status", "response_url": q})
        if url.endswith("/status"):
            return httpx.Response(200, json={"status": "COMPLETED"})
        if url.startswith("https://queue.fal.run"):
            return httpx.Response(200, json=self.result)
        return httpx.Response(200, content=self.file)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def posts(self) -> list[tuple[str, dict]]:
        return [(str(r.url), json.loads(r.content)) for r in self.requests if r.method == "POST"]


class LocalSpeech:
    def __init__(self) -> None:
        self.spoke: list[str] = []
        self.installer = "the speech runtime's installer"

    def models(self, task=None):
        return [{"id": "kokoro-82m", "tasks": ["speak"], "state": "ready"}]

    def resolve(self, task, model_id):
        if model_id not in (None, "kokoro-82m"):
            raise VoiceEngineError("unknown_model", "no")
        return SimpleNamespace(id=f"local:{task}")

    async def speak(self, model, text, voice, options, *, beside=False):
        self.spoke.append(text)
        return SpeechResult(WAV, 24000, 0.5, "kokoro-82m", voice, 0, 0)


def keys_service() -> OwnKeysService:
    return OwnKeysService(
        InMemorySettingsStore(), InMemorySecretStore(), {"text": accept, "media": accept}
    )


async def on_key(keys: OwnKeysService, product: str, model: str) -> None:
    await keys.save(product, "key", "fal", model, None, KEY)


# ---- speech ------------------------------------------------------------------------------------


async def test_on_this_computer_speaking_is_untouched():
    local, keys = LocalSpeech(), keys_service()
    engine = KeyedSpeechEngine(local, keys)
    assert engine.models("speak") == local.models("speak")
    assert engine.resolve("speak", None).id == "local:speak"
    assert engine.installer == local.installer  # everything else is this computer's engine
    await engine.speak(engine.resolve("speak", None), "hello", None, {})
    assert local.spoke == ["hello"]


async def test_on_the_key_speaking_goes_to_fal_with_the_key_and_the_voice_chosen():
    fal = Fal({"audio": {"url": "https://v3.fal.media/s.wav"}}, WAV)
    local, keys = LocalSpeech(), keys_service()
    await on_key(keys, "voice", "fal-ai/kokoro")
    engine = KeyedSpeechEngine(local, keys, fal.client, poll_s=0)
    (only,) = engine.models("speak")  # the one model for speaking while it runs on the key
    assert only["id"] == KEYED_VOICE and only["state"] == "ready" and only["engine"] == "remote"
    assert {v["id"] for v in only["voices"]} >= {"af_heart", "am_adam"}
    model = engine.resolve("speak", "kokoro-82m")  # what the screen remembered does not matter
    res = await engine.speak(model, "Good morning.", "am_adam", {"speed": 1.2})
    assert fal.posts() == [
        (
            "https://queue.fal.run/fal-ai/kokoro",
            {"prompt": "Good morning.", "voice": "am_adam", "speed": 1.2},
        )
    ]
    assert res.wav == WAV and res.seconds == pytest.approx(0.5) and res.sample_rate == 24000
    assert res.model_id == "fal-ai/kokoro" and local.spoke == []
    for r in fal.requests:  # the key goes to fal.ai's queue only, never to the file host
        on_queue = str(r.url).startswith("https://queue.fal.run")
        assert (r.headers.get("authorization") == f"Key {KEY}") is on_queue


async def test_other_voice_tools_stay_here_while_speaking_is_on_the_key():
    local, keys = LocalSpeech(), keys_service()
    await on_key(keys, "voice", "fal-ai/kokoro")
    engine = KeyedSpeechEngine(local, keys)
    assert engine.resolve("clone", None).id == "local:clone"
    assert engine.models("clone") == local.models("clone")
    assert [m["id"] for m in engine.models()] == [KEYED_VOICE, "kokoro-82m"]


async def test_back_on_this_computer_the_keyed_model_is_not_asked_for_again():
    local, keys = LocalSpeech(), keys_service()
    await on_key(keys, "voice", "fal-ai/kokoro")
    engine = KeyedSpeechEngine(local, keys)
    model = engine.resolve("speak", None)
    await keys.save("voice", "here", None, None, None, None)
    assert engine.resolve("speak", KEYED_VOICE).id == "local:speak"  # a remembered keyed id
    with pytest.raises(VoiceEngineError) as e:  # a request made just before the change
        await engine.speak(model, "hi", None, {})
    assert e.value.code == "not_with_key" and local.spoke == []


@pytest.mark.parametrize(
    ("fal", "code", "words"),
    [
        (Fal({}, WAV, submit=401), "provider_refused", "fal.ai did not accept the key."),
        (Fal({"audio": {"url": "https://f/a.mp3"}}, b"ID3mp3"), "engine_failed", "cannot read"),
        (Fal({}, WAV), "missing_output", "returned nothing"),
    ],
)
async def test_a_failure_on_fal_is_said_and_never_with_the_key(fal, code, words):
    local, keys = LocalSpeech(), keys_service()
    await on_key(keys, "voice", "fal-ai/kokoro")
    engine = KeyedSpeechEngine(local, keys, fal.client, poll_s=0)
    with pytest.raises(VoiceEngineError) as e:
        await engine.speak(engine.resolve("speak", None), "hi", None, {})
    assert e.value.code == code and words in e.value.message and KEY not in e.value.message


# ---- 3D ----------------------------------------------------------------------------------------


class Local3d:
    """This computer's 3D engine, not set up."""

    def __init__(self) -> None:
        self.ran: list[str] = []
        self.installer = "the 3D installer"

    def state(self):
        return {"installed": False, "fit": None, "about": {"where": "here"}}

    def ready(self):
        return False

    def problem(self):
        return "The 3D component is not set up yet. Set it up first."

    def fit(self):
        return {"verdict": "too_big", "reason": "19 GB"}

    async def matte(self, picture, out_dir, on_line=None):
        self.ran.append("matte")

    async def generate(self, cutout, out_glb, **kw):
        self.ran.append("generate")


async def test_3d_on_this_computer_is_untouched():
    local, keys = Local3d(), keys_service()
    engine = KeyedModel3d(local, keys)
    assert engine.state() == local.state() and not engine.ready()
    assert engine.problem() == local.problem() and engine.fit() == local.fit()
    await engine.generate(Path("c.png"), Path("m.glb"))
    assert local.ran == ["generate"] and engine.installer == local.installer


async def test_3d_on_the_key_needs_nothing_set_up_and_runs_on_fal(tmp_path: Path):
    fal = Fal({"model_glb": {"url": "https://v3.fal.media/m.glb"}}, GLB)
    local, keys = Local3d(), keys_service()
    await on_key(keys, "model3d", "fal-ai/pixal3d")
    engine = KeyedModel3d(local, keys, fal.client, poll_s=0)
    assert engine.ready() and engine.problem() is None
    assert engine.fit()["verdict"] == "fits"
    state = engine.state()
    assert state["installed"] is True and state["here"] is False and state["keyed"] is True
    cutout = tmp_path / "cutout.png"
    cutout.write_bytes(PNG)
    seen: list[tuple[float, str]] = []
    res = await engine.generate(
        cutout, tmp_path / "model.glb", seed=7, detail="detailed",
        on_progress=lambda f, w: seen.append((f, w)),
    )  # fmt: skip
    assert res.ok and res.output == tmp_path / "model.glb"
    assert (tmp_path / "model.glb").read_bytes() == GLB
    ((url, body),) = fal.posts()
    assert url == "https://queue.fal.run/fal-ai/pixal3d"
    assert body["image_url"].startswith("data:image/png;base64,")
    assert {k: body[k] for k in ("seed", "resolution", "texture_size")} == {
        "seed": 7, "resolution": 1024, "texture_size": 4096,
    }  # fmt: skip
    assert seen and local.ran == []


async def test_the_cut_out_on_the_key_is_made_by_fal_too(tmp_path: Path):
    fal = Fal({"image": {"url": "https://v3.fal.media/cut.png"}}, PNG)
    local, keys = Local3d(), keys_service()
    await on_key(keys, "model3d", "fal-ai/pixal3d")
    engine = KeyedModel3d(local, keys, fal.client, poll_s=0)
    picture = tmp_path / "picture.png"
    picture.write_bytes(PNG)
    res = await engine.matte(picture, tmp_path)
    assert res.ok and res.output is not None and res.output.read_bytes() == PNG
    ((url, body),) = fal.posts()
    assert url == "https://queue.fal.run/fal-ai/birefnet" and body["output_format"] == "png"
    assert local.ran == []


async def test_a_3d_failure_on_fal_is_a_failed_run_in_fals_words(tmp_path: Path):
    local, keys = Local3d(), keys_service()
    await on_key(keys, "model3d", "fal-ai/pixal3d")
    engine = KeyedModel3d(local, keys, Fal({}, GLB, submit=429).client, poll_s=0)
    cutout = tmp_path / "cutout.png"
    cutout.write_bytes(PNG)
    res = await engine.generate(cutout, tmp_path / "model.glb")
    assert not res.ok and res.reason == "failed" and "too many requests" in res.message
    assert not (tmp_path / "model.glb").exists()


async def test_removing_the_3d_key_brings_it_back_here_at_once():
    local, keys = Local3d(), keys_service()
    await on_key(keys, "model3d", "fal-ai/pixal3d")
    engine = KeyedModel3d(local, keys)
    assert engine.ready()
    await keys.remove("model3d")
    assert not engine.ready() and engine.state() == local.state()
