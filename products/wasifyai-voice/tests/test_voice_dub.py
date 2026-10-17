"""Dubbing (V6): the script (separate, write down, translate) and the dub (speak, fit, mix), on a
fake engine and a scripted language model; the pure parts; and the mixing with the real ffmpeg when
there is one."""

import io
import shutil
import wave

import pytest
from test_voice_graph import CTX, Rig, ctx, library_track  # noqa: F401
from voice_rig import FakeEngine
from wasifyai_platform_sdk import RunError
from wasifyai_voice import dubbing
from wasifyai_voice.runtime import store_for

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

SCRIPT = [
    {"start": 0.0, "end": 1.0, "source": "Hello there.", "text": "Hola."},
    {
        "start": 1.5,
        "end": 3.0,
        "source": "Second sentence.",
        "text": "Segunda frase, un poco más larga.",
    },
]


# ---- the parts that are not a model ----------------------------------------------------------


def test_a_language_is_its_two_letters_and_a_model_says_which_it_speaks():
    assert dubbing.base("en-US") == "en" and dubbing.base("pt_BR") == "pt"
    assert dubbing.language_name("de") == "German" and dubbing.language_name("xx") == "xx"
    models = FakeEngine().models_by_id
    assert dubbing.supports(models["kokoro-82m"], "en") and not dubbing.supports(
        models["kokoro-82m"], "es"
    )
    assert dubbing.supports(models["qwen3-tts-0.6b-base"], "ES")


def test_a_script_is_checked_line_by_line_in_words():
    ok = dubbing.clean_segments(SCRIPT, 3.0)
    assert [s.text for s in ok][0] == "Hola." and ok[1].end == 3.0
    for raw, code in (
        (None, "script_required"),
        ([], "script_required"),
        ([{"start": 0, "end": 1, "text": " "}], "empty_line"),
        ([{"start": "a", "end": 1, "text": "x"}], "bad_line"),
        ([{"start": 2, "end": 1, "text": "x"}], "bad_time"),
        ([{"start": 0, "end": 9, "text": "x"}], "bad_time"),
        (
            [{"start": 0, "end": 2, "text": "x"}, {"start": 1, "end": 3, "text": "y"}],
            "lines_overlap",
        ),
        ([{"start": 0, "end": 1, "text": "x" * 5001}], "line_too_long"),
        ([{"start": 0, "end": 1, "text": "x"}] * 401, "too_many_lines"),
    ):
        with pytest.raises(dubbing.DubError) as e:
            dubbing.clean_segments(raw, 3.0)  # type: ignore[arg-type]
        assert e.value.code == code


def test_a_line_may_take_until_the_next_one_starts_and_is_sped_up_only_so_far():
    segs = dubbing.clean_segments(SCRIPT, 3.0)
    assert dubbing.slots(segs, 3.0) == [1.5, 1.5 + 2.0]
    assert dubbing.tempo_for(1.0, 1.5) == (1.0, 0.0)  # fits: left alone
    assert dubbing.tempo_for(1.8, 1.5)[0] == pytest.approx(1.2)  # sped up to fit exactly
    tempo, over = dubbing.tempo_for(3.0, 1.5)  # twice as long: sped up as far as is allowed
    assert tempo == dubbing.MAX_TEMPO and over == pytest.approx(3.0 / 1.3 - 1.5)


def test_the_voice_to_copy_is_the_longest_stretch_in_the_models_range():
    segs = [
        dubbing.Segment(0, 2, "two seconds only here", ""),
        dubbing.Segment(3, 10, "seven seconds of one voice speaking", ""),
        dubbing.Segment(11, 51, "far too long for the model to copy from", ""),
        dubbing.Segment(41, 50, "no", ""),
    ]
    assert dubbing.pick_reference(segs, 3, 30) == segs[1]
    assert dubbing.pick_reference(segs[:1], 3, 30) is None
    assert dubbing.pick_reference(segs[3:], 3, 30) is None  # nine seconds, but two words


