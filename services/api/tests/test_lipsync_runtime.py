"""The lip sync engine (V5): pins, what counts as installed, the installer on stand-ins, the sidecar
process on a stand-in server, and how the engine lists and runs the model."""

import asyncio
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

import httpx
import pytest
from wasifyai_api import lipsync_runtime as lr
from wasifyai_api.audio_runtime import InstallError
from wasifyai_platform_sdk import VoiceEngineError, check_lipsync

from tests.test_audio_runtime import ALL, Models, make_engine

REPO = Path(__file__).parents[3]
LIPSYNC_FILES = {
    "musetalk-v15-unet.pth", "musetalk-v15.json", "sd-vae-ft-mse.bin", "sd-vae-ft-mse.json",
    "whisper-tiny.bin", "whisper-tiny.json", "whisper-tiny-preprocessor.json",
    "face-parsing-bisenet.pth", "resnet18-5c106cde.pth", "s3fd-619a316812.pth",
    "2DFAN4-11f355bf06.pth.tar",
}  # fmt: skip


# ---- pins and what the catalogue says ---------------------------------------------------------


def test_the_pins_are_exact_and_the_shipped_lock_is_the_one_pinned():
    pins = lr.load_pins()
    assert len(pins.commit) == 40 and pins.url.endswith(f"{pins.commit}.tar.gz")
    assert pins.url.startswith("https://github.com/TMElyralab/MuseTalk/archive/")
    assert lr._sha256_file(pins.lock) == pins.lock_sha256  # noqa: SLF001
    assert pins.platforms == ("darwin-arm64",)
    text = pins.lock.read_text()
    assert "--hash=sha256:" in text and "torch==" in text and "numpy==1." in text
    assert "gdown" not in text  # the weights come from Models, not from a download script


def test_a_pin_without_a_hash_is_refused(tmp_path):
    raw = json.loads(lr.PINS_FILE.read_text())
    raw["source"]["sha256"] = "abc"
    bad = tmp_path / "pins.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="SHA-256"):
        lr.load_pins(bad)


def test_every_weight_file_of_the_catalogue_has_a_place_to_be_laid_out():
    entry = Models(Path("/x"), set()).catalogue["musetalk-v15"]
    names = {f.name for f in entry.files}
    assert names == LIPSYNC_FILES == set(lr.WEIGHTS) | set(lr.TORCH_WEIGHTS)
    assert all(f.folder == "lipsync" and f.url.startswith("https://") for f in entry.files)
    assert sum(f.size for f in entry.files) == pytest.approx(4.2e9, rel=0.05)
    assert entry.voice and entry.voice.lipsync["mark"] == "required"
    assert entry.voice.engine == "sidecar" and entry.voice.commercial_use == "yes"


def test_the_mark_is_drawn_on_every_frame_and_cannot_be_asked_away():
    engine = (lr.SERVER_DIR / "engine.py").read_text()
    server = (lr.SERVER_DIR / "server.py").read_text()
    assert "stamp(out, mark)" in engine and "-metadata" in engine
    assert 'mark: Annotated[str, Form()] = ""' in server


# ---- what counts as installed ----------------------------------------------------------------


def managed(tmp_path, **state):
    pins = lr.load_pins()
    root = tmp_path / "engine" / "musetalk"
    (root / "src" / "musetalk").mkdir(parents=True, exist_ok=True)
    py = lr._venv_python(root / "venv")  # noqa: SLF001
    py.parent.mkdir(parents=True, exist_ok=True)
    if not py.exists():
        py.write_text("")
    rec = {"schema": 1, "commit": pins.commit, "lock_sha256": pins.lock_sha256, **state}
    (root / "state.json").write_text(json.dumps(rec))
    return root


def test_nothing_is_installed_until_the_record_matches_the_pins(tmp_path, monkeypatch):
    monkeypatch.delenv("WASIFYAI_MUSETALK_HOME", raising=False)
    assert lr.find_install(tmp_path) is None
    root = managed(tmp_path)
    found = lr.find_install(tmp_path)
    assert found is not None and found.source == "managed" and not found.in_place
    assert found.src == root / "src" and found.torch_home == root / "torch"
    managed(tmp_path, commit="old")
    assert lr.find_install(tmp_path) is None  # another version of the code
    managed(tmp_path, lock_sha256="0" * 64)
    assert lr.find_install(tmp_path) is None  # another package list
    (root / "state.json").write_text("not json")
    assert lr.find_install(tmp_path) is None


