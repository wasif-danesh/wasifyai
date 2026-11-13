"""Voice on the cloud models (ADR-0100, stage CP7), against fakes of Runware, WaveSpeed and fal.ai:
speaking with each model on each offer; copying a voice from a recording and making one from words
(a MiniMax voice made once and spoken in again per character where it was made); writing down
speech; changing a voice. The recordings go up the provider's way first."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from wasifyai_api.own_keys import OwnKeysService, Provider, Tried
from wasifyai_api.own_keys_catalogue import CATALOGUE
from wasifyai_api.own_keys_engines import KeyedSpeechEngine
from wasifyai_api.own_keys_voice import (
    KEYED_CHANGE,
    KEYED_CLONE,
    KEYED_TRANSCRIBE,
    KEYED_VOICE,
    transcript_of,
)
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import ConvertRequest, InMemorySecretStore, InMemoryUsageRecorder

from tests.test_own_keys_engines import Fal
from tests.test_own_keys_wavespeed_runware import Runware, WaveSpeed, a_wav

WAV = a_wav(1.0, 24000)


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


def fake(provider: str, answer: dict | None = None) -> Any:
    if provider == "runware":
        return Runware("audioURL", WAV, "audio/wav")
    if provider == "wavespeed":
        return WaveSpeed(WAV, "audio/wav")
    return Fal(answer or {"audio": {"url": "https://v3.fal.media/s.wav"}}, WAV)


def asked(provider: str, f) -> tuple[str, dict]:
    """The request that made the speech: where it went and what it said."""
    if provider == "runware":
        (task,) = [t for t in f.tasks() if t["taskType"] == "audioInference"]
        return task["model"], task
    return f.posts()[-1]


SPEAK = [
    (m.model, o.provider, o.endpoint) for m in CATALOGUE if m.product == "voice" for o in m.offers
]


@pytest.mark.parametrize(("model", "provider", "endpoint"), SPEAK)
async def test_each_speaking_model_speaks_on_each_offer(model, provider, endpoint):
    keys = await on("voice", model, provider)
    f = fake(provider)
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0)
    (row,) = engine.models("speak")  # the one speaking model while Voice runs on the cloud
    voice = engine.resolve("speak", None)
    assert row["id"] == voice.id == KEYED_VOICE
    res = await engine.speak(voice, "Hello there.", voice.default_voice, {})
    where, body = asked(provider, f)
    if provider == "runware":
        assert where == endpoint and body["speech"]["text"] == "Hello there."
        assert body["speech"]["voice"] == voice.default_voice
    else:
        assert where.endswith("/" + endpoint)
        said = body.get("text") or body.get("prompt")
        assert said == "Hello there."
    if voice.voices and provider != "runware":
        named = body.get("voice") or body.get("voice_id") or body.get("voice_setting", {})
        assert voice.default_voice in (named, getattr(named, "get", lambda _: None)("voice_id"))
    assert res.wav[:4] == b"RIFF" and res.model_id == endpoint


async def test_speaking_has_each_models_own_voices():
    keys = await on("voice", "gemini-3.8-flash-tts", "fal")
    engine = KeyedSpeechEngine(Here(), keys, fake("fal").client, poll_s=0)
    voice = engine.resolve("speak", None)
    assert voice.default_voice == "Kore" and len(voice.voices) == 30
    keys = await on("voice", "minimax-speech-2.8-hd", "runware")
    voice = KeyedSpeechEngine(Here(), keys, fake("runware").client).resolve("speak", None)
    assert "speed" in {o.name for o in voice.options}


# ---- copy a voice, or make one from words -------------------------------------------------------


def recording(tmp_path: Path) -> Path:
    p = tmp_path / "me.wav"
    p.write_bytes(a_wav(5.0, 24000))
    return p


async def test_qwen_copies_a_voice_on_runware_with_the_recording_uploaded_first(tmp_path):
    keys = await on("voiceclone", "qwen3-tts", "runware")
    rw = fake("runware")
    engine = KeyedSpeechEngine(Here(), keys, rw.client, poll_s=0)
    (row,) = engine.models("clone")
    assert row["id"] == KEYED_CLONE and set(row["tasks"]) == {"clone", "design"}
    model = engine.resolve("clone", None)
    await engine.clone(model, "Read this.", recording(tmp_path), "What I said.", {})
    _, task = asked("runware", rw)
    assert task["model"] == "alibaba:qwen@3-tts-1.7b-base"
    assert task["inputs"]["audio"] == "media-0"  # a voice goes up first (`mediaStorage`)
    assert task["speech"] == {"text": "Read this.", "voice": "clone", "language": "Auto"}
    assert task["settings"] == {"xVectorOnly": False, "transcript": "What I said."}
    await engine.design(model, "Read this.", "A calm, low voice", {})
    task = [t for t in rw.tasks() if t["taskType"] == "audioInference"][-1]
    assert task["model"] == "alibaba:qwen@3-tts-1.7b-voicedesign"
    assert task["positivePrompt"] == "A calm, low voice" and task["speech"]["voice"] == "design"


async def test_with_only_fal_qwen_designs_but_does_not_copy(tmp_path):
    keys = await on("voiceclone", "qwen3-tts", "fal")
    f = fake("fal")
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0)
    model = engine.resolve("design", None)
    assert model.tasks == ("design",)
    await engine.design(model, "Read this.", "A calm, low voice", {})
    ((url, body),) = f.posts()
    assert url.endswith("/fal-ai/qwen-3-tts/voice-design/1.7b")
    assert body == {"prompt": "A calm, low voice", "text": "Read this."}


async def test_chatterbox_copies_a_voice_on_wavespeed(tmp_path):
    keys = await on("voiceclone", "chatterbox-clone", "wavespeed")
    ws = fake("wavespeed")
    engine = KeyedSpeechEngine(Here(), keys, ws.client, poll_s=0)
    model = engine.resolve("clone", None)
    await engine.clone(model, "Read this.", recording(tmp_path), None, {})
    ((url, body),) = ws.posts()
    assert url.endswith("/chatterbox/text-to-speech")
    assert body == {"text": "Read this.", "reference_audio": "https://d1.wavespeed.ai/in/0"}
    assert [u["content_type"] for u in ws.uploads] == ["audio/wav"]


async def test_a_minimax_voice_is_made_once_then_spoken_in_where_it_was_made(tmp_path):
    keys = await on("voiceclone", "minimax-voice", "fal")
    made = {"custom_voice_id": "wasify-from-fal", "audio": {"url": "https://v3.fal.media/s.wav"}}
    f, usage = fake("fal", made), InMemoryUsageRecorder()
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0, usage=usage)
    model = engine.resolve("clone", None)
    voice = recording(tmp_path)
    await engine.clone(model, "First words.", voice, None, {})
    url, body = f.posts()[-1]
    assert url.endswith("/fal-ai/minimax/voice-clone") and body["text"] == "First words."
    assert await keys.kept_voice(_key(voice), "fal") == "wasify-from-fal"
    await engine.clone(model, "More words.", voice, None, {})
    url, body = f.posts()[-1]
    assert url.endswith("/fal-ai/minimax/speech-2.8-hd")  # spoken in again, per character
    assert body["voice_setting"]["voice_id"] == "wasify-from-fal"
    assert body["prompt"] == "More words."
    made_cost, again_cost = (e.quantity for e in usage.events)
    assert made_cost == pytest.approx(1.50)  # a new voice
    assert again_cost == pytest.approx(0.10 * len("More words.") / 1000, abs=1e-6)


def _key(voice: Path) -> str:
    from wasifyai_api.own_keys_voice import voice_key

    return voice_key("clone", voice.read_bytes())


async def test_a_minimax_voice_designed_on_wavespeed_is_named_by_this_app(tmp_path):
    keys = await on("voiceclone", "minimax-voice", "wavespeed")
    ws = fake("wavespeed")
    engine = KeyedSpeechEngine(Here(), keys, ws.client, poll_s=0)
    await engine.design(engine.resolve("design", None), "Hello.", "An old sailor", {})
    ((url, body),) = ws.posts()
    assert url.endswith("/minimax/voice-design")
    assert body["prompt"] == "An old sailor" and body["preview_text"] == "Hello."
    assert body["custom_voice_id"].startswith("wasify")


# ---- write down speech -------------------------------------------------------------------------

SCRIBE = {
    "text": "Hello there. How are you?",
    "words": [
        {"text": "Hello", "start": 0.0, "end": 0.4, "type": "word"},
        {"text": " ", "start": 0.4, "end": 0.45, "type": "spacing"},
        {"text": "there.", "start": 0.45, "end": 0.9, "type": "word"},
        {"text": " ", "start": 0.9, "end": 1.0, "type": "spacing"},
        {"text": "How", "start": 1.0, "end": 1.2, "type": "word"},
        {"text": " ", "start": 1.2, "end": 1.25, "type": "spacing"},
        {"text": "are", "start": 1.25, "end": 1.4, "type": "word"},
        {"text": " ", "start": 1.4, "end": 1.45, "type": "spacing"},
        {"text": "you?", "start": 1.45, "end": 1.8, "type": "word"},
    ],
}


async def test_scribe_writes_down_speech_on_fal_in_sentences():
    keys = await on("transcribe", "scribe-v2", "fal")
    f = fake("fal", SCRIBE)
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0)
    model = engine.resolve("transcribe", None)
    assert model.id == KEYED_TRANSCRIBE
    res = await engine.transcribe(model, WAV, {"language": "en"})
    ((url, body),) = f.posts()
    assert url.endswith("/fal-ai/elevenlabs/speech-to-text/scribe-v2")
    assert body["audio_url"] == "https://v3.fal.media/files/in0" and body["language_code"] == "en"
    assert [(s.start, s.end, s.text) for s in res.segments] == [
        (0.0, 0.9, "Hello there."), (1.0, 1.8, "How are you?"),
    ]  # fmt: skip
    assert res.text == "Hello there. How are you?"


def test_whisper_answers_are_read_from_wavespeeds_outputs():
    text, segs, seconds = transcript_of({"outputs": [{"text": "Hi.", "segments": [
        {"start": 0.0, "end": 0.7, "text": " Hi."}]}]})  # fmt: skip
    assert (text, [s.text for s in segs], seconds) == ("Hi.", ["Hi."], 0.7)
    text, segs, _ = transcript_of({"outputs": ["Just words."]})
    assert text == "Just words." and len(segs) == 1


async def test_whisper_writes_down_speech_on_wavespeed():
    keys = await on("transcribe", "whisper", "wavespeed")
    ws = fake("wavespeed")
    ws_result = {"status": "completed", "outputs": [{"text": "Hi.", "segments": []}]}

    def answer(req: httpx.Request) -> httpx.Response:
        if str(req.url).endswith("/predictions/p1/result"):
            return httpx.Response(200, json={"data": ws_result})
        return ws(req)

    engine = KeyedSpeechEngine(
        Here(), keys, lambda: httpx.AsyncClient(transport=httpx.MockTransport(answer)), poll_s=0
    )
    res = await engine.transcribe(engine.resolve("transcribe", None), WAV, {})
    ((url, body),) = ws.posts()
    assert url.endswith("/wavespeed-ai/openai-whisper") and body["audio"].startswith("https://")
    assert res.text == "Hi."


# ---- change a voice ----------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["fal", "wavespeed"])
async def test_chatterbox_changes_a_voice(tmp_path, provider):
    keys = await on("voicechange", "chatterbox-sts", provider)
    f = fake(provider)
    engine = KeyedSpeechEngine(Here(), keys, f.client, poll_s=0)
    model = engine.resolve("convert", None)
    assert model.id == KEYED_CHANGE and model.convert["input_rate"] == 44100
    src, ref = tmp_path / "said.wav", tmp_path / "voice.wav"
    src.write_bytes(a_wav(4.0))
    ref.write_bytes(a_wav(5.0))
    res = await engine.convert(model, ConvertRequest({}, None, 4.0), src, ref)
    url, body = f.posts()[-1]
    if provider == "fal":
        assert url.endswith("/fal-ai/chatterbox/speech-to-speech")
        assert set(body) == {"source_audio_url", "target_voice_audio_url"}
    else:
        assert url.endswith("/chatterbox/speech-to-speech")
        assert set(body) == {"audio", "reference_audio"}
    assert res.wav[:4] == b"RIFF"