def test_the_translation_is_read_from_a_json_answer_and_anything_else_is_asked_again():
    assert dubbing.parse_translation('Here: ["Hola.", "Adiós."]', 2) == ["Hola.", "Adiós."]
    assert dubbing.parse_translation('```json\n[{"text": "Hola."}]\n```', 1) == ["Hola."]
    assert dubbing.parse_translation('<think>x</think>["a"]', 1) == ["a"]
    for bad in ("no list", '["one"]', '["a", ""]', '["a", 3]', "[broken"):
        assert dubbing.parse_translation(bad, 2) is None
    segs = dubbing.clean_segments(SCRIPT, 3.0)
    msg = dubbing.translation_messages(segs, "es")
    assert "Spanish" in msg[0]["content"] and "Hello there." in msg[1]["content"]
    assert dubbing.clean_line('<think>x</think> "Hola."') == "Hola."


def test_the_mix_puts_each_line_at_its_time_over_the_background():
    lines = [
        dubbing.Placement(__import__("pathlib").Path("a.wav"), 0.0, 1.0),
        dubbing.Placement(__import__("pathlib").Path("b.wav"), 1.5, 1.2),
    ]
    graph = dubbing.mix_script(2, True, lines, 3.0)
    assert "[1:a]aresample=44100,pan=stereo|c0=c0|c1=c0,adelay=0|0[s1]" in graph
    assert "[2:a]atempo=1.2000,aresample=44100,pan=stereo|c0=c0|c1=c0,adelay=1500|1500[s2]" in graph
    assert "[b][s1][s2]amix=inputs=3:normalize=0:duration=longest" in graph and "alimiter" in graph


def rms(data: bytes, start: float, end: float) -> float:
    with wave.open(io.BytesIO(data)) as w:
        rate = w.getframerate()
        w.setpos(int(start * rate))
        frames = w.readframes(int((end - start) * rate))
    import array

    samples = array.array("h", frames)
    return (sum(x * x for x in samples) / max(1, len(samples))) ** 0.5


def tone(path, seconds, rate=24000, amp=8000):
    import math

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(
            b"".join(
                int(amp * math.sin(2 * math.pi * 440 * i / rate)).to_bytes(2, "little", signed=True)
                for i in range(int(rate * seconds))
            )
        )


@needs_ffmpeg
async def test_the_real_mix_has_each_line_at_its_time_and_silence_between(tmp_path):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    tone(a, 1.0)
    tone(b, 1.0)
    out = await dubbing.mix(
        None,
        [dubbing.Placement(a, 0.5, 1.0), dubbing.Placement(b, 3.0, 1.0)],
        5.0,
        tmp_path / "out.wav",
    )
    with wave.open(io.BytesIO(out)) as w:
        assert w.getframerate() == 44100 and w.getnchannels() == 2
        assert w.getnframes() / 44100 == pytest.approx(7.0, abs=0.15)
    assert rms(out, 0.6, 1.4) > 1000 and rms(out, 3.1, 3.9) > 1000
    assert rms(out, 1.8, 2.8) < 50 and rms(out, 4.5, 6.0) < 50


@needs_ffmpeg
async def test_a_line_that_runs_past_the_end_of_the_recording_is_not_cut_off(tmp_path):
    line = tmp_path / "line.wav"
    tone(line, 4.0)
    out = await dubbing.mix(None, [dubbing.Placement(line, 2.0, 1.0)], 3.0, tmp_path / "o.wav")
    with wave.open(io.BytesIO(out)) as w:
        assert w.getnframes() / 44100 == pytest.approx(6.0, abs=0.15)  # the line ends at 6 s
    assert rms(out, 5.0, 5.9) > 1000


@needs_ffmpeg
async def test_the_real_mix_keeps_the_background_under_the_lines(tmp_path):
    bg, line = tmp_path / "bg.wav", tmp_path / "line.wav"
    tone(bg, 4.0, 44100, 2000)
    tone(line, 1.0, 24000, 9000)
    out = await dubbing.mix(bg, [dubbing.Placement(line, 1.0, 1.0)], 4.0, tmp_path / "o.wav")
    assert rms(out, 0.1, 0.9) > 500  # the background alone
    assert rms(out, 1.1, 1.9) > rms(out, 0.1, 0.9) * 2  # with the line on top
    assert rms(out, 2.5, 3.5) == pytest.approx(rms(out, 0.1, 0.9), rel=0.2)


# ---- the script ------------------------------------------------------------------------------


def array_of(*lines: str) -> dict:
    import json

    return {"text": json.dumps(list(lines), ensure_ascii=False)}


