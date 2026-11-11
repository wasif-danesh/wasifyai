"""Music, sound effects and lip sync on the person's key (`docs/own-keys-fal-everywhere-plan.md`,
F2 to F4), against a fake fal.ai: what each endpoint is sent, what comes back, and that this
computer's models stay offered beside the keyed ones."""

import base64
import io
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from wasifyai_api.own_keys import OwnKeysService, Provider, Tried
from wasifyai_api.own_keys_engines import (
    KEYED_LIPSYNC,
    KEYED_MUSIC,
    KEYED_SFX,
    KeyedSpeechEngine,
)
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import (
    InMemorySecretStore,
    LipSyncRequest,
    VoiceEngineError,
    VoiceRequestError,
    check_lipsync,
    check_music,
)

MINIMAX = "fal-ai/minimax-music/v2.6"
ELEVEN = "fal-ai/elevenlabs/music"
SFX = "fal-ai/elevenlabs/sound-effects/v2"
LONGCAT = "fal-ai/longcat-single-avatar/image-audio-to-video"
INFINITALK = "fal-ai/infinitalk"
KEY = "fal-key-voice"


def a_wav(seconds: float = 0.5, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


WAV = a_wav()


def mp4(w: int, h: int) -> bytes:
    """A few bytes that read as an MP4 with a video track header of this size."""
    tkhd = bytes([0]) + b"\0\0\0" + b"\0" * 20 + b"\0" * 52
    tkhd += (w << 16).to_bytes(4, "big") + (h << 16).to_bytes(4, "big")
    return b"\0\0\0\x5ctkhd" + tkhd


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


async def accept(provider: Provider, model: str, key: str, base: str) -> Tried:
    return Tried(True, 1)


def keys_service() -> OwnKeysService:
    return OwnKeysService(
        InMemorySettingsStore(), InMemorySecretStore(), {"text": accept, "media": accept}
    )


async def on_key(keys: OwnKeysService, product: str, model: str) -> None:
    await keys.save_key(product, "fal", KEY)
    await keys.use(product, "fal", model)


class LocalVoice:
    """This computer's engine: one music model and one lip sync model."""

    def __init__(self) -> None:
        self.made: list[str] = []

    def models(self, task=None):
        rows = [{"id": "ace-step", "tasks": ["music"]}, {"id": "echomimic", "tasks": ["lipsync"]}]
        return [r for r in rows if task is None or task in r["tasks"]]

    def resolve(self, task, model_id):
        return SimpleNamespace(id=model_id or f"local:{task}", tasks=(task,))

    async def music(self, model, req):
        self.made.append(model.id)
        return "made here"

    async def lipsync(self, model, req, picture, voice):
        self.made.append(model.id)
        return "made here"


def a_picture(tmp_path: Path) -> Path:
    path = tmp_path / "face.png"
    Image.new("RGB", (1024, 924), (120, 90, 80)).save(path)
    return path


def sent_picture(body: dict) -> tuple[int, int]:
    data = base64.b64decode(body["image_url"].split(",", 1)[1])
    with Image.open(io.BytesIO(data)) as im:
        return im.size


# ---- music and sound effects -------------------------------------------------------------------


async def test_on_the_key_music_and_sound_effects_come_first_and_this_computers_stay():
    local, keys = LocalVoice(), keys_service()
    await on_key(keys, "music", MINIMAX)
    await on_key(keys, "sfx", SFX)
    engine = KeyedSpeechEngine(local, keys)
    ids = [m["id"] for m in engine.models("music")]
    assert ids == [KEYED_MUSIC, KEYED_SFX, "ace-step"]
    assert engine.resolve("music", None).id == KEYED_MUSIC  # the default runs on the key
    assert engine.resolve("music", "ace-step").id == "ace-step"  # this computer's, when chosen
    assert [m["id"] for m in engine.models("lipsync")] == ["echomimic"]  # lip sync not on a key


async def test_a_song_with_lyrics_goes_to_minimax_with_the_key(tmp_path: Path):
    fal = Fal({"audio": {"url": "https://v3.fal.media/song.wav"}, "seed": 7}, a_wav(2.0, 44100))
    local, keys = LocalVoice(), keys_service()
    await on_key(keys, "music", MINIMAX)
    engine = KeyedSpeechEngine(local, keys, fal.client, poll_s=0)
    model = engine.resolve("music", None)
    req = check_music(model, "song", "Warm city pop at night", "La la la", False, None, None, None)
    res = await engine.music(model, req)
    assert fal.posts() == [(
        f"https://queue.fal.run/{MINIMAX}",
        {"prompt": "Warm city pop at night", "is_instrumental": False, "lyrics": "La la la"},
    )]  # fmt: skip
    assert res.seconds == pytest.approx(2.0) and res.sample_rate == 44100
    assert res.model_id == MINIMAX and res.seed == 7 and local.made == []
    for r in fal.requests:  # the key goes to fal.ai's queue only
        on_queue = str(r.url).startswith("https://queue.fal.run")
        assert (r.headers.get("authorization") == f"Key {KEY}") is on_queue


async def test_minimax_writes_the_words_when_none_are_given_and_needs_ten_letters():
    fal = Fal({"audio": {"url": "https://v3.fal.media/song.wav"}}, WAV)
    keys = keys_service()
    await on_key(keys, "music", MINIMAX)
    engine = KeyedSpeechEngine(LocalVoice(), keys, fal.client, poll_s=0)
    model = engine.resolve("music", None)
    await engine.music(model, check_music(model, "song", "A happy folk song", None, False, None,
                                          None, None))  # fmt: skip
    assert fal.posts()[0][1] == {
        "prompt": "A happy folk song",
        "is_instrumental": False,
        "lyrics_optimizer": True,
    }
    with pytest.raises(VoiceEngineError, match="ten letters"):
        await engine.music(model, check_music(model, "song", "Folk", None, True, None, None, None))


async def test_an_elevenlabs_instrumental_has_its_length_and_takes_no_lyrics():
    fal = Fal({"audio": {"url": "https://v3.fal.media/m.wav"}}, WAV)
    keys = keys_service()
    await on_key(keys, "music", ELEVEN)
    engine = KeyedSpeechEngine(LocalVoice(), keys, fal.client, poll_s=0)
    model = engine.resolve("music", None)
    req = check_music(model, "song", "Calm piano", None, True, 45, None, None)
    await engine.music(model, req)
    assert fal.posts()[0][1] == {
        "prompt": "Calm piano",
        "music_length_ms": 45000,
        "force_instrumental": True,
    }
    with pytest.raises(VoiceRequestError, match="does not sing lyrics"):
        check_music(model, "song", "Calm piano", "words", False, 45, None, None)


async def test_a_sound_effect_goes_to_elevenlabs_with_its_length():
    fal = Fal({"audio": {"url": "https://v3.fal.media/fx.wav"}}, a_wav(5.0, 44100))
    local, keys = LocalVoice(), keys_service()
    await on_key(keys, "sfx", SFX)
    engine = KeyedSpeechEngine(local, keys, fal.client, poll_s=0)
    model = engine.resolve("music", KEYED_SFX)
    req = check_music(model, "sfx", "A door slams", None, False, 30, None, None)
    res = await engine.music(model, req)
    assert fal.posts()[0][1] == {"text": "A door slams", "duration_seconds": 22}  # its longest
    assert res.model_id == SFX and res.seconds == pytest.approx(5.0)


async def test_music_back_on_this_computer_is_made_here():
    local, keys = LocalVoice(), keys_service()
    engine = KeyedSpeechEngine(local, keys)
    model = engine.resolve("music", KEYED_MUSIC)  # remembered from when it was on the key
    assert model.id == "local:music"
    assert await engine.music(model, None) == "made here"  # pyright: ignore[reportArgumentType]


async def test_a_music_failure_on_fal_is_said_in_its_words():
    fal = Fal({}, WAV, submit=401)
    keys = keys_service()
    await on_key(keys, "music", ELEVEN)
    engine = KeyedSpeechEngine(LocalVoice(), keys, fal.client, poll_s=0)
    model = engine.resolve("music", None)
    req = check_music(model, "song", "Calm piano", None, True, 10, None, None)
    with pytest.raises(VoiceEngineError, match="did not accept the key") as e:
        await engine.music(model, req)
    assert KEY not in str(e.value)


# ---- lip sync ----------------------------------------------------------------------------------


async def test_lip_sync_on_the_key_sends_the_cropped_picture_and_the_voice_to_longcat(
    tmp_path: Path,
):
    fal = Fal({"video": {"url": "https://v3.fal.media/v.mp4"}}, mp4(720, 1280))
    local, keys = LocalVoice(), keys_service()
    await on_key(keys, "lipsync", LONGCAT)
    engine = KeyedSpeechEngine(local, keys, fal.client, poll_s=0)
    assert [m["id"] for m in engine.models("lipsync")] == [KEYED_LIPSYNC, "echomimic"]
    model = engine.resolve("lipsync", None)
    req = check_lipsync(model, 12.0, picture=(1024, 924), shape="9:16", size=720)
    assert (req.width, req.height) == (720, 1280)
    voice = tmp_path / "v.wav"
    voice.write_bytes(a_wav(12.0, 16000))
    res = await engine.lipsync(model, req, a_picture(tmp_path), voice)
    ((url, body),) = fal.posts()
    assert url == f"https://queue.fal.run/{LONGCAT}"
    assert body["resolution"] == "720p" and body["num_segments"] == 3  # 5.8 s, then 5 s more each
    assert body["audio_url"].startswith("data:") and sent_picture(body) == (720, 1280)
    assert (res.width, res.height, res.fps) == (720, 1280, 25)
    assert res.model_id == LONGCAT and local.made == []


async def test_infinitetalk_is_asked_for_the_frames_of_the_voice_at_480p(tmp_path: Path):
    fal = Fal({"video": {"url": "https://v3.fal.media/v.mp4"}}, mp4(848, 480))
    keys = keys_service()
    await on_key(keys, "lipsync", INFINITALK)
    engine = KeyedSpeechEngine(LocalVoice(), keys, fal.client, poll_s=0)
    model = engine.resolve("lipsync", None)
    req = check_lipsync(model, 4.0, picture=(1024, 924), shape="16:9", size=480)
    voice = tmp_path / "v.wav"
    voice.write_bytes(a_wav(4.0, 16000))
    await engine.lipsync(model, req, a_picture(tmp_path), voice)
    body = fal.posts()[0][1]
    assert body["resolution"] == "480p" and body["num_frames"] == 101  # 4 s at 25, as 4k+1
    assert sent_picture(body) == (848, 480)
    with pytest.raises(VoiceRequestError):  # longer than one InfiniteTalk request takes
        check_lipsync(model, 40.0, picture=(1024, 924))


async def test_what_fal_sends_back_must_be_a_video(tmp_path: Path):
    fal = Fal({"video": {"url": "https://v3.fal.media/v.mp4"}}, b"not a video")
    keys = keys_service()
    await on_key(keys, "lipsync", LONGCAT)
    engine = KeyedSpeechEngine(LocalVoice(), keys, fal.client, poll_s=0)
    model = engine.resolve("lipsync", None)
    voice = tmp_path / "v.wav"
    voice.write_bytes(a_wav(2.0, 16000))
    with pytest.raises(VoiceEngineError, match="cannot read"):
        await engine.lipsync(model, LipSyncRequest(25, 2.0, 720, 720), a_picture(tmp_path), voice)
