"""The Indian-language speech engine (voice languages plan, L5 and L6): its pins, what counts as
installed, the installer on stand-ins, the sidecar on a stand-in server, and how the speech engine
lists, refuses and runs Indic Parler-TTS and IndicConformer."""

import json
import sys
from pathlib import Path

import pytest
from wasifyai_api import audio_runtime as ar
from wasifyai_api import indic_runtime as ir
from wasifyai_api.audio_runtime import InstallError
from wasifyai_api.components.manifest import part_pins
from wasifyai_platform_sdk import VoiceEngineError

from tests.test_audio_runtime import ALL, Models

FAKE_SERVER = (Path(__file__).parent / "fake_indic_server.py").read_text()
SPEAK = "indic-parler-tts"
WRITE = "indic-conformer-600m"


def entry_names(model_id: str) -> set[str]:
    return {f.name for f in Models(Path("/x"), set()).catalogue[model_id].files}


# ---- pins and the catalogue ----------------------------------------------------------------------


def test_the_shipped_lock_is_the_one_pinned_and_has_every_hash():
    pins = ir.load_pins()
    assert ir._sha256_file(pins.lock) == pins.lock_sha256  # noqa: SLF001
    assert set(pins.platforms) == {"darwin-arm64", "linux-x64", "linux-arm64", "windows-x64"}
    text = pins.lock.read_text()
    assert "git+" not in text  # a git requirement cannot carry a hash
    assert "parler-tts @ https://github.com/huggingface/parler-tts/archive/" in text
    assert "protobuf==" in text and "transformers==4.46.1" in text
    for block in text.split("\n\n"):  # every requirement has its hashes
        for line in block.splitlines():
            if line and not line.startswith((" ", "#")):
                assert line.endswith("\\"), line


@pytest.mark.parametrize("platform", ["darwin-arm64", "darwin-x64", "linux-x64", "windows-x64"])
def test_every_platform_names_the_same_lock(platform):
    raw = part_pins("indic", platform=platform)
    assert raw["lock"] == "indic_server/indic.lock.txt"
    assert raw["lock_sha256"] == ir.load_pins().lock_sha256


def test_a_pin_without_a_hash_is_refused(tmp_path):
    raw = part_pins("indic")
    raw["lock_sha256"] = "abc"
    bad = tmp_path / "pins.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="SHA-256"):
        ir.load_pins(bad)


def test_the_catalogue_pins_every_file_and_lays_each_out_by_its_name():
    cat = Models(Path("/x"), set()).catalogue
    speak, write = cat[SPEAK], cat[WRITE]
    for e in (speak, write):
        assert e.voice is not None and e.voice.engine == "indic"
        assert set(e.voice.languages) == {"bn", "hi", "mr", "te", "ta", "gu"}
        assert all(f.folder == "indic" and "/resolve/" in f.url for f in e.files)
        assert all(len(f.url.split("/resolve/")[1].split("/")[0]) == 40 for f in e.files)
    names = entry_names(SPEAK)
    assert "indic-parler-tts--model.safetensors" in names
    assert "flan-t5-large--spiece.model" in names
    assert sum(f.size for f in speak.files) == pytest.approx(3.77e9, rel=0.02)
    assert "indic-conformer-600m--assets--encoder.onnx" in entry_names(WRITE)
    assert "indic-conformer-600m--model_onnx.py" in entry_names(WRITE)
    assert speak.voice.tasks == ("speak",) and write.voice.tasks == ("transcribe",)
    by_language = {v.language for v in speak.voice.voices}
    assert by_language == {"bn", "hi", "mr", "te", "ta", "gu"}
    assert speak.voice.default_voice == "Aditi"


def test_files_are_linked_where_each_model_reads_them(tmp_path):
    a, b = tmp_path / "dl" / "x", tmp_path / "dl" / "y"
    a.parent.mkdir()
    a.write_text("a")
    b.write_text("b")
    root = tmp_path / "models"
    ir.lay_out(root, {"indic-conformer-600m--assets--encoder.onnx": a, "flan-t5-large--x.json": b})
    assert (root / "indic-conformer-600m/assets/encoder.onnx").read_text() == "a"
    assert (root / "flan-t5-large/x.json").is_symlink()
    ir.lay_out(root, {"flan-t5-large--x.json": a})  # a changed file replaces the old link
    assert (root / "flan-t5-large/x.json").read_text() == "a"
    with pytest.raises(VoiceEngineError):
        ir.lay_out(root, {"a--..--b": a})


