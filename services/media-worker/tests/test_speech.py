"""Text to speech in the worker (ADR-0042): splitting text in any script, joining the pieces,
and the runner against a speech server played by an httpx mock transport."""

import io
import json
import re
import wave

import httpx
import pytest
from wasifyai_media_worker.backends import BackendRouter, BackendUnavailable
from wasifyai_media_worker.comfy import ComfyError
from wasifyai_media_worker.processor import StubRunner
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_media_worker.speech import OpenAISpeechRunner, join_wavs, split_text
from wasifyai_platform_sdk import InMemoryMediaBindingStore, JobRequest, SecretBox

RUN, THREAD = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


def wav(seconds: float = 0.1, rate: int = 24000, channels: int = 1) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds) * channels)
    return out.getvalue()


def seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


def job(**inputs) -> JobRequest:
    base = {"text": "Hello there.", "engine": "kokoro", "voice": "af_heart", "model": "m"}
    return JobRequest(
        tenant_id="t1", product_id="p1", user_id="u1", run_id=RUN, thread_id=THREAD,
        capability="speech.synthesize", workflow="speech", prompt={},
        inputs={**base, **inputs}, outputs={"audio": {"node": "", "type": "audio"}},
    )  # fmt: skip


async def progress(p: float) -> None:
    pass


# ---- splitting -----------------------------------------------------------------------------


def test_text_is_split_at_sentence_ends_in_any_script_and_nothing_is_lost():
    cases = [
        "First sentence. Second one! Is this the third? Yes it is.",
        "यह पहला वाक्य है। यह दूसरा है। क्या यह तीसरा है?",
        "今天天气很好。明天我们去乡下！你想一起去吗？",
        "これは一つ目です。これは二つ目です。",
        "Hola. ¿Qué tal? Muy bien, gracias.",
    ]
    for text in cases:
        pieces = split_text(text, max_chars=20)
        assert all(len(p) <= 20 for p in pieces)
        assert "".join(re.sub(r"\s", "", p) for p in pieces) == re.sub(r"\s", "", text)


def test_short_sentences_are_put_together_up_to_the_limit():
    assert split_text("One. Two. Three.", 400) == ["One. Two. Three."]
    assert split_text("One. Two. Three.", 9) == ["One. Two.", "Three."]


def test_a_long_sentence_is_cut_at_commas_then_spaces_then_the_limit():
    comma = "alpha beta, gamma delta, epsilon zeta, eta theta"
    assert split_text(comma, 25) == ["alpha beta, gamma delta,", "epsilon zeta, eta theta"]
    spaces = " ".join(["word"] * 12)
    parts = split_text(spaces, 20)
    assert all(len(p) <= 20 for p in parts) and " ".join(parts) == spaces
    assert split_text("x" * 45, 20) == ["x" * 20, "x" * 20, "x" * 5]  # no spaces at all
    assert split_text("   ", 20) == [] and split_text("", 20) == []


def test_join_adds_a_pause_and_refuses_pieces_in_different_formats():
    joined = join_wavs([wav(0.1), wav(0.2)], pause_s=0.3)
    assert seconds(joined) == pytest.approx(0.6, abs=0.001)
    assert seconds(join_wavs([wav(0.1)])) == pytest.approx(0.1, abs=0.001)
    with pytest.raises(ComfyError, match="audio format"):
        join_wavs([wav(0.1, rate=24000), wav(0.1, rate=16000)])


# ---- the runner ----------------------------------------------------------------------------