def test_a_copy_set_up_by_hand_is_used_as_it_is(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "src" / "musetalk").mkdir(parents=True)
    py = lr._venv_python(home / "venv")  # noqa: SLF001
    py.parent.mkdir(parents=True)
    py.write_text("")
    monkeypatch.setenv("WASIFYAI_MUSETALK_HOME", str(home))
    found = lr.find_install(tmp_path)
    assert found is not None and found.source == "env" and found.in_place
    assert found.torch_home is None


def test_uv_is_the_one_the_shell_gave_or_the_one_downloaded_or_on_the_path(tmp_path, monkeypatch):
    monkeypatch.delenv("WASIFYAI_UV", raising=False)
    uv = tmp_path / "engine" / "tools" / "uv-0.12.23" / "uv"
    uv.parent.mkdir(parents=True)
    uv.write_text("")
    assert lr.find_uv(tmp_path) == str(uv)
    other = tmp_path / "myuv"
    other.write_text("")
    monkeypatch.setenv("WASIFYAI_UV", str(other))
    assert lr.find_uv(tmp_path) == str(other)


# ---- laying out the weights ---------------------------------------------------------------------


def weights(tmp_path):
    files = {}
    for name in LIPSYNC_FILES:
        p = tmp_path / "models" / "lipsync" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(name.encode())
        files[name] = p
    return files


def test_weights_are_linked_to_where_musetalk_and_the_face_package_read_them(tmp_path):
    root = managed(tmp_path)
    install = lr.find_install(tmp_path)
    assert install is not None
    files = weights(tmp_path)
    lr._lay_out(install, files)  # noqa: SLF001
    assert (root / "src/models/musetalkV15/unet.pth").read_bytes() == b"musetalk-v15-unet.pth"
    assert (root / "src/models/face-parse-bisent/79999_iter.pth").is_file()
    assert (
        root / "torch/hub/checkpoints/s3fd-619a316812.pth"
    ).read_bytes() == b"s3fd-619a316812.pth"
    lr._lay_out(install, files)  # again: nothing breaks
    (root / "src/models/sd-vae/config.json").unlink()
    lr._lay_out(install, files)
    assert (root / "src/models/sd-vae/config.json").is_file()


def test_a_missing_weight_file_is_told_as_a_model_to_get(tmp_path):
    managed(tmp_path)
    install = lr.find_install(tmp_path)
    assert install is not None
    files = weights(tmp_path)
    del files["whisper-tiny.bin"]
    with pytest.raises(VoiceEngineError) as e:
        lr._lay_out(install, files)  # noqa: SLF001
    assert e.value.code == "model_missing"


# ---- the installer ---------------------------------------------------------------------------


def tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in (
            ("MuseTalk-abc/musetalk/__init__.py", b""),
            ("MuseTalk-abc/LICENSE", b"MIT"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def installer_for(tmp_path, data: bytes, monkeypatch, platforms=None):
    monkeypatch.setenv("WASIFYAI_UV", str(tmp_path / "uv"))
    (tmp_path / "uv").write_text("")
    base = lr.load_pins()
    pins = lr.Pins(
        base.commit, "https://example.test/musetalk.tar.gz", len(data),
        hashlib.sha256(data).hexdigest(), "3.12", base.lock, base.lock_sha256, 1_000_000,
        platforms or (lr.platform_key(),),
    )  # fmt: skip
    client = lambda: httpx.AsyncClient(  # noqa: E731
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=data))
    )
    data_dir = tmp_path / "data"
    (data_dir / "engine").mkdir(parents=True, exist_ok=True)
    inst = lr.MuseTalkInstaller(data_dir, pins, client)
    calls: list[list[str]] = []

    async def run(args, cwd, env, limit_s: float = 3600):
        calls.append(args)
        if args[1] == "venv":
            py = lr._venv_python(Path(args[-1]))  # noqa: SLF001
            py.parent.mkdir(parents=True)
            py.write_text("")
        if args[1] == "pip":
            assert "--require-hashes" in args and "--python" in args
        if args[1:3] == ["-c", args[2]] or args[1] == "-c":
            return True, "accelerator mps\n"
        return True, ""

    inst.run = run
    return inst, pins, calls, data_dir


