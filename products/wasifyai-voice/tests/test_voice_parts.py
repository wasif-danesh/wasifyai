"""The smaller parts: getting audio into WAV, the store, the search index, the exports."""

import sqlite3

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from voice_rig import wav
from wasifyai_voice import audio_input, export
from wasifyai_voice.index import VoiceIndexSource
from wasifyai_voice.store import NotFound, VoiceStore


async def test_a_wav_passes_through_untouched():
    data = wav(0.3)
    assert await audio_input.to_wav(data, "a.wav") is data


async def test_empty_and_oversized_files_are_refused(monkeypatch):
    with pytest.raises(audio_input.AudioInputError) as e:
        await audio_input.to_wav(b"", "a.wav")
    assert e.value.code == "empty"
    monkeypatch.setattr(audio_input, "MAX_BYTES", 10)
    with pytest.raises(audio_input.AudioInputError) as e:
        await audio_input.to_wav(b"x" * 11, "a.wav")
    assert e.value.code == "too_large"


async def test_other_formats_need_a_converter_and_get_one_when_there_is_one(monkeypatch):
    monkeypatch.setattr(audio_input, "find_converter", lambda: None)
    with pytest.raises(audio_input.AudioInputError) as e:
        await audio_input.to_wav(b"ID3 not wav", "a.mp3")
    assert e.value.code == "needs_converter"


@pytest.mark.skipif(
    not (__import__("shutil").which("afconvert") or __import__("shutil").which("ffmpeg")),
    reason="neither afconvert nor ffmpeg is on this computer",
)
async def test_a_real_conversion_gives_sixteen_kilohertz_mono_wav(tmp_path):
    import asyncio
    import wave

    src = tmp_path / "in.wav"
    src.write_bytes(wav(0.5, 44100))
    conv = audio_input.find_converter()
    assert conv is not None
    out = tmp_path / "in.caf"
    args = (
        [conv[1], "-nostdin", "-loglevel", "error", "-i", str(src), str(out)]
        if conv[0] == "ffmpeg"
        else [conv[1], "-f", "caff", "-d", "LEI16", str(src), str(out)]
    )
    await (await asyncio.create_subprocess_exec(*args)).wait()
    data = await audio_input.to_wav(out.read_bytes(), "in.caf")
    with wave.open(__import__("io").BytesIO(data)) as w:
        assert (w.getframerate(), w.getnchannels()) == (16000, 1)
    with pytest.raises(audio_input.AudioInputError) as e:
        await audio_input.to_wav(b"this is not audio at all", "x.bin")
    assert e.value.code == "unsupported_audio"


def test_exports_handle_no_segments_and_awkward_titles():
    t = {"text": "Just text.", "segments": []}
    assert export.render(t, "srt") == "Just text.\n"
    assert export.file_name("a/b: c?", "txt") == "a_b_ c.txt"
    assert export.file_name("", "srt") == "transcript.srt"
    assert export._stamp(3725.5, True) == "01:02:05,500"  # noqa: SLF001


def test_the_store_keeps_each_persons_things_apart_and_refuses_a_newer_file(tmp_path):
    s = VoiceStore(tmp_path)
    t = s.add_transcript(
        "t", "u", title="x", source_name="x.wav", model_id="m", text="hello",
        segments=[{"start": 0, "end": 1, "text": "hello"}], seconds=1, elapsed_s=0.1,
    )  # fmt: skip
    assert s.get_transcript("t", "u", t["id"])["segments"][0]["text"] == "hello"
    with pytest.raises(NotFound):
        s.get_transcript("t", "other", t["id"])
    with pytest.raises(NotFound):
        s.get_transcript("other", "u", t["id"])
    with sqlite3.connect(s.path) as db:
        db.execute("UPDATE meta SET value = '99' WHERE key = 'schema'")
    with pytest.raises(RuntimeError, match="newer"):
        VoiceStore(tmp_path)


async def test_the_index_source_pages_both_kinds_and_knows_what_is_gone(tmp_path):
    s = VoiceStore(tmp_path / "voice")
    s.add_speech(
        "t", "u", text="spoken words", model_id="m", voice=None, options={}, seconds=1,
        sample_rate=24000, audio_key="k", load_s=0, elapsed_s=0, speech_id="a",
    )  # fmt: skip
    s.add_transcript(
        "t", "u", title="Meeting", source_name="", model_id="m", text="we met", segments=[],
        seconds=1, elapsed_s=0, transcript_id="b",
    )  # fmt: skip
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wasifyai.db'}")
    src = VoiceIndexSource(engine)
    items = await src.page(None, 10)
    assert [(i.item_id, i.kind) for i in items] == [("a", "speech"), ("b", "transcript")]
    assert items[0].text == "spoken words" and items[1].text.startswith("Meeting")
    assert [i.item_id for i in await src.page("a", 10)] == ["b"]
    assert await src.present(["a", "b", "zz"]) == {"a", "b"}
    assert await src.present([]) == set()
    await engine.dispose()