def speech_server(calls, status=200, body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append((str(request.url), payload, request.headers.get("authorization")))
        if status != 200:
            return httpx.Response(status, text="boom")
        return httpx.Response(200, content=body or wav(0.2), headers={"content-type": "audio/wav"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_each_piece_is_asked_of_the_engines_server_and_the_result_is_one_wav():
    calls: list = []
    runner = OpenAISpeechRunner(
        {"kokoro": "http://speech:8000/", "indic": "http://other:9"}, 30, speech_server(calls)
    )
    seen: list[float] = []

    async def record(p: float) -> None:
        seen.append(p)

    out = await runner.run(
        job(text="One sentence here. Another sentence here.", max_chars=25, speed=1.1), record
    )
    ((name, (data, ctype, ext)),) = out.items()
    assert (name, ctype, ext) == ("audio", "audio/wav", "wav")
    assert [c[0] for c in calls] == ["http://speech:8000/v1/audio/speech"] * 2
    assert calls[0][1] == {
        "model": "m", "voice": "af_heart", "input": "One sentence here.",
        "response_format": "wav", "speed": 1.1,
    }  # fmt: skip
    assert seconds(data) == pytest.approx(0.2 + 0.3 + 0.2, abs=0.01)
    assert seen[-1] == 1.0 and seen == sorted(seen)


async def test_another_engine_uses_its_own_server_and_a_missing_one_is_a_clean_error():
    calls: list = []
    runner = OpenAISpeechRunner(
        {"kokoro": "http://a", "indic-parler": "http://b"}, 30, speech_server(calls)
    )
    await runner.run(job(engine="indic-parler"), progress)
    assert calls[0][0] == "http://b/v1/audio/speech"
    with pytest.raises(ComfyError) as e:
        await runner.run(job(engine="nope"), progress)
    assert e.value.code == "backend_misconfigured" and "nope" not in e.value.message


@pytest.mark.parametrize("missing", ["text", "voice", "model"])
async def test_a_request_without_text_voice_or_model_is_refused(missing):
    runner = OpenAISpeechRunner({"kokoro": "http://a"}, 30, speech_server([]))
    with pytest.raises(ComfyError) as e:
        await runner.run(job(**{missing: ""}), progress)
    assert e.value.code == "invalid_workflow"


async def test_server_trouble_is_translated_and_junk_audio_is_not_returned():
    for status, error in ((500, BackendUnavailable), (429, BackendUnavailable), (422, ComfyError)):
        runner = OpenAISpeechRunner({"kokoro": "http://a"}, 30, speech_server([], status=status))
        with pytest.raises(error):
            await runner.run(job(), progress)
    junk = OpenAISpeechRunner({"kokoro": "http://a"}, 30, speech_server([], body=b"not a wav"))
    with pytest.raises(ComfyError, match="unusable audio"):
        await junk.run(job(), progress)


async def test_a_key_is_sent_when_there_is_one():
    calls: list = []
    runner = OpenAISpeechRunner({"kokoro": "http://a"}, 30, speech_server(calls), api_key="sk-x")
    await runner.run(job(), progress)
    assert calls[0][2] == "Bearer sk-x"


# ---- the router ----------------------------------------------------------------------------


def router(settings: WorkerSettings) -> BackendRouter:
    default = StubRunner()
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    return BackendRouter(
        default, settings, InMemoryMediaBindingStore(), SecretBox(SecretBox.generate_key()), http
    )


def test_the_settings_parse_the_engine_map():
    s = WorkerSettings(
        speech_servers="kokoro=http://speech:8000, indic-parler = http://i:9,broken,=x"
    )
    assert s.speech_server_map == {"kokoro": "http://speech:8000", "indic-parler": "http://i:9"}
    assert WorkerSettings().speech_server_map == {
        "kokoro": "http://speech:8000",
        "indic-parler": "http://speech-indic:8000",
        "whisper": "http://speech:8000",
        "indic-stt": "http://stt-indic:8000",
    }


async def test_speech_jobs_go_to_the_speech_runner_and_in_stub_mode_to_the_stub():
    r = router(WorkerSettings(speech_servers="kokoro=http://speech:8000"))
    chosen = await r.resolve(job())
    assert isinstance(chosen, OpenAISpeechRunner) and chosen.local_gpu is False
    stub = router(WorkerSettings(comfyui_mode="stub"))
    assert isinstance(await stub.resolve(job()), StubRunner)
