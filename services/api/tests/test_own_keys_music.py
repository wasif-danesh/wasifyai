"""Music and sound effects on the cloud models (ADR-0100, stage CP8), against fakes of Runware,
WaveSpeed and fal.ai: each song and sound effect model on each offer; the cheapest offer for the
job (MiniMax Music 3 by length, Mureka by whether it sings); splitting a recording into stems; a
stretch of a clip written again. The recordings go up the provider's way first."""

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from wasifyai_api.own_keys import OwnKeysService, Provider, Tried
from wasifyai_api.own_keys_catalogue import CATALOGUE
from wasifyai_api.own_keys_engines import KeyedSpeechEngine
from wasifyai_api.own_keys_music import (
    KEYED_MUSIC,
    KEYED_MUSICEDIT,
    KEYED_SFX,
    KEYED_SPLIT,
    SPLIT_MODELS,
)
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import (
    InMemorySecretStore,
    InMemoryUsageRecorder,
    VoiceEngineError,
    VoiceRequestError,
    check_music,
    check_music_edit,
    check_separate,
)

from tests.test_own_keys_engines import Fal
from tests.test_own_keys_wavespeed_runware import Runware, WaveSpeed, a_wav

WAV = a_wav(1.0, 44100)


async def accept(provider: Provider, model: str, key: str, base: str) -> Tried:
    return Tried(True, 1)


async def on(product: str, model: str, *providers: str) -> OwnKeysService:
    keys = OwnKeysService(
        InMemorySettingsStore(), InMemorySecretStore(), {"text": accept, "media": accept}
    )
    for p in providers:
        await keys.save_key(product, p, "k")
    await keys.use(product, None, model)
    return keys


class Here:
    """This computer's speech engine: nothing on it here."""

    def models(self, task=None):
        return []

    def resolve(self, task, model_id):
        return SimpleNamespace(id=f"local:{task}", tasks=(task,))


def fake(provider: str, answer: dict | None = None, outputs: int = 1) -> Any:
    if provider == "runware":
        return Runware("audioURL", WAV, "audio/wav")
    if provider == "wavespeed":
        return WaveSpeed(WAV, "audio/wav", outputs=outputs)
    return Fal(answer or {"audio": {"url": "https://v3.fal.media/s.wav"}}, WAV)


def asked(provider: str, f) -> tuple[str, dict]:
    """The request that made the audio: where it went and what it said."""
    if provider == "runware":
        (task,) = [t for t in f.tasks() if t["taskType"] == "audioInference"]
        return task["model"], task
    return f.posts()[-1]


def recording(tmp_path: Path, seconds: float = 4.0) -> Path:
    p = tmp_path / "song.wav"
    p.write_bytes(a_wav(seconds, 44100))
    return p


# ---- songs and sound effects -------------------------------------------------------------------

# the offers that sing only words they are given (CP13); the model's other offers write them
NEEDS_WORDS = {("minimax-music-2.6", "wavespeed"), ("minimax-music-3", "fal")}

MAKE = [
    (m.product, m.model, o.provider, o.endpoint)
    for m in CATALOGUE if m.product in ("music", "sfx") for o in m.offers
]  # fmt: skip


@pytest.mark.parametrize(("product", "model", "provider", "endpoint"), MAKE)
async def test_each_song_and_sound_effect_model_makes_on_each_offer(
    product, model, provider, endpoint
):
    keys = await on(product, model, provider)
    f = fake(provider)
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0)
    m = engine.resolve("music", KEYED_SFX if product == "sfx" else KEYED_MUSIC)
    mode = "sfx" if product == "sfx" else "song"
    words = m.music["modes"][mode].get("lyrics") == "required" or (model, provider) in NEEDS_WORDS
    lyrics = "[verse]\nLa la la" if words else None
    req = check_music(
        m, mode, "A bright synth melody over soft drums", lyrics, False, None, {}, None
    )
    res = await engine.music(m, req)
    url, body = asked(provider, f)
    assert url.endswith(endpoint) and res.model_id == endpoint
    assert res.seconds == pytest.approx(1.0) and res.wav[:4] == b"RIFF"
    said = " ".join(str(v) for v in body.values())
    assert "A bright synth melody" in said


@pytest.mark.parametrize(("model", "provider"), sorted(NEEDS_WORDS))
async def test_a_song_without_words_is_refused_before_sending_where_none_are_written(
    model, provider
):
    keys = await on("music", model, provider)
    f = fake(provider)
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0)
    m = engine.resolve("music", KEYED_MUSIC)
    req = check_music(m, "song", "A slow piano ballad in the rain", None, False, None, {}, None)
    with pytest.raises(VoiceEngineError, match="add lyrics"):
        await engine.music(m, req)
    assert f.posts() == []