def test_a_version_one_file_is_upgraded_in_place(tmp_path):
    root = tmp_path / "voice"
    root.mkdir()
    with sqlite3.connect(root / "voice.db") as db:
        db.executescript(
            "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "INSERT INTO meta VALUES ('schema', '1');"
            "CREATE TABLE speeches(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, "
            "user_id TEXT NOT NULL, text TEXT NOT NULL, model_id TEXT NOT NULL, voice TEXT, "
            "options TEXT NOT NULL DEFAULT '{}', seconds REAL NOT NULL, "
            "sample_rate INTEGER NOT NULL, audio_key TEXT NOT NULL, "
            "load_s REAL NOT NULL DEFAULT 0, elapsed_s REAL NOT NULL DEFAULT 0, "
            "created_at TEXT NOT NULL);"
            "CREATE TABLE transcripts(id TEXT PRIMARY KEY);"
            "INSERT INTO speeches VALUES "
            "('old','t','u','hi','kokoro-82m',NULL,'{}',1,24000,'k',0,0,'x');"
        )
    s = VoiceStore(root)
    old = s.get_speech("t", "u", "old")
    assert (old["mode"], old["saved_voice_id"]) == ("speak", None)
    v = s.add_voice("t", "u", kind="design", name="n", description="a man")
    assert s.list_voices("t", "u")[0]["id"] == v["id"]
    VoiceStore(root)  # opening an upgraded file again is fine


def test_voices_are_kept_apart_and_a_reference_path_cannot_leave_its_folder(tmp_path):
    s = VoiceStore(tmp_path)
    v = s.add_voice("t", "u", kind="clone", name="n", reference_key="k", reference_seconds=3.0)
    with pytest.raises(NotFound):
        s.get_voice("t", "other", v["id"])
    with pytest.raises(NotFound):
        s.reference_path("../evil")
    assert s.reference_path(v["id"]).parent == tmp_path / "voices"


async def test_the_index_source_also_pages_voices(tmp_path):
    s = VoiceStore(tmp_path / "voice")
    s.add_voice("t", "u", kind="design", name="Calm", description="a deep man", voice_id="v1")
    s.add_voice("t", "u", kind="clone", name="Me", voice_id="v2")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wasifyai.db'}")
    src = VoiceIndexSource(engine)
    items = await src.page(None, 10)
    assert [(i.item_id, i.kind, i.text) for i in items] == [
        ("v1", "voice", "Calm. a deep man"),
        ("v2", "voice", "Me. cloned voice"),
    ]
    assert await src.present(["v1", "v2", "zz"]) == {"v1", "v2"}
    await engine.dispose()


async def test_a_recording_is_cut_at_thirty_seconds_and_refused_under_two(monkeypatch):
    from wasifyai_voice import reference

    long, seconds = await reference.prepare(wav(45.0, 8000), "a.wav")
    assert seconds == 30.0
    with pytest.raises(audio_input.AudioInputError) as e:
        await reference.prepare(wav(1.5), "a.wav")
    assert e.value.code == "too_short"
    monkeypatch.setattr(audio_input, "find_converter", lambda: None)
    float_wav = bytearray(wav(3.0))
    float_wav[20:22] = (3).to_bytes(2, "little")  # format 3: float samples
    with pytest.raises(audio_input.AudioInputError) as e:
        await reference.prepare(bytes(float_wav), "f.wav")
    assert e.value.code in ("unsupported_audio", "needs_converter")
    assert len(long) < len(wav(45.0, 8000))


def test_a_version_two_file_gains_tracks_and_the_index_pages_them(tmp_path):
    root = tmp_path / "voice"
    s = VoiceStore(root)
    with sqlite3.connect(s.path) as db:
        db.execute("DROP TABLE tracks")
        db.execute("UPDATE meta SET value = '2' WHERE key = 'schema'")
    s = VoiceStore(root)
    t = s.add_track(
        "t", "u", title="Song", mode="song", description="pop", lyrics="", instrumental=True,
        model_id="m", options={}, seed=None, seconds=1, sample_rate=24000, audio_key="k",
        load_s=0, elapsed_s=0, track_id="tr1",
    )  # fmt: skip
    assert t["instrumental"] is True and t["seed"] is None
    with pytest.raises(NotFound):
        s.get_track("t", "other", "tr1")


async def test_the_index_source_also_pages_tracks(tmp_path):
    s = VoiceStore(tmp_path / "voice")
    s.add_track(
        "t", "u", title="Summer", mode="song", description="pop upbeat", lyrics="la la",
        instrumental=False, model_id="m", options={}, seed=1, seconds=1, sample_rate=1,
        audio_key="k", load_s=0, elapsed_s=0, track_id="tr1",
    )  # fmt: skip
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wasifyai.db'}")
    src = VoiceIndexSource(engine)
    items = await src.page(None, 10)
    assert [(i.item_id, i.kind, i.text) for i in items] == [
        ("tr1", "track", "Summer. pop upbeat. la la")
    ]
    assert await src.present(["tr1", "zz"]) == {"tr1"}
    await engine.dispose()
