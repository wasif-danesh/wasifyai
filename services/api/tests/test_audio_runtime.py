"""The speech runtime of the desktop engine (ADR-0066): pins, install, server, engine."""

import asyncio
import hashlib
import io
import json
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest
from wasifyai_api import audio_runtime as ar
from wasifyai_api.desktop_models import load_catalogue
from wasifyai_platform_sdk import VoiceEngineError, check_music

from tests.fake_audiocpp import wav_bytes

TESTS = Path(__file__).parent
PRODUCTS = TESTS.parents[2] / "products"


def fake_server_script() -> str:
    return (
        f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(TESTS)!r})\n"
        "import fake_audiocpp\nfake_audiocpp.main()\n"
    )


def make_install(root: Path) -> ar.AudioInstall:
    server = root / "audiocpp_server"
    server.write_text(fake_server_script())
    server.chmod(server.stat().st_mode | stat.S_IXUSR)
    return ar.AudioInstall("test", "cpu", server, "env")


def tar_with_server() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        data = fake_server_script().encode()
        info = tarfile.TarInfo("audio-test/audiocpp_server")
        info.size, info.mode = len(data), 0o755
        t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def pins_for(data: bytes, kind: str = "tar.gz") -> ar.Pins:
    pin = ar.Pin(
        ar.platform_key(), "audio-test.tar.gz", "https://example.test/audio-test.tar.gz",
        len(data), hashlib.sha256(data).hexdigest(), "cpu", kind, True,
    )  # fmt: skip
    return ar.Pins("x/y", "vTEST", "audiocpp_server", {pin.platform: pin})


def client_for(data: bytes):
    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=data))
    )


async def finished(installer: ar.AudioInstaller):
    assert installer._task is not None  # noqa: SLF001
    await installer._task  # noqa: SLF001


# ---- pins ----------------------------------------------------------------------------------


def test_the_shipped_pins_are_complete_and_https():
    pins = ar.load_pins()
    assert pins.tag.startswith("v0.9.0") and "darwin-arm64" in pins.assets
    for pin in pins.assets.values():
        assert pin.url.startswith("https://github.com/unslothai/audio.cpp/releases/download/")
        assert len(pin.sha256) == 64 and pin.size > 1_000_000
    assert [p.platform for p in pins.assets.values() if p.measured] == ["darwin-arm64"]


def test_a_pin_without_a_sha_is_refused(tmp_path):
    raw = json.loads(ar.PINS_FILE.read_text())
    raw["assets"]["darwin-arm64"]["sha256"] = "abc"
    bad = tmp_path / "pins.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="SHA-256"):
        ar.load_pins(bad)


# ---- installing ----------------------------------------------------------------------------


async def test_install_shows_the_plan_then_downloads_checks_unpacks_and_records(tmp_path):
    data = tar_with_server()
    inst = ar.AudioInstaller(tmp_path, pins_for(data), client_for(data))
    plan = inst.plan()
    assert plan["supported"] and plan["bytes"] == len(data) and plan["tag"] == "vTEST"
    assert ar.find_install(tmp_path) is None
    with pytest.raises(ar.InstallError, match="changed since"):
        inst.start(len(data) + 1)
    inst.start(len(data))
    await finished(inst)
    assert inst.progress.state == "ready", inst.progress
    found = ar.find_install(tmp_path)
    assert found is not None and found.source == "managed" and found.tag == "vTEST"
    assert found.server.is_file() and str(found.server).startswith(str(tmp_path))


async def test_a_download_that_does_not_match_is_not_kept(tmp_path):
    data = tar_with_server()
    inst = ar.AudioInstaller(tmp_path, pins_for(data), client_for(data + b"x"))
    inst.start(len(data))
    await finished(inst)
    assert inst.progress.state == "failed" and "did not match" in inst.progress.message
    assert ar.find_install(tmp_path) is None
    assert not list((tmp_path / "engine" / "audiocpp").glob("v*"))