async def test_minimax_music_3_on_wavespeed_writes_the_words_when_none_are_given():
    keys = await on("music", "minimax-music-3", "wavespeed")
    ws = fake("wavespeed")
    engine = KeyedSpeechEngine(Here(), keys, ws.client, poll_s=0)
    m = engine.resolve("music", None)
    req = check_music(m, "song", "A slow piano ballad in the rain", None, False, None, {}, None)
    await engine.music(m, req)
    _, body = ws.posts()[-1]
    assert body["lyrics_optimizer"] is True and "lyrics" not in body


async def test_minimax_music_3_runs_where_a_song_of_its_length_is_cheaper():
    usage = InMemoryUsageRecorder()
    keys = await on("music", "minimax-music-3", "wavespeed", "fal")
    ws = fake("wavespeed")
    engine = KeyedSpeechEngine(Here(), keys, ws.client, poll_s=0, usage=usage)
    m = engine.resolve("music", None)
    req = check_music(m, "song", "A slow piano ballad in the rain", None, False, None, {}, None)
    await engine.music(m, req)  # 120 s: $0.15 a song on WaveSpeed beats $0.002 a second
    (url, body), (event,) = ws.posts()[-1], usage.events
    assert url.endswith("/minimax/music-3.0") and body["is_instrumental"] is False
    assert event.quantity == pytest.approx(0.15) and event.meta["provider"] == "wavespeed"


@pytest.mark.parametrize(
    ("instrumental", "provider", "endpoint", "cost"),
    [(False, "fal", "mureka/v9.5/generate/song", 0.15),
     (True, "wavespeed", "mureka-ai/mureka-v9.5/generate-bgm", 0.225)],
)  # fmt: skip
async def test_mureka_sings_on_fal_and_plays_instrumentals_on_wavespeed(
    instrumental, provider, endpoint, cost
):
    usage = InMemoryUsageRecorder()
    keys = await on("music", "mureka-v9.5", "wavespeed", "fal")
    f = fake(provider)
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0, usage=usage)
    m = engine.resolve("music", None)
    lyrics = None if instrumental else "[verse]\nOver the hills"
    req = check_music(m, "song", "Folk with a fiddle", lyrics, instrumental, None, {}, None)
    res = await engine.music(m, req)
    url, body = asked(provider, f)
    assert url.endswith(endpoint) and res.model_id == endpoint
    assert ("lyrics" in body) is not instrumental
    assert usage.events[0].quantity == pytest.approx(cost)


async def test_mureka_needs_lyrics_to_sing():
    keys = await on("music", "mureka-v9.5", "fal")
    engine = KeyedSpeechEngine(Here(), keys, fake("fal").client, poll_s=0)
    m = engine.resolve("music", None)
    with pytest.raises(VoiceRequestError) as e:
        check_music(m, "song", "Folk with a fiddle", None, False, None, {}, None)
    assert e.value.code == "lyrics_required"


# ---- split into stems --------------------------------------------------------------------------


async def test_demucs_splits_into_six_parts_on_fal(tmp_path):
    names = ("drums", "bass", "other", "vocals", "guitar", "piano")
    answer = {n: {"url": f"https://v3.fal.media/{n}.wav"} for n in names}
    f = fake("fal", answer)
    keys = await on("split", "demucs", "fal")
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0)
    model = engine.resolve("separate", None)
    assert model.id == KEYED_SPLIT and model.separate["stems"] == list(names)
    req = check_separate(model, 4.0, {})
    res = await engine.separate(model, req, recording(tmp_path))
    ((url, body),) = f.posts()
    assert url.endswith("/fal-ai/demucs") and body["model"] == "htdemucs_6s"
    assert body["audio_url"] == "https://v3.fal.media/files/in0"  # the recording went up first
    assert [s.name for s in res.stems] == list(names)
    assert all(s.wav[:4] == b"RIFF" and s.seconds == pytest.approx(1.0) for s in res.stems)


async def test_sam_audio_answers_the_singing_and_the_rest(tmp_path):
    answer = {"target": {"url": "https://v3.fal.media/t.wav"},
              "residual": {"url": "https://v3.fal.media/r.wav"}}  # fmt: skip
    f = fake("fal", answer)
    keys = await on("split", "sam-audio", "fal")
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0)
    model = engine.resolve("separate", None)
    res = await engine.separate(model, check_separate(model, 4.0, {}), recording(tmp_path))
    ((_, body),) = f.posts()
    assert body["prompt"] == "singing voice"
    assert [s.name for s in res.stems] == ["vocals", "instrumental"]


