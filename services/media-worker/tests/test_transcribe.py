"""Speech to text in the worker (ADR-0043): language detection on the first 30 seconds with the
larger model, then the whole recording with the fast one, against a server played by a mock."""

import io
import json
import wave

import httpx
import pytest
from wasifyai_media_worker.backends import BackendRouter, BackendUnavailable
from wasifyai_media_worker.comfy import ComfyError
from wasifyai_media_worker.processor import StubRunner
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_media_worker.transcribe import OpenAITranscriptionRunner, first_seconds, split_pieces
from wasifyai_platform_sdk import InMemoryMediaBindingStore, JobRequest, SecretBox

RUN, THREAD = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


def wav(seconds: float, rate: int = 16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds))
    return out.getvalue()


def length(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


def job(**inputs) -> JobRequest:
    base = {
        "audio_key": "uploads/a.wav", "engine": "whisper", "model": "fast",
        "detect_model": "big", "language": "", "seconds": 60,
    }  # fmt: skip
    return JobRequest(
        tenant_id="t1", product_id="p1", user_id="u1", run_id=RUN, thread_id=THREAD,
        capability="speech.transcribe", workflow="speech", prompt={}, inputs={**base, **inputs},
        outputs={"transcript": {"node": "", "type": "json"}},
    )  # fmt: skip


async def progress(_: float) -> None:
    return None


def server(calls: list, status=200, answers=None, junk=False):
    """A transcription server: detection answers with a language, the real run with text."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        fields = {}
        for part in body.split(b"--")[1:-1]:
            head, _, value = part.partition(b"\r\n\r\n")
            if b'name="model"' in head:
                fields["model"] = value.strip().decode()
            if b'name="language"' in head:
                fields["language"] = value.strip().decode()
            if b'name="file"' in head:
                fields["file"] = value.rstrip(b"\r\n")
        calls.append((str(request.url), fields, request.headers.get("authorization")))
        if status != 200:
            return httpx.Response(status, text="boom")
        if junk:
            return httpx.Response(200, text="<html>")
        answer = (answers or {}).get(fields["model"], {})
        return httpx.Response(200, json=answer)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


REAL = {
    "text": " Hello world. ",
    "language": "en",
    "segments": [
        {"start": 0, "end": 1.2, "text": " Hello"},
        {"start": 1.2, "end": 2.0, "text": " world."},
        {"start": 2.0, "end": 2.5, "text": "  "},
    ],
}


def runner(calls, **kw):
    return OpenAITranscriptionRunner({"whisper": "http://speech:8000/"}, 30, server(calls, **kw))


def test_only_the_first_seconds_of_a_recording_are_cut_out():
    assert length(first_seconds(wav(90), 30)) == pytest.approx(30, abs=0.01)
    assert length(first_seconds(wav(5), 30)) == pytest.approx(5, abs=0.01)


async def test_without_a_language_the_first_30_seconds_decide_it_with_the_larger_model():
    calls: list = []
    r = runner(calls, answers={"big": {"language": "bn"}, "fast": {**REAL, "language": "bn"}})
    out = await r.run(job(), progress, files={"audio": wav(90)})
    assert [c[0] for c in calls] == ["http://speech:8000/v1/audio/transcriptions"] * 2
    detect, real = calls
    assert detect[1]["model"] == "big" and "language" not in detect[1]
    assert length(detect[1]["file"]) == pytest.approx(30, abs=0.01)
    assert real[1]["model"] == "fast" and real[1]["language"] == "bn"
    assert length(real[1]["file"]) == pytest.approx(90, abs=0.01)
    ((name, (data, ctype, ext)),) = out.items()
    assert (name, ctype, ext) == ("transcript", "application/json", "json")
    result = json.loads(data)
    assert result["text"] == "Hello world." and result["language"] == "bn"
    assert result["segments"] == [
        {"start": 0.0, "end": 1.2, "text": " Hello"},
        {"start": 1.2, "end": 2.0, "text": " world."},
    ]  # the empty segment is dropped


async def test_a_chosen_language_skips_detection():
    calls: list = []
    r = runner(calls, answers={"fast": REAL})
    await r.run(job(language="en"), progress, files={"audio": wav(3)})
    assert len(calls) == 1 and calls[0][1]["model"] == "fast" and calls[0][1]["language"] == "en"


async def test_progress_runs_forward_to_one():
    seen: list[float] = []

    async def record(p: float) -> None:
        seen.append(p)

    r = runner([], answers={"big": {"language": "en"}, "fast": REAL})
    await r.run(job(), record, files={"audio": wav(2)})
    assert seen[-1] == 1.0 and seen == sorted(seen)


async def test_a_job_without_a_recording_or_model_or_with_an_unknown_engine_fails_cleanly():
    r = runner([])
    with pytest.raises(ComfyError) as e:
        await r.run(job(), progress, files={})
    assert e.value.code == "invalid_workflow"
    with pytest.raises(ComfyError):
        await r.run(job(model=""), progress, files={"audio": wav(1)})
    with pytest.raises(ComfyError) as e:
        await r.run(job(engine="nope"), progress, files={"audio": wav(1)})
    assert e.value.code == "backend_misconfigured" and "nope" not in e.value.message


async def test_server_trouble_is_translated_and_a_junk_answer_is_not_returned():
    for status, error in ((500, BackendUnavailable), (429, BackendUnavailable), (422, ComfyError)):
        r = runner([], status=status)
        with pytest.raises(error):
            await r.run(job(language="en"), progress, files={"audio": wav(1)})
    with pytest.raises(ComfyError, match="unusable text"):
        await runner([], junk=True).run(job(language="en"), progress, files={"audio": wav(1)})


async def test_the_router_sends_transcription_jobs_to_this_runner_and_stub_mode_to_the_stub():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))

    def router(settings):
        return BackendRouter(
            StubRunner(), settings, InMemoryMediaBindingStore(),
            SecretBox(SecretBox.generate_key()), http,
        )  # fmt: skip

    chosen = await router(WorkerSettings()).resolve(job())
    assert isinstance(chosen, OpenAITranscriptionRunner) and chosen.local_gpu is False
    stub = await router(WorkerSettings(comfyui_mode="stub")).resolve(job())
    assert isinstance(stub, StubRunner)


# ---- the Indian languages: pieces of up to 15 seconds to the IndicConformer server ----


def speech_then_pauses(*seconds_of_sound_then_gap: tuple[float, float], rate: int = 16000) -> bytes:
    """A WAV of loud stretches separated by silences, as (loud seconds, quiet seconds) pairs."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for loud, quiet in seconds_of_sound_then_gap:
            w.writeframes(b"\xe8\x03" * int(rate * loud))  # 1000: a steady loud sample
            w.writeframes(b"\x00\x00" * int(rate * quiet))
    return out.getvalue()


def test_a_short_recording_is_one_piece_and_a_long_one_is_cut_in_the_pauses():
    one = split_pieces(wav(10))
    assert len(one) == 1 and one[0][0] == 0 and one[0][1] == pytest.approx(10, abs=0.02)
    # 3 s of sound, 0.5 s pause, repeated: 7 groups = 24.5 s, so it must be cut, and in the pauses
    audio = speech_then_pauses(*[(3.0, 0.5)] * 7)
    pieces = split_pieces(audio)
    assert len(pieces) >= 2
    assert all(b - a <= 15.01 for a, b, _ in pieces)
    assert pieces[0][0] == 0 and pieces[-1][1] == pytest.approx(24.5, abs=0.02)
    for (_, end, _), (start, _, _) in zip(pieces, pieces[1:], strict=False):
        assert end == pytest.approx(start, abs=0.001)  # nothing lost between pieces
        # the cut falls inside a pause: seconds 3.0 to 3.5 of every 3.5 s group
        assert 3.0 - 0.03 <= end % 3.5 <= 3.5 + 0.03
    assert sum(length(p) for _, _, p in pieces) == pytest.approx(24.5, abs=0.05)


def test_an_empty_recording_has_no_pieces():
    assert split_pieces(wav(0)) == []


def indic_server(calls: list, texts: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        fields = {}
        for part in body.split(b"--")[1:-1]:
            head, _, value = part.partition(b"\r\n\r\n")
            for name in (b"model", b"language", b"response_format"):
                if b'name="%s"' % name in head:
                    fields[name.decode()] = value.strip().decode()
            if b'name="file"' in head:
                fields["file"] = value.rstrip(b"\r\n")
        calls.append((str(request.url), fields))
        return httpx.Response(200, json={"text": texts[len(calls) - 1], "language": "bn"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


INDIC_JOB = {"indic_languages": ["bn", "hi"], "language": "bn"}


async def test_an_indian_language_goes_to_the_indic_server_in_pieces_with_timed_segments():
    calls: list = []
    runner = OpenAITranscriptionRunner(
        {"whisper": "http://speech:8000", "indic-stt": "http://stt:8000/"},
        30,
        indic_server(calls, ["প্রথম অংশ", "দ্বিতীয় অংশ", "তৃতীয়"]),
    )
    seen: list[float] = []

    async def record(p: float) -> None:
        seen.append(p)

    audio = speech_then_pauses(*[(3.0, 0.5)] * 7)
    out = await runner.run(job(**INDIC_JOB), record, files={"audio": audio})
    assert len(calls) >= 2 and all(c[0] == "http://stt:8000/v1/audio/transcriptions" for c in calls)
    assert {c[1]["language"] for c in calls} == {"bn"}
    result = json.loads(out["transcript"][0])
    assert result["language"] == "bn" and result["text"].startswith("প্রথম অংশ দ্বিতীয় অংশ")
    segs = result["segments"]
    assert segs[0]["start"] == 0 and segs[0]["text"] == "প্রথম অংশ"
    assert all(a["end"] <= b["start"] + 0.01 for a, b in zip(segs, segs[1:], strict=False))
    assert seen[-1] == 1.0 and seen == sorted(seen)


async def test_detection_decides_between_the_two_engines():
    calls: list = []
    http = server(calls, answers={"big": {"language": "bn"}, "fast": REAL})
    runner = OpenAITranscriptionRunner(
        {"whisper": "http://speech:8000", "indic-stt": "http://stt:8000"}, 30, http
    )
    # the detector says Bengali, which is on the product's list: Whisper is asked only to detect
    texts = ["আমাদের"]
    runner._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: (
                httpx.Response(200, json={"language": "bn"})
                if "speech:8000" in str(r.url)
                else httpx.Response(200, json={"text": texts[0], "language": "bn"})
            )
        )
    )
    out = await runner.run(job(indic_languages=["bn"]), progress, files={"audio": wav(3)})
    assert json.loads(out["transcript"][0])["text"] == "আমাদের"
    # a language that is not on the list stays on Whisper
    calls.clear()
    plain = runner_with_whisper(calls)
    await plain.run(job(language="en", indic_languages=["bn"]), progress, files={"audio": wav(2)})
    assert len(calls) == 1 and calls[0][1]["model"] == "fast"


def runner_with_whisper(calls):
    return OpenAITranscriptionRunner(
        {"whisper": "http://speech:8000", "indic-stt": "http://stt:8000"},
        30,
        server(calls, answers={"fast": REAL}),
    )


async def test_without_an_indic_server_an_indian_language_stays_on_whisper():
    calls: list = []
    r = OpenAITranscriptionRunner(
        {"whisper": "http://speech:8000"}, 30, server(calls, answers={"fast": REAL})
    )
    await r.run(job(**INDIC_JOB), progress, files={"audio": wav(2)})
    assert len(calls) == 1 and calls[0][1]["language"] == "bn" and calls[0][1]["model"] == "fast"


async def test_a_broken_indic_server_is_a_clean_error():
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, text="boom")

    r = OpenAITranscriptionRunner(
        {"whisper": "http://a", "indic-stt": "http://b"},
        30,
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(BackendUnavailable):
        await r.run(job(**INDIC_JOB), progress, files={"audio": wav(2)})