async def test_a_script_is_written_separating_the_voice_first(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, turns=[array_of("Hola.", "Segunda frase.")])
    await library_track(rig, rate=44100, channels=2, seconds=3.0)
    final, events = await rig.run(
        task="dub_script", source_track="song", language="es", background=True
    )
    assert final["status"] == "done" and final["language"] == "es"
    assert [(s["start"], s["end"], s["source"], s["text"]) for s in final["segments"]] == [
        (0.0, 1.0, "Hello there.", "Hola."),
        (1.5, 3.0, "Second sentence.", "Segunda frase."),
    ]
    store = store_for(rig.state)
    vocals = store.get_track("t1", "u1", final["vocals_track"])
    background = store.get_track("t1", "u1", final["background_track"])
    assert (
        vocals["mode"] == "stem" and background["mode"] == "stem" and vocals["parent_id"] == "song"
    )
    assert [m for m, *_ in rig.engine.separated] == ["mel-band-roformer"]
    assert rig.engine.transcribed and "Spanish" in rig.model.chats[0]["messages"][0]["content"]
    assert [e["node"] for e in events if e["type"] == "node"] == [
        "check_request", "separate", "transcribe", "translate",
    ]  # fmt: skip


async def test_a_script_without_separating_hears_the_recording_as_it_is(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, turns=[array_of("Hola.", "Segunda frase.")])
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    final, _ = await rig.run(task="dub_script", source_track="song", language="es")
    assert final["status"] == "done" and "vocals_track" not in final
    assert rig.engine.separated == []


async def test_a_translation_that_is_not_the_right_lines_is_asked_for_line_by_line(tmp_path, ctx):  # noqa: F811
    rig = Rig(
        tmp_path, turns=[{"text": "Sorry I cannot"}, {"text": "Hola."}, {"text": "Segunda frase."}]
    )
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    final, _ = await rig.run(task="dub_script", source_track="song", language="es")
    assert [s["text"] for s in final["segments"]] == ["Hola.", "Segunda frase."]
    assert len(rig.model.chats) == 3


@pytest.mark.parametrize(
    "extra, code",
    [({"language": "xx"}, "unknown_language"), ({"language": "ja"}, "no_voice_for_language")],
)  # fmt: skip
async def test_a_script_that_cannot_be_made_is_refused_before_any_work(tmp_path, ctx, extra, code):  # noqa: F811
    engine = FakeEngine(
        ready={"kokoro-82m", "parakeet-tdt-0.6b-v3", "mel-band-roformer", "htdemucs"}
    )
    rig = Rig(tmp_path, engine)
    await library_track(rig, rate=16000, channels=1)
    final, _ = await rig.run(task="dub_script", **{"source_track": "song", **extra})
    assert final["refusal"]["code"] == code
    assert engine.separated == [] and engine.transcribed == []


async def test_a_missing_recording_is_said_so(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path)
    final, _ = await rig.run(task="dub_script", source_track="nope", language="es")
    assert final["refusal"]["code"] == "unknown_source"


async def test_a_recording_with_no_speech_is_said_so(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path)
    await library_track(rig, rate=16000, channels=1)

    async def silent(model, data, options):
        from wasifyai_platform_sdk import TranscriptResult

        return TranscriptResult("", (), 3.0, model.id, 0.1)

    rig.engine.transcribe = silent  # type: ignore[method-assign]
    final, _ = await rig.run(task="dub_script", source_track="song", language="es")
    assert final["refusal"]["code"] == "no_speech"


# ---- the dub ----------------------------------------------------------------------------------


@needs_ffmpeg
async def test_a_dub_speaks_each_line_fits_it_and_is_kept_as_a_track(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path)
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    english = [
        {"start": 0.0, "end": 1.0, "source": "Hola.", "text": "Hello."},
        {
            "start": 1.5,
            "end": 3.0,
            "source": "Frase.",
            "text": "A second and slightly longer sentence.",
        },
    ]
    final, events = await rig.run(
        task="dub", source_track="song", language="en", segments=english, voice_from="builtin",
        voice="am_adam",
    )  # fmt: skip
    assert final["status"] == "done" and final["title"] == "Summer (English)"
    spoken = [(m, t, v) for m, t, v, _ in rig.engine.spoken]
    assert spoken == [
        ("kokoro-82m", "Hello.", "am_adam"),
        ("kokoro-82m", "A second and slightly longer sentence.", "am_adam"),
    ]
    store = store_for(rig.state)
    saved = store.get_track("t1", "u1", final["track_id"])
    assert (
        saved["mode"] == "dubbed" and saved["parent_id"] == "song" and saved["sample_rate"] == 44100
    )
    assert saved["edit"]["action"] == "dub" and saved["edit"]["language"] == "en"
    assert saved["edit"]["voice"] == "am_adam" and saved["edit"]["consent"] is None
    assert [s["text"] for s in saved["edit"]["segments"]][0] == "Hello."
    assert final["fit"]["lines"] == 2 and final["fit"]["sped_up"] >= 0
    assert rig.indexed[-1][0] == "track"
    labels = [e["label"] for e in events if e["type"] == "node"]
    assert labels == ["Checking", "Speaking line 1 of 2", "Speaking line 2 of 2", "Mixing"]
    assert not list((store.root / "tmp").iterdir())  # the working folder is gone