async def finished(inst):
    assert inst._task is not None  # noqa: SLF001
    await inst._task  # noqa: SLF001


async def test_the_installer_shows_the_plan_then_gets_checks_builds_and_records(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("WASIFYAI_MUSETALK_HOME", raising=False)
    inst, pins, calls, data_dir = installer_for(tmp_path, tarball(), monkeypatch)
    plan = inst.plan()
    assert plan["supported"] and plan["bytes"] == pins.size + pins.packages_bytes and plan["uv"]
    with pytest.raises(InstallError, match="changed since"):
        inst.start(plan["bytes"] - 1)
    inst.start(plan["bytes"])
    with pytest.raises(InstallError, match="already being set up"):
        inst.start(plan["bytes"])
    await finished(inst)
    assert inst.progress.state == "ready", inst.progress
    found = lr.find_install(data_dir, pins)
    assert found is not None and found.source == "managed"
    assert (found.src / "musetalk" / "__init__.py").is_file() and (found.src / "LICENSE").is_file()
    kinds = [c[1] if c[1] in ("venv", "pip") else "check" for c in calls]
    assert kinds == ["venv", "pip", "check"]
    state = json.loads((data_dir / "engine/musetalk/state.json").read_text())
    assert state["accelerator"] == "mps" and state["commit"] == pins.commit
    assert not list((data_dir / "engine/musetalk").glob("stage-*"))  # the staging folder is gone


async def test_a_download_that_does_not_match_leaves_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("WASIFYAI_MUSETALK_HOME", raising=False)
    inst, pins, calls, data_dir = installer_for(tmp_path, tarball(), monkeypatch)
    inst.pins = lr.Pins(pins.commit, pins.url, pins.size, "0" * 64, *[getattr(pins, f) for f in
        ("python", "lock", "lock_sha256", "packages_bytes", "platforms")])  # fmt: skip
    inst.start(inst.total_bytes)
    await finished(inst)
    assert inst.progress.state == "failed" and "did not match" in inst.progress.message
    assert calls == [] and lr.find_install(data_dir, pins) is None


@pytest.mark.parametrize("failing, message", [("venv", "environment"), ("pip", "packages")])
async def test_a_failing_step_says_which_and_the_old_install_is_not_left_half_there(
    tmp_path, monkeypatch, failing, message
):
    monkeypatch.delenv("WASIFYAI_MUSETALK_HOME", raising=False)
    inst, pins, calls, data_dir = installer_for(tmp_path, tarball(), monkeypatch)
    ok = inst.run

    async def run(args, cwd, env, limit_s: float = 3600):
        if args[1] == failing:
            return False, "boom"
        return await ok(args, cwd, env, limit_s)

    inst.run = run
    inst.start(inst.total_bytes)
    await finished(inst)
    assert inst.progress.state == "failed" and message in inst.progress.message
    assert lr.find_install(data_dir, pins) is None  # the record is written last


async def test_the_check_that_torch_starts_decides_whether_it_is_installed(tmp_path, monkeypatch):
    monkeypatch.delenv("WASIFYAI_MUSETALK_HOME", raising=False)
    inst, pins, calls, data_dir = installer_for(tmp_path, tarball(), monkeypatch)
    ok = inst.run

    async def run(args, cwd, env, limit_s: float = 3600):
        if args[1] == "-c":
            return False, "ImportError"
        return await ok(args, cwd, env, limit_s)

    inst.run = run
    inst.start(inst.total_bytes)
    await finished(inst)
    assert inst.progress.state == "failed" and "did not start" in inst.progress.message
    assert lr.find_install(data_dir, pins) is None


async def test_a_computer_it_does_not_support_and_a_missing_uv_are_told_in_words(
    tmp_path, monkeypatch
):
    inst, _, _, _ = installer_for(tmp_path, tarball(), monkeypatch, platforms=("windows-x64",))
    assert not inst.plan()["supported"] and inst.plan()["bytes"] == 0
    with pytest.raises(InstallError, match="no lip sync engine for this kind of computer"):
        inst.start(0)
    inst, *_ = installer_for(tmp_path, tarball(), monkeypatch)
    monkeypatch.setenv("WASIFYAI_UV", str(tmp_path / "missing"))
    monkeypatch.setattr(lr.shutil, "which", lambda name: None)
    with pytest.raises(InstallError, match="installer tool"):
        inst.start(inst.total_bytes)


# ---- the process ---------------------------------------------------------------------------------

FAKE_SERVER = (Path(__file__).parent / "fake_lipsync_server.py").read_text()


def sidecar_for(tmp_path, monkeypatch, with_weights=True):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.py").write_text(FAKE_SERVER)
    monkeypatch.setattr(lr, "SERVER_DIR", server_dir)
    root = managed(tmp_path)
    py = lr._venv_python(root / "venv")  # noqa: SLF001
    py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')  # the test's own interpreter
    py.chmod(0o755)
    monkeypatch.delenv("WASIFYAI_MUSETALK_HOME", raising=False)
    side = lr.LipSyncSidecar(tmp_path)
    files = weights(tmp_path) if with_weights else {}
    model = Models(tmp_path, set()).catalogue["musetalk-v15"].voice
    assert model is not None
    return side, model, files, server_dir


def inputs(tmp_path, picture=b"\x89PNG....", voice=b"RIFF....WAVE"):
    p, v = tmp_path / "face.png", tmp_path / "voice.wav"
    p.write_bytes(picture)
    v.write_bytes(voice)
    return p, v


async def test_a_clip_is_made_with_the_mark_and_the_weights_are_laid_out(tmp_path, monkeypatch):
    side, model, files, server_dir = sidecar_for(tmp_path, monkeypatch)
    try:
        req = check_lipsync(model, 3.0, "drawn", "own")
        pic, voice = inputs(tmp_path)
        out = await side.generate(model, req, pic, voice, files)
        assert out.mp4[4:8] == b"ftyp" and (out.width, out.height) == (640, 480)
        assert out.fps == 25 and out.seconds == 3.0 and out.model_id == "musetalk-v15"
        sent = json.loads((server_dir / "last.json").read_text())
        assert sent["mark"] == "AI-generated" and sent["fps"] == 25 and sent["voice"] == 12
        assert (tmp_path / "engine/musetalk/src/models/musetalkV15/unet.pth").exists()
        again = await side.generate(model, req, pic, voice, files)  # warm: no loading to report
        assert again.load_s == 0.0 and out.load_s >= 0.0
        assert side.running
        assert await side.stop() is True and not side.running
        assert await side.stop() is False
    finally:
        await side.close()


async def test_the_server_is_told_where_musetalk_and_torch_files_are(tmp_path, monkeypatch):
    side, model, files, _ = sidecar_for(tmp_path, monkeypatch)
    try:
        url = await side.ensure_running(files)
        async with httpx.AsyncClient() as http:
            health = (await http.get(f"{url}/health")).json()
        assert health["dir"] == str(tmp_path / "engine/musetalk/src")
        assert health["torch_home"] == str(tmp_path / "engine/musetalk/torch")
        assert await side.ensure_running(files) == url  # still the same process
    finally:
        await side.close()


async def test_no_face_a_failure_and_a_stopped_server_are_told_apart(tmp_path, monkeypatch):
    side, model, files, _ = sidecar_for(tmp_path, monkeypatch)
    try:
        req = check_lipsync(model, 3.0, "drawn", "own")
        for picture, code in ((b"noface", "no_face"), (b"boom", "engine_failed")):
            pic, voice = inputs(tmp_path, picture)
            with pytest.raises(VoiceEngineError) as e:
                await side.generate(model, req, pic, voice, files)
            assert e.value.code == code
        assert "front-facing" in (await _msg(side, model, req, files, tmp_path))
    finally:
        await side.close()


async def _msg(side, model, req, files, tmp_path):
    pic, voice = inputs(tmp_path, b"noface")
    with pytest.raises(VoiceEngineError) as e:
        await side.generate(model, req, pic, voice, files)
    return e.value.message


async def test_cancelling_stops_the_server_so_the_memory_goes_back(tmp_path, monkeypatch):
    side, model, files, _ = sidecar_for(tmp_path, monkeypatch)
    try:
        req = check_lipsync(model, 3.0, "drawn", "own")
        pic, voice = inputs(tmp_path, b"slow")
        task = asyncio.create_task(side.generate(model, req, pic, voice, files))
        await asyncio.sleep(2.5)
        assert side.running
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not side.running
    finally:
        await side.close()


async def test_a_server_that_never_answers_is_reported_and_not_left_running(tmp_path, monkeypatch):
    side, model, files, server_dir = sidecar_for(tmp_path, monkeypatch)
    (server_dir / "server.py").write_text("raise SystemExit(3)\n")
    monkeypatch.setattr(lr, "START_TIMEOUT_S", 5.0)
    try:
        with pytest.raises(VoiceEngineError) as e:
            await side.ensure_running(files)
        assert e.value.code == "engine_stopped" and not side.running
    finally:
        await side.close()


def test_the_size_of_a_video_is_read_from_its_header():
    tkhd = bytes([0]) + b"\0" * 3 + b"\0" * 20 + b"\0" * 52 + (640 << 16).to_bytes(4, "big")
    tkhd += (480 << 16).to_bytes(4, "big")
    audio = b"tkhd" + bytes([0]) + b"\0" * 3 + b"\0" * 20 + b"\0" * 52 + b"\0" * 8
    video = b"tkhd" + tkhd
    assert lr._video_size(b"xxxx" + audio + b"yyyy" + video) == (640, 480)  # noqa: SLF001
    assert lr._video_size(b"nothing here") == (0, 0)  # noqa: SLF001


# ---- how the engine lists and runs the model ------------------------------------------


def lipsync_engine(tmp_path, monkeypatch, installed: bool):
    eng, server = make_engine(tmp_path, monkeypatch, present=ALL | LIPSYNC_FILES)
    side = lr.LipSyncSidecar(tmp_path / "data")
    monkeypatch.delenv("WASIFYAI_MUSETALK_HOME", raising=False)
    if installed:
        managed(tmp_path / "data")
    eng.lipsync_sidecar = side
    return eng, server, side


def test_the_model_is_listed_with_what_it_needs_and_never_default_without_the_engine(
    tmp_path, monkeypatch
):
    eng, _, _ = lipsync_engine(tmp_path, monkeypatch, installed=False)
    got = {m["id"]: m for m in eng.models("lipsync")}
    assert set(got) == {"musetalk-v15"}
    assert (
        got["musetalk-v15"]["state"] == "needs_runtime"
        and got["musetalk-v15"]["engine"] == "sidecar"
    )
    assert got["musetalk-v15"]["lipsync"]["mark"] == "required"
    with pytest.raises(VoiceEngineError) as e:
        eng.resolve("lipsync", "musetalk-v15")
    assert e.value.code == "runtime_missing" and "lip sync engine" in e.value.message
    eng, _, _ = lipsync_engine(tmp_path, monkeypatch, installed=True)
    assert {m["state"] for m in eng.models("lipsync")} == {"ready"}
    assert eng.resolve("lipsync", None).id == "musetalk-v15"


async def test_the_engine_holds_the_lip_sync_slot_and_passes_the_located_files(
    tmp_path, monkeypatch
):
    eng, server, side = lipsync_engine(tmp_path, monkeypatch, installed=True)
    held, got = [], {}

    class Slot:
        def hold(self, owner):
            held.append(owner)

            class Ctx:
                async def __aenter__(_self):  # noqa: N805
                    return None

                async def __aexit__(_self, *a):  # noqa: N805
                    return None

            return Ctx()

    async def generate(model, req, picture, voice, files):
        got.update(files)
        return "made"

    monkeypatch.setattr(side, "generate", generate)
    eng.slot = Slot()
    try:
        model = eng.resolve("lipsync", None)
        req = check_lipsync(model, 3.0, "drawn", "own")
        assert await eng.lipsync(model, req, tmp_path / "p.png", tmp_path / "v.wav") == "made"
        assert held == ["lipsync"] and set(got) == LIPSYNC_FILES
        other = eng.resolve("speak", "kokoro-82m")
        with pytest.raises(VoiceEngineError) as e:
            await eng.lipsync(other, req, tmp_path / "p.png", tmp_path / "v.wav")
        assert e.value.code == "wrong_task"
    finally:
        await server.close()
