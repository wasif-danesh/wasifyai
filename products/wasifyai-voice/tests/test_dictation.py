"""Dictation (ADR-0083, decision 5): a clip in, text out, nothing kept, hostile clips refused."""

import io
import logging
import math
import struct
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from voice_rig import FakeEngine, app_state
from wasifyai_platform_sdk import Identity, RouteDeps, VoiceEngineError
from wasifyai_voice import dictation
from wasifyai_voice.routes import build_routes


def clip(seconds=1.0, rate=16000, channels=1, loud=0.3, width=2) -> bytes:
    """A tone at `loud` of full scale (0 is silence)."""
    n = int(rate * seconds)
    frames = b"".join(
        struct.pack("<h", int(loud * 32767 * math.sin(i / 20))) * channels for i in range(n)
    )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(frames if width == 2 else frames[: n * channels * width])
    return buf.getvalue()


@pytest.fixture
def api(tmp_path):
    engine = FakeEngine()
    state = app_state(tmp_path, engine)

    async def identity() -> Identity:
        return Identity("t1", "u1")

    app = FastAPI()
    app.include_router(build_routes(RouteDeps(state, identity)), prefix="/products/wasifyai-voice")
    with TestClient(app) as c:
        c.base_url = c.base_url.join("/products/wasifyai-voice/")
        yield c, engine, state, tmp_path


def send(c, data: bytes, name="dictation.wav"):
    return c.post("dictation", files={"file": (name, io.BytesIO(data), "audio/wav")})


def test_a_clip_becomes_text_and_nothing_is_kept(api):
    c, engine, state, root = api
    before = sorted(p.name for p in root.rglob("*"))
    r = send(c, clip(2.0))
    assert r.status_code == 200
    assert r.json() == {
        "text": "Hello there. Second sentence.",
        "seconds": 2.0,
        "model": "parakeet-tdt-0.6b-v3",
        "displaced": None,
    }
    assert engine.beside == [True]  # dictation asks to stay beside the chat model
    assert sorted(p.name for p in root.rglob("*")) == before  # no file, no database row
    assert c.get("transcripts").json()["items"] == []


def test_the_chat_model_being_unloaded_is_passed_on(api):
    c, engine, _, _ = api
    engine.displaced = "chat"
    assert send(c, clip()).json()["displaced"] == "chat"


def test_the_words_are_not_written_to_the_log(api, caplog):
    c, engine, _, _ = api
    engine.words = "my secret sentence"
    with caplog.at_level(logging.DEBUG):
        assert send(c, clip()).json()["text"] == "my secret sentence"
    assert "secret" not in caplog.text


@pytest.mark.parametrize(
    "data, status, code",
    [
        (b"", 422, "empty"),
        (b"ID3\x03\x00\x00....an mp3 that says it is a wav" * 20, 422, "not_wav"),
        (b"RIFF\x00\x00\x00\x00WAVEjunk" * 4, 422, "not_wav"),
        (clip(1.0, rate=44100, channels=2), 422, "wrong_format"),
        (clip(1.0, rate=8000), 422, "wrong_format"),
        (clip(0.1), 422, "too_short"),
        (clip(1.0, loud=0.0), 422, "silent"),
        (clip(1.0, loud=0.001), 422, "silent"),
        (clip(305.0), 422, "too_long"),
    ],
)
def test_a_clip_the_model_should_not_get_is_refused_in_words(api, data, status, code):
    c, engine, _, _ = api
    r = send(c, data)
    assert r.status_code == status and r.json()["detail"]["code"] == code
    assert r.json()["detail"]["message"].endswith((".", "?")) and "Traceback" not in r.text
    assert engine.transcribed == []  # the model never saw it


def test_a_clip_over_the_size_limit_is_refused(api):
    c, engine, _, _ = api
    r = send(c, clip(1.0) + b"\x00" * dictation.MAX_BYTES)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "too_large"
    assert engine.transcribed == []


def test_a_header_that_claims_more_than_the_file_has_is_measured_by_its_samples(api):
    c, engine, _, _ = api
    data = bytearray(clip(0.2))
    data[40:44] = struct.pack("<I", 0x7FFFFFF0)  # the data chunk "is" two gigabytes
    data[4:8] = struct.pack("<I", 0x7FFFFFF8)
    r = send(c, bytes(data))
    assert r.status_code == 422 and r.json()["detail"]["code"] in ("too_short", "not_wav")
    assert engine.transcribed == []


def test_a_clip_with_no_words_in_it_says_so(api):
    c, engine, _, _ = api
    engine.words = "  "
    r = send(c, clip())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_speech"


def test_a_missing_model_or_runtime_is_a_conflict_with_what_to_do(api):
    c, engine, _, _ = api
    engine.ready.discard("parakeet-tdt-0.6b-v3")
    r = send(c, clip())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "model_missing"
    engine.ready.add("parakeet-tdt-0.6b-v3")
    engine.fail_with = VoiceEngineError("busy", "The speech model is busy. Try again in a moment.")
    r = send(c, clip())
    assert r.status_code == 502 and "busy" in r.json()["detail"]["message"]


def test_without_a_speech_engine_the_route_answers_503(api):
    c, _, state, _ = api
    state.audio = None
    assert send(c, clip()).status_code == 503


def test_inspect_reads_the_samples_not_the_header():
    got = dictation.inspect(clip(1.5, loud=0.5))
    assert got.seconds == pytest.approx(1.5) and 0.45 < got.peak < 0.51