@needs_ffmpeg
async def test_copying_the_speaker_needs_their_word_and_cuts_their_voice(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path)
    await library_track(rig, track_id="song", rate=44100, channels=2, seconds=12.0)
    await library_track(rig, track_id="vox", title="Vocals", rate=44100, channels=2, seconds=12.0)
    await library_track(
        rig, track_id="bg", title="Background", rate=44100, channels=2, seconds=12.0
    )
    script = [
        {
            "start": 0.0,
            "end": 8.0,
            "source": "A long enough stretch of speech",
            "text": "Un tramo largo de voz.",
        },
        {"start": 9.0, "end": 11.0, "source": "And a short one", "text": "Y uno corto."},
    ]
    asked = {"task": "dub", "source_track": "song", "language": "es", "segments": script,
             "voice_from": "speaker", "vocals_track": "vox"}  # fmt: skip
    final, _ = await rig.run(**asked)
    assert final["refusal"]["code"] == "consent_required" and rig.engine.cloned == []
    final, _ = await rig.run(**asked, speaker_basis="own", background_track="bg")
    assert final["status"] == "done"
    model, text, ref_name, ref_text, _ = rig.engine.cloned[0]
    assert model == "qwen3-tts-0.6b-base" and text == "Un tramo largo de voz."
    assert ref_name == "reference.wav"
    assert ref_text == "A long enough stretch of speech"  # the words of the stretch it copied from
    saved = store_for(rig.state).get_track("t1", "u1", final["track_id"])
    assert (
        saved["edit"]["consent"]["basis"] == "own"
        and saved["edit"]["voice"] == "the original speaker"
    )
    assert saved["sample_rate"] == 44100 and saved["seconds"] > 11


@needs_ffmpeg
async def test_a_dub_that_cannot_be_made_is_refused_in_words(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path)
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    base = {"task": "dub", "source_track": "song", "segments": SCRIPT}
    for extra, code in (
        ({"language": "xx"}, "unknown_language"),
        (
            {"language": "es", "voice_from": "builtin"},
            "no_voice_for_language",
        ),  # Kokoro is English only
        ({"language": "es", "voice_from": "saved", "saved_voice": "ghost"}, "unknown_voice"),
        ({"language": "es", "voice_from": "speaker", "speaker_basis": "own"}, "no_reference"),
        ({"language": "en", "segments": None}, "script_required"),
        ({"language": "en", "model": "qwen3-tts-0.6b-base"}, "no_voice_for_language"),
    ):
        final, _ = await rig.run(**{**base, **extra})
        assert final["refusal"]["code"] == code, extra
    assert rig.engine.spoken == [] and rig.engine.cloned == []


async def test_without_ffmpeg_a_dub_says_what_is_missing(tmp_path, ctx, monkeypatch):  # noqa: F811
    monkeypatch.setattr(dubbing, "find_converter", lambda: None)
    rig = Rig(tmp_path)
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    final, _ = await rig.run(task="dub", source_track="song", language="en", segments=SCRIPT)
    assert final["refusal"]["code"] == "needs_ffmpeg" and "ffmpeg" in final["refusal"]["message"]


async def test_a_translation_failure_ends_the_run_with_a_code(tmp_path, ctx):  # noqa: F811
    rig = Rig(tmp_path, turns=[{"text": "nope"}, {"text": ""}])
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    with pytest.raises(RunError) as e:
        await rig.run(task="dub_script", source_track="song", language="es")
    assert e.value.code == "translation_failed" and e.value.retryable