# ---- installed or not, and the installer --------------------------------------------------------


def managed(data: Path, **state) -> Path:
    pins = ir.load_pins()
    root = data / "engine" / "indic"
    py = ir._venv_python(root / "venv")  # noqa: SLF001
    py.parent.mkdir(parents=True, exist_ok=True)
    if not py.exists():
        py.write_text("")
    (root / "state.json").write_text(
        json.dumps({"schema": 1, "lock_sha256": pins.lock_sha256, **state})
    )
    return root


def test_nothing_is_installed_until_the_record_matches_the_lock(tmp_path, monkeypatch):
    monkeypatch.delenv("WASIFYAI_INDIC_VENV", raising=False)
    pins = ir.load_pins()
    assert ir.find_install(tmp_path, pins) is None
    managed(tmp_path, lock_sha256="0" * 64)
    assert ir.find_install(tmp_path, pins) is None  # made from another lock
    managed(tmp_path)
    found = ir.find_install(tmp_path, pins)
    assert found is not None and found.source == "managed"


def installer_for(tmp_path, monkeypatch, platforms=None):
    monkeypatch.setenv("WASIFYAI_UV", str(tmp_path / "uv"))
    (tmp_path / "uv").write_text("")
    base = ir.load_pins()
    pins = ir.Pins("3.12", base.lock, base.lock_sha256, 1_000_000,
                   platforms or (ir.platform_key(),))  # fmt: skip
    data = tmp_path / "data"
    (data / "engine").mkdir(parents=True, exist_ok=True)
    inst = ir.IndicInstaller(data, pins)
    calls: list[list[str]] = []

    async def run(args, cwd, env, limit_s=3600):
        calls.append([str(a) for a in args])
        if args[1:3] == ["venv", "--python"]:
            py = ir._venv_python(Path(args[-1]))  # noqa: SLF001
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("")
        if "-c" in args:
            return True, "accelerator mps\n"
        return True, ""

    inst.run = run
    return inst, data, calls