async def test_an_archive_with_no_server_or_an_unsafe_path_fails_cleanly(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo("readme.txt")
        info.size = 2
        t.addfile(info, io.BytesIO(b"hi"))
    empty = buf.getvalue()
    inst = ar.AudioInstaller(tmp_path, pins_for(empty), client_for(empty))
    inst.start(len(empty))
    await finished(inst)
    assert inst.progress.state == "failed" and "did not contain" in inst.progress.message

    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil", "x")
    evil = z.getvalue()
    inst2 = ar.AudioInstaller(tmp_path / "b", pins_for(evil, "zip"), client_for(evil))
    inst2.start(len(evil))
    await finished(inst2)
    assert inst2.progress.state == "failed" and "unsafe" in inst2.progress.message


async def test_a_runtime_that_does_not_start_is_not_recorded(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        data = b"#!/bin/sh\nexit 3\n"
        info = tarfile.TarInfo("audiocpp_server")
        info.size, info.mode = len(data), 0o755
        t.addfile(info, io.BytesIO(data))
    broken = buf.getvalue()
    inst = ar.AudioInstaller(tmp_path, pins_for(broken), client_for(broken))
    inst.start(len(broken))
    await finished(inst)
    assert inst.progress.state == "failed" and ar.find_install(tmp_path) is None


def test_an_environment_binary_is_used_when_nothing_is_installed(tmp_path, monkeypatch):
    install = make_install(tmp_path)
    monkeypatch.setenv("WASIFYAI_AUDIOCPP", str(install.server))
    found = ar.find_install(tmp_path / "empty")
    assert found is not None and found.source == "env"


# ---- the engine ----------------------------------------------------------------------------


class Models:
    """A stand-in for ModelsService: the real catalogue, files present where a test says."""

    def __init__(self, root: Path, present: set[str]):
        self.catalogue = {e.id: e for e in load_catalogue(PRODUCTS, ["wasifyai-voice"])}
        self._root, self._present = root, present

    def locate(self, f):
        if f.name not in self._present:
            return None
        p = self._root / f.name
        p.write_bytes(b"gguf")
        return p


ALL = {
    "kokoro-82m-q8_0.gguf", "parakeet-tdt-0.6b-v3-q8_0.gguf", "voxcpm2-q8_0.gguf",
    "qwen3-tts-12hz-0.6b-base-q8_0.gguf", "qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf",
    "ace-step-1.5-turbo-q8_0.gguf", "stable-audio-3-small-music-q8_0.gguf",
    "stable-audio-3-small-sfx-q8_0.gguf",
}  # fmt: skip


def make_engine(tmp_path, monkeypatch, present=ALL, install=True):
    models = Models(tmp_path, set(present))
    if install:
        monkeypatch.setenv("WASIFYAI_AUDIOCPP", str(make_install(tmp_path).server))
    else:
        monkeypatch.delenv("WASIFYAI_AUDIOCPP", raising=False)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    server = ar.AudioServer(data, startup_timeout_s=20)
    engine = ar.AudioEngine(data, models, ar.AudioInstaller(data), server)
    return engine, server


@pytest.fixture
async def engine(tmp_path, monkeypatch):
    eng, server = make_engine(tmp_path, monkeypatch)
    yield eng
    await server.close()


def test_models_by_task_with_their_state(tmp_path, monkeypatch):
    eng, _ = make_engine(tmp_path, monkeypatch, present={"kokoro-82m-q8_0.gguf"})
    speak = {m["id"]: m for m in eng.models("speak")}
    assert set(speak) == {"kokoro-82m", "voxcpm2"}
    assert {m["id"] for m in eng.models("clone")} == {"qwen3-tts-0.6b-base", "voxcpm2"}
    assert {m["id"] for m in eng.models("design")} == {"qwen3-tts-1.7b-voicedesign", "voxcpm2"}
    assert speak["kokoro-82m"]["state"] == "ready" and speak["kokoro-82m"]["bytes_missing"] == 0
    assert speak["voxcpm2"]["state"] == "can_install" and speak["voxcpm2"]["bytes_missing"] > 2e9
    assert [m["id"] for m in eng.models("transcribe")] == ["parakeet-tdt-0.6b-v3"]
    assert speak["kokoro-82m"]["commercial_use"] == "yes"
    eng2, _ = make_engine(tmp_path, monkeypatch, present={"kokoro-82m-q8_0.gguf"}, install=False)
    assert {m["state"] for m in eng2.models("speak")} == {"needs_runtime", "can_install"}


def test_resolve_names_what_to_do(tmp_path, monkeypatch):
    eng, _ = make_engine(tmp_path, monkeypatch, present={"kokoro-82m-q8_0.gguf"})
    assert eng.resolve("speak", None).id == "kokoro-82m"  # the recommended, ready one
    with pytest.raises(VoiceEngineError) as e:
        eng.resolve("speak", "voxcpm2")
    assert e.value.code == "model_missing" and "Models" in e.value.message
    with pytest.raises(VoiceEngineError) as e:
        eng.resolve("speak", "parakeet-tdt-0.6b-v3")
    assert e.value.code == "unknown_model"
    with pytest.raises(VoiceEngineError) as e:
        eng.resolve("speak", "ghost")
    assert e.value.code == "unknown_model"
    eng2, _ = make_engine(tmp_path, monkeypatch, install=False)
    with pytest.raises(VoiceEngineError) as e:
        eng2.resolve("speak", None)
    assert e.value.code == "runtime_missing"


async def test_speak_runs_the_model_and_reports_the_load(engine):
    model = engine.resolve("speak", "kokoro-82m")
    first = await engine.speak(model, "Hello there, this is a test of speech.", "af_heart", {})
    assert first.seconds > 0.5 and first.sample_rate == 24000 and first.wav[:4] == b"RIFF"
    assert first.load_s > 0  # the model was not loaded before this request
    second = await engine.speak(model, "Again.", None, {"speed": 1.2})
    assert second.load_s == 0.0
    loaded = await engine.server.loaded()
    assert loaded["kokoro-82m"] and not any(v for k, v in loaded.items() if k != "kokoro-82m")


async def test_the_server_is_restarted_when_the_set_of_models_changes(tmp_path, monkeypatch):
    eng, server = make_engine(tmp_path, monkeypatch, present={"kokoro-82m-q8_0.gguf"})
    try:
        await eng.speak(eng.resolve("speak", None), "one", None, {})
        pid = server.pid
        eng._models._present.add("voxcpm2-q8_0.gguf")  # noqa: SLF001
        await eng.speak(eng.resolve("speak", "voxcpm2"), "two", None, {})
        assert server.pid != pid and server.running
    finally:
        await server.close()


async def test_transcribe_returns_text_and_sentences_with_times(engine):
    model = engine.resolve("transcribe", None)
    result = await engine.transcribe(model, wav_bytes(2.5), {})
    assert result.text == "Hello there. Second sentence here."
    assert [(s.text, s.start, s.end) for s in result.segments] == [
        ("Hello there.", 0.0, 1.0), ("Second sentence here.", 1.25, 2.5),
    ]  # fmt: skip
    assert result.seconds == 2.5


async def test_engine_failures_are_friendly_and_do_not_leak_the_runtimes_words(engine):
    model = engine.resolve("speak", "kokoro-82m")
    with pytest.raises(VoiceEngineError) as e:
        await engine.speak(model, "BOOM now", None, {})
    assert e.value.code == "out_of_memory" and "Kokoro" not in e.value.message
    asr = engine.resolve("transcribe", None)
    with pytest.raises(VoiceEngineError) as e:
        await engine.transcribe(asr, b"not audio at all", {})
    assert e.value.code == "bad_audio"


async def test_a_cancelled_request_stops_the_server(engine):
    model = engine.resolve("speak", "kokoro-82m")
    await engine.speak(model, "warm up", None, {})
    task = asyncio.create_task(engine.speak(model, "SLOW request", None, {}))
    await asyncio.sleep(0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.1)
    assert not engine.server.running
    again = await engine.speak(model, "after the cancel", None, {})  # starts again
    assert again.seconds > 0


async def test_the_slot_is_held_while_a_request_runs(tmp_path, monkeypatch):
    eng, server = make_engine(tmp_path, monkeypatch)
    held: list[str] = []

    class Slot:
        def hold(self, owner):
            held.append(owner)
            return _Null()

    class _Null:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False

    eng.slot = Slot()
    try:
        await eng.speak(eng.resolve("speak", None), "hello", None, {})
        assert held == ["audio"]
    finally:
        await server.close()


def test_segments_split_at_sentences_and_at_twelve_seconds():
    words = [
        ("a", 0.0, 1.0),
        ("b.", 1.0, 2.0),
        ("c", 2.0, 8.0),
        ("d", 8.0, 15.0),
        ("e", 15.0, 16.0),
    ]
    got = ar._segments(words)  # noqa: SLF001
    assert [s.text for s in got] == ["a b.", "c d", "e"]


def test_segment_text_is_cut_from_the_full_text_when_the_runtime_joined_words():
    words = [
        ("The", 0.0, 0.5),
        ("budget", 0.5, 1.0),
        ("is$350,000.", 1.0, 2.5),
        ("Thanks.", 3.0, 3.5),
    ]
    got = ar._segments(words, "The budget is $350,000. Thanks.")  # noqa: SLF001
    assert [s.text for s in got] == ["The budget is $350,000.", "Thanks."]
    # words that do not add up to the text: the words are used as they are
    assert [s.text for s in ar._segments(words, "something else")][0] == "The budget is$350,000."  # noqa: SLF001


async def last_request(engine) -> dict:
    r = await engine.server._http.get(f"{engine.server._url}/_last")  # noqa: SLF001
    return r.json()


async def test_design_delivers_the_description_the_way_each_model_takes_it(engine):
    qwen = engine.resolve("design", None)
    assert qwen.id == "qwen3-tts-1.7b-voicedesign"
    out = await engine.design(qwen, "Hello there", "a deep, calm man", {})
    assert out.seconds > 0.2 and out.voice is None
    sent = await last_request(engine)
    assert sent["options"] == {"instruct": "a deep, calm man"} and sent["input"] == "Hello there"
    vox = engine.resolve("design", "voxcpm2")
    await engine.design(vox, "Hello there", "a bright young woman", {})
    sent = await last_request(engine)
    assert sent["input"] == "(a bright young woman)Hello there"
    assert "instruct" not in (sent.get("options") or {})  # VoxCPM2 would ignore it, silently
    with pytest.raises(VoiceEngineError) as e:
        await engine.design(engine.resolve("speak", "kokoro-82m"), "Hi", "a man", {})
    assert e.value.code == "wrong_task"


async def test_clone_sends_the_recording_and_the_words_it_says(engine, tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(wav_bytes(2.0))
    base = engine.resolve("clone", None)
    assert base.id == "qwen3-tts-0.6b-base"
    out = await engine.clone(base, "Say this please", ref, "the words said", {})
    assert out.seconds > 0.2
    sent = await last_request(engine)
    assert sent["voice_ref"] == str(ref) and sent["reference_text"] == "the words said"
    with pytest.raises(VoiceEngineError) as e:
        await engine.clone(base, "Say this", ref, None, {})  # the runtime refuses: no words
    assert e.value.code == "engine_failed"
    with pytest.raises(VoiceEngineError) as e:
        await engine.clone(engine.resolve("speak", "kokoro-82m"), "Hi", ref, None, {})
    assert e.value.code == "wrong_task"
    vox = engine.resolve("clone", "voxcpm2")
    await engine.clone(vox, "Optional words", ref, None, {})
    assert "reference_text" not in await last_request(engine)


async def test_music_is_asked_for_the_way_each_family_takes_it(engine):
    ace = engine.resolve("music", None)
    assert ace.id == "ace-step-1.5-turbo"
    req = check_music(ace, "song", "pop, upbeat", "la la la", False, 20, None, 5)
    out = await engine.music(ace, req)
    assert out.seconds > 0.5 and out.seed == 5 and out.sample_rate == 24000
    sent = (await last_request(engine))["request"]
    assert sent == {
        "text": "pop, upbeat",
        "duration_seconds": 20.0,
        "seed": "5",
        "options": {"lyrics": "la la la"},
    }
    instrumental = check_music(ace, "song", "calm piano", None, True, None, None, None)
    out = await engine.music(ace, instrumental)
    sent = (await last_request(engine))["request"]
    assert sent["options"] == {"lyrics": "[Instrumental]"} and sent["duration_seconds"] == 30.0
    assert out.seed is not None and sent["seed"] == str(
        out.seed
    )  # chosen, because the default is fixed
    stable = engine.resolve("music", "stable-audio-3-small-music")
    await engine.music(stable, check_music(stable, "song", "ambient pad", None, False, 12, None, 1))
    sent = (await last_request(engine))["request"]
    assert "options" not in sent and sent["duration_seconds"] == 12.0
    sfx = engine.resolve("music", "stable-audio-3-small-sfx")
    await engine.music(
        sfx, check_music(sfx, "sfx", "rain on a tin roof", None, False, None, None, 2)
    )
    assert (await last_request(engine))["request"]["duration_seconds"] == 8.0


async def test_music_can_come_back_as_raw_audio_and_failures_are_friendly(engine):
    ace = engine.resolve("music", None)
    out = await engine.music(ace, check_music(ace, "song", "RAW sound", None, False, 5, None, 1))
    assert out.wav[:4] == b"RIFF"
    with pytest.raises(VoiceEngineError) as e:
        await engine.music(ace, check_music(ace, "song", "BOOM now", None, False, 5, None, 1))
    assert e.value.code == "out_of_memory"
    with pytest.raises(VoiceEngineError) as e:
        await engine.music(
            engine.resolve("speak", "kokoro-82m"),
            check_music(ace, "song", "x y z", None, False, 5, None, 1),
        )
    assert e.value.code == "wrong_task"


def test_the_music_models_are_listed_with_their_licence(tmp_path, monkeypatch):
    eng, _ = make_engine(tmp_path, monkeypatch, present={"ace-step-1.5-turbo-q8_0.gguf"})
    got = {m["id"]: m for m in eng.models("music")}
    assert set(got) == {
        "ace-step-1.5-turbo",
        "stable-audio-3-small-music",
        "stable-audio-3-small-sfx",
    }
    assert got["ace-step-1.5-turbo"]["state"] == "ready" and got["ace-step-1.5-turbo"][
        "recommended"
    ] == ["music"]
    assert got["stable-audio-3-small-music"]["commercial_use"] == "conditional"
    assert got["stable-audio-3-small-music"]["recommended"] == []
    assert got["stable-audio-3-small-sfx"]["state"] == "can_install"