async def test_mureka_stems_on_wavespeed_are_read_in_order(tmp_path):
    ws = fake("wavespeed", outputs=2)
    keys = await on("split", "mureka-stems", "wavespeed")
    engine = KeyedSpeechEngine(Here(), keys, ws.client, poll_s=0)
    model = engine.resolve("separate", None)
    res = await engine.separate(model, check_separate(model, 4.0, {}), recording(tmp_path))
    ((url, body),) = ws.posts()
    assert url.endswith("/mureka-ai/stem-song") and body["audio"] == "https://d1.wavespeed.ai/in/0"
    assert [s.name for s in res.stems] == list(SPLIT_MODELS["mureka-stems"].stems)


def stems_zip(*names: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, WAV)
    return buf.getvalue()


async def test_with_both_keys_mureka_stems_go_to_the_cheaper_fal_as_an_mp3_and_come_back_zipped(
    tmp_path, monkeypatch
):
    """Mureka on fal.ai reads no WAV and answers one zip of every part (CP13)."""
    import wasifyai_api.own_keys_engines as engines

    async def as_mp3(data: bytes, suffix: str = ".wav") -> bytes:
        return b"ID3" + data[:8]

    monkeypatch.setattr(engines, "to_mp3", as_mp3)
    usage = InMemoryUsageRecorder()
    zipped = stems_zip("vocals.wav", "bass.wav", "instrumental.wav", "drums.wav", "song.wav")
    f = Fal({"zip_url": "https://v3.fal.media/stems.zip", "midi_zip_url": None}, zipped)
    keys = await on("split", "mureka-stems", "wavespeed", "fal")
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0, usage=usage)
    model = engine.resolve("separate", None)
    res = await engine.separate(model, check_separate(model, 4.0, {}), recording(tmp_path))
    assert usage.events[0].meta["provider"] == "fal"
    assert usage.events[0].quantity == pytest.approx(0.02)
    ((url, body),) = f.posts()
    assert url.endswith("/mureka/api/song/stem")
    assert list(f.uploads.values())[0].startswith(b"ID3")  # an MP3 went up
    assert [s.name for s in res.stems] == ["vocals", "instrumental"]
    assert all(s.wav[:4] == b"RIFF" for s in res.stems)


# ---- a stretch of a clip written again ---------------------------------------------------------


async def test_ace_step_repaints_a_stretch_on_runware(tmp_path):
    rw = fake("runware")
    keys = await on("musicedit", "ace-step-edit", "runware", "fal")
    engine = KeyedSpeechEngine(Here(), keys, rw.client, poll_s=0)
    editors = [m["id"] for m in engine.models("music") if (m["music"]["modes"] or {}).get("edit")]
    assert editors == [KEYED_MUSICEDIT]
    model = engine.resolve("music", KEYED_MUSICEDIT)
    req = check_music_edit(
        model, "repaint", "A guitar solo", 4.0, [(1.0, 3.0)], None, None, {}, None
    )
    res = await engine.music_edit(model, req, recording(tmp_path))
    air, task = asked("runware", rw)
    assert air == "runware:ace-step@v1.5-turbo" and task["positivePrompt"] == "A guitar solo"
    assert task["inputs"]["audio"] == "media-0"  # the clip went up first
    assert task["settings"] == {"repaintingStart": 1.0, "repaintingEnd": 3.0}
    assert "duration" not in task  # refused with a clip (CP13)
    assert res.wav[:4] == b"RIFF"


@pytest.mark.parametrize(
    ("model_id", "action", "endpoint", "start"),
    [("ace-step-edit", "repaint", "fal-ai/ace-step/audio-inpaint", "start_time"),
     ("stable-audio-3-inpaint", "inpaint", "fal-ai/stable-audio-3/medium/audio-inpainting",
      "mask_start_seconds")],
)  # fmt: skip
async def test_editing_on_fal(tmp_path, model_id, action, endpoint, start):
    f = fake("fal")
    keys = await on("musicedit", model_id, "fal")
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0)
    model = engine.resolve("music", KEYED_MUSICEDIT)
    req = check_music_edit(model, action, "Rain on a roof", 4.0, [(0.5, 2.0)], None, None, {}, None)
    await engine.music_edit(model, req, recording(tmp_path))
    ((url, body),) = f.posts()
    assert url.endswith(endpoint) and body["audio_url"] == "https://v3.fal.media/files/in0"
    assert body[start] == 0.5


async def test_an_editing_model_offers_only_what_it_can_do():
    keys = await on("musicedit", "stable-audio-3-inpaint", "fal")
    engine = KeyedSpeechEngine(Here(), keys, fake("fal").client, poll_s=0)
    model = engine.resolve("music", KEYED_MUSICEDIT)
    with pytest.raises(VoiceRequestError) as e:
        check_music_edit(model, "repaint", "A guitar solo", 4.0, [(1.0, 3.0)], None, None, {}, None)
    assert e.value.code == "wrong_action"