async def test_the_installer_makes_the_environment_from_the_lock_without_resolving(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("WASIFYAI_INDIC_VENV", raising=False)
    inst, data, calls = installer_for(tmp_path, monkeypatch)
    with pytest.raises(InstallError, match="changed"):
        inst.start(1)
    inst.start(inst.total_bytes)
    await inst.wait()
    assert inst.progress.state == "ready", inst.progress
    pip = next(c for c in calls if "pip" in c)
    assert "--require-hashes" in pip and "--no-deps" in pip  # the override lives in the lock
    assert str(ir.load_pins().lock) in pip
    state = json.loads((data / "engine/indic/state.json").read_text())
    assert state["accelerator"] == "mps"
    assert ir.find_install(data, inst.pins) is not None


def test_a_computer_without_a_build_is_told_so(tmp_path, monkeypatch):
    inst, *_ = installer_for(tmp_path, monkeypatch, platforms=("windows-arm64",))
    assert not inst.plan()["supported"] and inst.plan()["bytes"] == 0
    with pytest.raises(InstallError, match="no Indian-language speech engine"):
        inst.start(0)


# ---- the process, through the speech engine ------------------------------------------------------


def engine_for(tmp_path, monkeypatch, present=frozenset(), installed=True):
    server_dir = tmp_path / "server"
    server_dir.mkdir(exist_ok=True)
    (server_dir / "server.py").write_text(FAKE_SERVER)
    monkeypatch.setattr(ir, "SERVER_DIR", server_dir)
    monkeypatch.delenv("WASIFYAI_INDIC_VENV", raising=False)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    if installed:
        py = ir._venv_python(managed(data) / "venv")  # noqa: SLF001
        py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')  # the test's own interpreter
        py.chmod(0o755)
    models = Models(tmp_path, set(present))
    side = ir.IndicSidecar(data)
    engine = ar.AudioEngine(data, models, ar.AudioInstaller(data), ar.AudioServer(data),
                            indic=side)  # fmt: skip
    return engine, side, server_dir


async def test_bengali_is_spoken_by_the_named_speaker(tmp_path, monkeypatch):
    engine, side, server_dir = engine_for(tmp_path, monkeypatch, ALL | entry_names(SPEAK))
    try:
        rows = {m["id"]: m for m in engine.models("speak")}
        assert rows[SPEAK]["state"] == "ready"
        model = engine.resolve("speak", SPEAK)
        out = await engine.speak(model, "আজ আবহাওয়া খুব সুন্দর।", "Arjun", {})
        assert out.seconds == pytest.approx(1.0) and out.voice == "Arjun"
        assert out.sample_rate == 44100
        sent = json.loads((server_dir / "last.json").read_text())
        assert sent["speaker"] == "Arjun" and sent["text"].startswith("আজ")
        assert sent["folder"] == str(tmp_path / "data/engine/indic/models")
        assert (tmp_path / "data/engine/indic/models/indic-parler-tts/model.safetensors").exists()
        again = await engine.speak(model, "আবার।", None, {})  # the default speaker, warm
        assert again.voice == "Aditi" and again.load_s == 0.0
        with pytest.raises(VoiceEngineError) as e:
            await engine.speak(model, "x", "Nobody", {})
        assert e.value.code == "unknown_voice"
    finally:
        await side.close()


async def test_a_recording_is_written_down_only_once_its_language_is_known(tmp_path, monkeypatch):
    engine, side, server_dir = engine_for(tmp_path, monkeypatch, ALL | entry_names(WRITE))
    try:
        model = engine.resolve("transcribe", WRITE)
        with pytest.raises(VoiceEngineError) as e:
            await engine.transcribe(model, b"RIFF....WAVE hello there", {})
        assert e.value.code == "language_needed"
        out = await engine.transcribe(model, b"RIFF....WAVE hello there", {"language": "bn"})
        assert out.text == "hello there" and out.segments[0].end == 1.5
        assert json.loads((server_dir / "last.json").read_text())["language"] == "bn"
        with pytest.raises(VoiceEngineError) as e:
            await engine.transcribe(model, b"RIFF", {"language": "xx"})
        assert e.value.code == "wrong_language"
    finally:
        await side.close()


async def test_the_models_say_what_is_missing(tmp_path, monkeypatch):
    engine, side, _ = engine_for(tmp_path, monkeypatch, ALL, installed=False)
    try:
        rows = {m["id"]: m for m in engine.models(None)}
        assert rows[SPEAK]["state"] == "can_install" and not rows[SPEAK]["runtime_ready"]
        engine2, side2, _ = engine_for(tmp_path, monkeypatch, ALL | entry_names(SPEAK), False)
        assert {m["id"]: m for m in engine2.models(None)}[SPEAK]["state"] == "needs_runtime"
        with pytest.raises(VoiceEngineError, match="Indian-language speech engine"):
            engine2.resolve("speak", SPEAK)
        await side2.close()
        side.installer.pins = ir.Pins("3.12", side.pins.lock, side.pins.lock_sha256, 1, ())
        assert {m["id"]: m for m in engine.models(None)}[SPEAK]["state"] == "not_available"
    finally:
        await side.close()


# ---- every language the two models claim (voice languages plan, L8) ------------------------------


@pytest.mark.parametrize("language", ["bn", "hi", "mr", "te", "ta", "gu"])
def test_every_claimed_language_has_a_voice_a_writer_and_a_speaking_rate(language):
    """What the catalogue claims is what the server and the dubbing accept: each language has a
    speaker of its own, IndicConformer writes it (the server's list), and dubbing knows how fast it
    is spoken. The sound itself is checked by hand with `scripts/indic-round-trip.py`."""
    from wasifyai_platform_sdk import languages
    from wasifyai_voice import dubbing

    server = (ir.SERVER_DIR / "server.py").read_text()
    cat = Models(Path("/x"), set()).catalogue
    speak, write = cat[SPEAK].voice, cat[WRITE].voice
    assert speak is not None and write is not None
    assert languages.voices_for(speak, language)
    assert languages.supports(write.languages, language)
    assert f'"{language}"' in server.split("CONFORMER_LANGUAGES")[1].split("}")[0]
    assert language in dubbing.CHARS_PER_SECOND
