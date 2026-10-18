"""The web's speech runtime: hosted models through the gateway, by alias."""

import io
import json
import wave
from pathlib import Path

import httpx
import pytest
from wasifyai_api.hosted_speech import HostedSpeechEngine, load_hosted_models, wav_info
from wasifyai_platform_sdk import VoiceEngineError, check_speak

MODELS = Path(__file__).resolve().parents[3] / "products/wasifyai-voice/hosted-models.yaml"


def wav(seconds: float = 0.5, rate: int = 8000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return out.getvalue()


def engine(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HostedSpeechEngine(load_hosted_models(MODELS), "http://gw:4000/", "secret", client)


def test_the_web_offers_only_what_its_descriptors_list_and_all_of_it_is_ready():
    e = engine(lambda r: httpx.Response(200))
    assert [m["id"] for m in e.models()] == ["hosted-speech", "hosted-transcribe"]
    assert [m["id"] for m in e.models("transcribe")] == ["hosted-transcribe"]
    assert e.models("music") == [] and e.models("clone") == []  # nothing for these
    assert all(m["state"] == "ready" and m["hosted"] for m in e.models())
    assert e.resolve("speak", None).id == "hosted-speech"
    assert e.resolve("transcribe", "hosted-transcribe").package == "voice-transcribe"
    with pytest.raises(VoiceEngineError) as unknown:
        e.resolve("speak", "kokoro-82m")
    assert unknown.value.code == "unknown_model"
    with pytest.raises(VoiceEngineError) as none:
        e.resolve("music", None)
    assert none.value.code == "no_model" and "coming to the web" in none.value.message


async def test_speaking_asks_the_gateway_by_alias_and_reads_the_wav():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=wav(1.5, 24000))

    e = engine(handler)
    model = e.resolve("speak", None)
    text, voice, options = check_speak(model, "Hello there", "nova", {"speed": 1.25})
    result = await e.speak(model, text, voice, options)
    assert seen["url"] == "http://gw:4000/v1/audio/speech" and seen["auth"] == "Bearer secret"
    assert seen["body"] == {
        "model": "voice-speak", "input": "Hello there", "response_format": "wav",
        "voice": "nova", "speed": 1.25,
    }  # fmt: skip
    assert (result.sample_rate, round(result.seconds, 2), result.voice) == (24000, 1.5, "nova")
    assert result.model_id == "hosted-speech" and result.wav.startswith(b"RIFF")


async def test_transcribing_sends_the_recording_and_returns_timed_segments():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "text": " Hello world. ",
                "duration": 3.2,
                "segments": [
                    {"start": 0.0, "end": 1.4, "text": " Hello"},
                    {"start": 1.4, "end": 3.2, "text": " world."},
                    {"start": 3.2, "end": 3.2, "text": "  "},
                ],
            },
        )

    e = engine(handler)
    got = await e.transcribe(e.resolve("transcribe", None), wav(), {"language": "en"})
    assert seen["url"] == "http://gw:4000/v1/audio/transcriptions"
    assert b"voice-transcribe" in seen["body"] and b"verbose_json" in seen["body"]
    assert b'name="language"' in seen["body"]
    assert got.text == "Hello world." and got.seconds == 3.2
    assert [(s.start, s.end, s.text) for s in got.segments] == [
        (0.0, 1.4, "Hello"),
        (1.4, 3.2, "world."),
    ]


async def test_a_text_only_answer_still_gives_one_segment():
    e = engine(lambda r: httpx.Response(200, json={"text": "Just words", "duration": 2}))
    got = await e.transcribe(e.resolve("transcribe", None), wav(), {})
    assert [(s.start, s.end, s.text) for s in got.segments] == [(0.0, 2.0, "Just words")]


async def test_a_busy_or_unreachable_or_refusing_service_is_told_in_words():
    def status(code):
        return engine(lambda r: httpx.Response(code, json={"error": "no"}))

    for code, expect in ((429, "busy"), (503, "busy"), (400, "engine_failed")):
        e = status(code)
        with pytest.raises(VoiceEngineError) as err:
            await e.speak(e.resolve("speak", None), "hi", "alloy", {})
        assert err.value.code == expect

    def down(request):
        raise httpx.ConnectError("no route")

    e = engine(down)
    with pytest.raises(VoiceEngineError, match="could not be reached"):
        await e.speak(e.resolve("speak", None), "hi", "alloy", {})
    e = engine(lambda r: httpx.Response(200, content=b"not audio"))
    with pytest.raises(VoiceEngineError, match="audio that could be read"):
        await e.speak(e.resolve("speak", None), "hi", "alloy", {})
    assert wav_info(wav(2.0, 8000)) == (8000, 2.0)


async def test_what_has_no_common_api_is_said_to_be_the_desktops():
    e = engine(lambda r: httpx.Response(200))
    for call in (e.clone, e.design, e.music, e.music_edit, e.separate, e.convert, e.speech_edit):
        with pytest.raises(VoiceEngineError) as err:
            await call()
        assert err.value.code == "not_offered" and "desktop app" in err.value.message


def test_a_descriptor_that_is_not_remote_is_refused(tmp_path):
    bad = tmp_path / "m.yaml"
    bad.write_text(MODELS.read_text().replace("engine: remote", "engine: audiocpp", 1))
    with pytest.raises(ValueError):
        load_hosted_models(bad)
