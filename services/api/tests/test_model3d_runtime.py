"""The 3D component and engine (ADR-0080, TD1) with stand-ins: the pins, what counts as installed,
the installer (nothing fetched before the person confirms the size shown, every file checked), the
progress read from the engine's output, and the two runs with a fake `trellis-cli`."""

import asyncio
import hashlib
import io
import json
import os
import stat
import tarfile
import textwrap
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from wasifyai_api import desktop_model3d as dm
from wasifyai_api import model3d_runtime as m3
from wasifyai_api.audio_runtime import InstallError, platform_key
from wasifyai_api.components.manifest import part_pins
from wasifyai_api.desktop_models import DownloadManager

FIXTURE = Path(__file__).parent / "fixtures" / "trellis-sv-run.txt"


# ---- the pins ----------------------------------------------------------------------------------


def test_every_pinned_file_has_an_https_url_a_size_and_a_sha256_and_the_total_is_their_sum():
    pins = m3.load_pins()
    files = [*pins.sv_files, *pins.matte_files]
    assert len(files) == 14 and all(f.url.startswith("https://") for f in files)
    assert all(len(f.sha256) == 64 and f.size > 0 for f in files)
    assert pins.total_bytes == pins.binary_size + sum(f.size for f in files) == 8_977_179_071
    assert pins.binary_url.startswith("https://github.com/") and len(pins.binary_sha256) == 64
    assert pins.platforms == ("darwin-arm64",) and 18 <= pins.need_gb <= 24
    # the encoder under Meta's licence and the licence texts that go with it are in the set
    names = {f.name for f in pins.sv_files}
    assert {"dinov3.gguf", "DINOV3_LICENSE.md", "MIT_LICENSE.md", "pixal3d-models.json"} <= names
    assert [f.name for f in pins.matte_files] == ["birefnet.gguf"]
    assert all("46d399ac986f45a0d7f5b1ca5058614d8729a131" in f.url for f in pins.sv_files)


def test_a_pin_without_a_checksum_or_with_a_path_in_a_name_is_refused(tmp_path):
    raw = part_pins("model3d")
    raw["weights"]["files"][0]["sha256"] = "abc"
    bad = tmp_path / "pins.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="SHA-256"):
        m3.load_pins(bad)
    raw = part_pins("model3d")
    raw["weights"]["files"][0]["name"] = "../evil"
    bad.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="plain name"):
        m3.load_pins(bad)


def test_the_licence_texts_the_component_carries_are_shipped_and_written_with_it(tmp_path):
    names = {p.name for p in m3.NOTICES_DIR.iterdir()}
    assert {"DINOV3_LICENSE.md", "LICENSE-pixal3d.cpp.txt", "NOTICE-pixal3d.cpp.txt"} <= names
    m3.write_notices(tmp_path)
    assert "DINOv3" in (tmp_path / "notices" / "DINOV3_LICENSE.md").read_text()
    # byte-identical to the agreement the weights bundle ships (SHA-256 recorded in the TD0 report)
    digest = hashlib.sha256((tmp_path / "notices" / "DINOV3_LICENSE.md").read_bytes()).hexdigest()
    pinned = next(f for f in m3.load_pins().sv_files if f.name == "DINOV3_LICENSE.md")
    assert digest == pinned.sha256


# ---- what counts as installed ----------------------------------------------------------------


def lay_out(root: Path, pins: m3.Pins, *, skip: str | None = None) -> None:
    (root / "bin").mkdir(parents=True, exist_ok=True)
    (root / "bin" / pins.cli).write_text("")
    for folder, files in ((pins.sv_folder, pins.sv_files), (pins.matte_folder, pins.matte_files)):
        d = root / "models" / folder
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            if f.name != skip:
                with (d / f.name).open("wb") as fh:  # a sparse file of the pinned size
                    fh.truncate(f.size)


def test_a_copy_named_by_the_environment_counts_only_when_every_file_is_there(
    tmp_path, monkeypatch
):
    pins = m3.load_pins()
    monkeypatch.setenv("WASIFYAI_MODEL3D_HOME", str(tmp_path / "home"))
    assert m3.find_install(tmp_path / "data", pins) is None
    lay_out(tmp_path / "home", pins, skip="dinov3.gguf")
    assert m3.find_install(tmp_path / "data", pins) is None  # the encoder is missing
    lay_out(tmp_path / "home", pins)
    found = m3.find_install(tmp_path / "data", pins)
    assert found is not None and found.source == "env" and found.cli.name == "trellis-cli"
    (tmp_path / "home" / "models" / pins.matte_folder / "birefnet.gguf").write_text("short")
    assert m3.find_install(tmp_path / "data", pins) is None  # a file of the wrong size


def test_an_install_of_this_app_counts_only_while_it_matches_the_pins(tmp_path, monkeypatch):
    monkeypatch.delenv("WASIFYAI_MODEL3D_HOME", raising=False)
    pins = m3.load_pins()
    root = m3.component_root(tmp_path)
    lay_out(root, pins)
    assert m3.find_install(tmp_path, pins) is None  # no state record: not finished
    (root / m3.STATE_FILE).write_text(json.dumps({"schema": 1, "pins": pins.digest}))
    found = m3.find_install(tmp_path, pins)
    assert found is not None and found.source == "managed"
    (root / m3.STATE_FILE).write_text(json.dumps({"schema": 1, "pins": "an older pin"}))
    assert m3.find_install(tmp_path, pins) is None  # the pins changed: set up again


def test_the_engine_runs_with_an_environment_of_its_own(tmp_path):
    pins = m3.load_pins()
    install = m3._layout(tmp_path / "c", pins, "managed")  # noqa: SLF001
    env = m3.run_env(install)
    assert env["HOME"].startswith(str(tmp_path)) and env["PATH"] == "/usr/bin:/bin"
    assert set(env) == {"HOME", "TMPDIR", "PATH", "LANG"}


def test_uninstall_reports_what_came_back(tmp_path):
    root = m3.component_root(tmp_path)
    root.mkdir(parents=True)
    (root / "a").write_bytes(b"x" * 1234)
    assert m3.uninstall(tmp_path) == 1234 and not root.exists()


# ---- the installer ------------------------------------------------------------------------------


def tiny_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in (
            ("trellis-cli", b"#!/bin/sh\necho trellis-cli usage\n"),
            ("lib.dylib", b"x"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def stand_ins(tmp_path, monkeypatch, *, wrong: str | None = None, cli_ok: bool = True):
    monkeypatch.delenv("WASIFYAI_MODEL3D_HOME", raising=False)
    served: dict[str, bytes] = {"https://example.test/engine.tar.gz": tiny_tar()}
    sv, matte = [], []
    for kind, files, out in (
        ("sv", m3.load_pins().sv_files, sv),
        ("matte", m3.load_pins().matte_files, matte),
    ):
        for f in files:
            data = (f"{kind}:{f.name}" * 3).encode()
            url = f"https://example.test/{kind}/{f.name}"
            served[url] = b"corrupted" if f.name == wrong else data
            out.append(m3.WeightFile(f.name, url, len(data), hashlib.sha256(data).hexdigest()))
    pins = replace(
        m3.load_pins(),
        binary_url="https://example.test/engine.tar.gz", binary_size=len(served["https://example.test/engine.tar.gz"]),
        binary_sha256=hashlib.sha256(served["https://example.test/engine.tar.gz"]).hexdigest(),
        sv_files=tuple(sv), matte_files=tuple(matte), platforms=(platform_key(),),
    )  # fmt: skip
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=served[str(request.url)])

    def factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    inst = m3.Model3dInstaller(tmp_path, pins, factory, DownloadManager(factory, chunk=64))
    commands: list[list[str]] = []

    async def run(args, cwd, env, limit_s=600):
        commands.append(args)
        if args[0].endswith("trellis-cli"):
            return cli_ok, "usage: trellis-cli <image.png> <out.glb>" if cli_ok else "boom"
        return True, ""

    inst.run = run
    return inst, asked, commands


async def finish(inst: m3.Model3dInstaller) -> None:
    assert inst._task is not None  # noqa: SLF001
    await inst._task  # noqa: SLF001


def test_the_plan_names_every_download_with_its_size_licence_and_source(tmp_path):
    plan = m3.Model3dInstaller(tmp_path).plan()
    assert (
        plan["bytes"] == sum(p["bytes"] for p in plan["parts"]) == 8_977_179_071
        or not plan["supported"]
    )
    names = {p["name"] for p in plan["parts"]}
    assert names == {"3D engine (pixal3d.cpp)", "Pixal3D models", "Cut-out model (BiRefNet)"}
    assert any("Built with DINOv3" in p["licence"] for p in plan["parts"])
    assert all(p["licence"] and p["source"] for p in plan["parts"])


async def test_it_installs_after_the_size_was_confirmed_and_only_then_is_installed(
    tmp_path, monkeypatch
):
    inst, asked, commands = stand_ins(tmp_path, monkeypatch)
    inst.start(inst.total_bytes)
    await finish(inst)
    assert inst.progress.state == "ready", inst.progress
    found = m3.find_install(tmp_path, inst.pins)
    assert found is not None and found.source == "managed"
    assert stat.S_IMODE(found.cli.stat().st_mode) & 0o111  # the engine can be run
    assert (m3.component_root(tmp_path) / "bin" / "lib.dylib").is_file()
    assert (m3.component_root(tmp_path) / "notices" / "DINOV3_LICENSE.md").is_file()
    assert all((found.sv_dir / f.name).is_file() for f in inst.pins.sv_files)
    assert (found.matte_dir / "birefnet.gguf").is_file()
    assert asked[0] == "https://example.test/engine.tar.gz" and len(asked) == 1 + 14
    assert any("xattr" in c[0] for c in commands) and any(
        c[0].endswith("trellis-cli") for c in commands
    )
    assert not list(m3.component_root(tmp_path).glob("stage-*"))  # nothing is left half-way


async def test_nothing_is_fetched_without_the_size_the_person_saw(tmp_path, monkeypatch):
    inst, asked, _ = stand_ins(tmp_path, monkeypatch)
    with pytest.raises(InstallError, match="changed since it was shown"):
        inst.start(inst.total_bytes + 1)
    assert asked == [] and not inst.running


async def test_a_computer_that_is_not_an_apple_silicon_mac_is_told_so_and_fetches_nothing(
    tmp_path, monkeypatch
):
    inst, asked, _ = stand_ins(tmp_path, monkeypatch)
    inst.pins = replace(inst.pins, platforms=("linux-x86_64",))
    with pytest.raises(InstallError, match="not available on this kind of computer"):
        inst.start(inst.total_bytes)
    assert asked == [] and inst.plan()["bytes"] == 0


async def test_a_weight_that_is_not_what_was_pinned_keeps_nothing_and_says_so(
    tmp_path, monkeypatch
):
    inst, _, _ = stand_ins(tmp_path, monkeypatch, wrong="dinov3.gguf")
    inst.start(inst.total_bytes)
    await finish(inst)
    assert inst.progress.state == "failed" and "checksum" in inst.progress.message
    assert m3.find_install(tmp_path, inst.pins) is None
    assert not (m3.component_root(tmp_path) / m3.STATE_FILE).exists()


async def test_an_engine_that_does_not_start_fails_the_setup_in_words(tmp_path, monkeypatch):
    inst, _, _ = stand_ins(tmp_path, monkeypatch, cli_ok=False)
    inst.start(inst.total_bytes)
    await finish(inst)
    assert inst.progress.state == "failed" and "did not start" in inst.progress.message
    assert m3.find_install(tmp_path, inst.pins) is None


async def test_a_tarball_whose_engine_is_missing_is_refused(tmp_path, monkeypatch):
    inst, _, _ = stand_ins(tmp_path, monkeypatch)
    inst.pins = replace(inst.pins, cli="not-the-engine")
    inst.start(inst.total_bytes)
    await finish(inst)
    assert inst.progress.state == "failed" and "did not contain the engine" in inst.progress.message


async def test_too_little_disk_is_said_before_anything_is_downloaded(tmp_path, monkeypatch):
    inst, asked, _ = stand_ins(tmp_path, monkeypatch)
    monkeypatch.setattr(m3, "free_disk_bytes", lambda p: 1000)
    inst.start(inst.total_bytes)
    await finish(inst)
    assert inst.progress.state == "failed" and "not enough free disk space" in inst.progress.message
    assert asked == []


async def test_a_second_start_while_one_runs_is_refused(tmp_path, monkeypatch):
    inst, _, _ = stand_ins(tmp_path, monkeypatch)
    inst.start(inst.total_bytes)
    with pytest.raises(InstallError, match="already being set up"):
        inst.start(inst.total_bytes)
    await finish(inst)


# ---- progress ------------------------------------------------------------------------------------


def test_progress_follows_a_real_run_forward_to_done_with_plain_stage_names():
    reader = dm.ProgressReader()
    seen, words = [], []
    for line in FIXTURE.read_text().splitlines():
        fraction, say = reader.feed(line)
        seen.append(fraction)
        words.append(say)
    assert seen == sorted(seen) and seen[-1] == 1.0 and 0 < seen[len(seen) // 2] < 1
    assert words[0] == "Looking at the picture" and words[-1] == "Done"
    assert {"Placing the object in space", "Building the shape", "Painting the surface"} <= set(
        words
    )
    assert all(w for w in words)


def test_progress_inside_the_shape_stage_counts_the_small_flow_first_then_the_big_one():
    r = dm.ProgressReader()
    r.feed("[3/6] shape SLAT flow (LR 512 -> upsample -> HR 1024 cascade, max_tok=49152)")
    r.feed("      [flow] [....................]  0/12    0.0s  starting    ")
    r.feed("      [flow] [####################] 12/12   46.6s  ~0s left   ")
    low_done, _ = r.feed("      [flow] [####################] 12/12   46.6s  ~0s left   ")
    r.feed("      [flow] [....................]  0/12    0.0s  starting    ")
    half, _ = r.feed("      [flow] [##########..........]  6/12   130.0s  ~130s left   ")
    assert 0.13 < low_done < half < 0.58


def test_progress_never_goes_back_and_never_says_done_before_the_engine_does():
    r = dm.ProgressReader()
    r.feed("[5/6] texture SLAT flow")
    high, _ = r.feed("      [flow] [####################] 12/12   1.0s  ~0s left   ")
    low, _ = r.feed("[2/6] SS proj conditioning + flow")
    assert low >= high and high < 1.0
    assert r.feed("done in 741.5s -> out/x.glb")[0] == 1.0


# ---- the two runs, with a fake engine ----------------------------------------------------------


FAKE_CLI = textwrap.dedent(
    """\
    #!/bin/bash
    # a stand-in for trellis-cli: prints what it prints, and writes what it writes. The engine runs
    # with an environment of its own, so a test sets the mode and the wait in files beside it.
    here=$(dirname "$0")
    FAKE_MODE=$(cat "$here/mode" 2>/dev/null); FAKE_SLEEP=$(cat "$here/sleep" 2>/dev/null)
    case "$*" in
      *--bg-only*)
        out="$2"; echo "[1/6] preprocess $1 (BiRefNet bg removal)"
        sleep ${FAKE_SLEEP:-0}
        [ "$FAKE_MODE" = "nocutout" ] || printf 'PNG' > "${out%.glb}_cutout.png"
        echo "[bg-only] done (0.1s)"; exit 0 ;;
    esac
    for last; do :; done
    echo "[0/6] Pixal3D single view"; echo "[2/6] SS proj conditioning + flow"
    echo "      [flow] [##########..........]  6/12  4.0s  ~4s left"
    sleep ${FAKE_SLEEP:-0}
    echo "ARGS: $*" >&2
    [ "$FAKE_MODE" = "fail" ] && { echo "boom" >&2; exit 3; }
    dir=$(dirname "$last")
    [ "$FAKE_MODE" = "nofile" ] || printf 'glTF' > "$last"
    printf 'ply' > "$dir/model.ply"; printf 'png' > "$dir/model_base.png"
    mkdir -p "$dir/model.svviews"
    echo "done in 1.0s -> $last"
    """
)


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.delenv("WASIFYAI_MODEL3D_HOME", raising=False)
    svc = dm.Model3dService(tmp_path / "data")
    pins = svc.installer.pins
    root = tmp_path / "home"
    lay_out(root, pins)
    cli = root / "bin" / pins.cli
    cli.write_text(FAKE_CLI)
    cli.chmod(0o755)
    monkeypatch.setattr(svc, "install", lambda: m3._layout(root, pins, "env"))  # noqa: SLF001
    svc.fake = root / "bin"  # type: ignore[attr-defined]
    return svc


def behave(service, mode: str = "", sleep: float = 0) -> None:
    (service.fake / "mode").write_text(mode)
    (service.fake / "sleep").write_text(str(sleep))


async def test_the_cutout_run_makes_a_picture_and_reports_the_lines_it_printed(service, tmp_path):
    pic = tmp_path / "in.png"
    pic.write_bytes(b"x")
    heard: list[str] = []
    res = await service.matte(pic, tmp_path / "out", heard.append)
    assert res.ok and res.output is not None and res.output.name == "unused_cutout.png"
    assert res.output.read_bytes() == b"PNG" and any("[bg-only] done" in line for line in heard)
    assert res.seconds >= 0 and not service.busy


async def test_a_cutout_run_that_made_no_picture_says_so(service, tmp_path, monkeypatch):
    behave(service, "nocutout")
    res = await service.matte(tmp_path / "in.png", tmp_path / "out")
    assert not res.ok and "did not make a picture" in res.message


async def test_the_3d_run_leaves_only_the_model_and_chooses_the_texture_size(service, tmp_path):
    cut = tmp_path / "cut.png"
    cut.write_bytes(b"x")
    out = tmp_path / "files" / "m.glb"
    out.parent.mkdir()
    heard: list[str] = []
    res = await service.generate(cut, out, seed=7, detail="detailed", on_line=heard.append)
    assert res.ok and res.output == out and out.read_bytes() == b"glTF"
    assert [p.name for p in out.parent.iterdir()] == ["m.glb"]  # no .ply, no PNG, no staging folder
    assert "[2/6] SS proj conditioning + flow" in heard and "done in 1.0s" in heard[-1]


async def test_the_arguments_of_the_3d_run_are_the_measured_ones(service, tmp_path, monkeypatch):
    seen: list[list[str]] = []
    real = service._run  # noqa: SLF001

    async def spy(install, args, cwd, wall_s, on_line):
        seen.append(args)
        return await real(install, args, cwd, wall_s, on_line)

    monkeypatch.setattr(service, "_run", spy)
    out = tmp_path / "m.glb"
    for detail, atlas in (("light", "1024"), ("standard", "2048"), ("detailed", "4096")):
        await service.generate(tmp_path / "c.png", out, seed=3, detail=detail)
        a = seen[-1]
        assert a[1] == "--sv-image" and a[a.index("--atlas") + 1] == atlas
        assert a[a.index("--res") + 1] == "1024" and a[a.index("--seed") + 1] == "3"
        assert a[a.index("--models") + 1].endswith("models/pixal3d-sv")
    assert dm.ATLAS == {"light": 1024, "standard": 2048, "detailed": 4096}


async def test_a_run_that_fails_says_so_and_leaves_nothing_behind(service, tmp_path, monkeypatch):
    behave(service, "fail")
    out = tmp_path / "m.glb"
    res = await service.generate(tmp_path / "c.png", out)
    assert not res.ok and res.reason == "failed" and "boom" in res.log_tail
    assert not out.exists() and list(tmp_path.glob("work-*")) == []


async def test_a_run_that_made_no_file_is_a_failure_not_a_success(service, tmp_path, monkeypatch):
    behave(service, "nofile")
    res = await service.generate(tmp_path / "c.png", tmp_path / "m.glb")
    assert not res.ok and "did not make a file" in res.message


async def test_cancelling_stops_the_process_and_gives_the_memory_back(
    service, tmp_path, monkeypatch
):
    behave(service, sleep=30)
    task = asyncio.create_task(service.generate(tmp_path / "c.png", tmp_path / "m.glb"))
    for _ in range(100):
        if service.busy:
            break
        await asyncio.sleep(0.05)
    assert service.busy
    pid = service._proc.pid  # type: ignore[union-attr]  # noqa: SLF001
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not service.busy
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # gone
    assert list(tmp_path.glob("work-*")) == []


async def test_stop_lets_go_of_the_memory_for_another_model(service, tmp_path, monkeypatch):
    behave(service, sleep=30)
    task = asyncio.create_task(service.generate(tmp_path / "c.png", tmp_path / "m.glb"))
    for _ in range(100):
        if service.busy:
            break
        await asyncio.sleep(0.05)
    await service.stop()
    res = await asyncio.wait_for(task, 10)
    assert not res.ok and not service.busy


async def test_a_run_that_takes_too_long_is_stopped(service, tmp_path, monkeypatch):
    behave(service, sleep=30)
    monkeypatch.setattr(dm, "GENERATE_WALL_S", 0.5)
    res = await service.generate(tmp_path / "c.png", tmp_path / "m.glb")
    assert not res.ok and res.reason == "wall_time" and "too long" in res.message
    assert not service.busy


async def test_without_the_component_a_run_says_to_set_it_up(tmp_path, monkeypatch):
    monkeypatch.delenv("WASIFYAI_MODEL3D_HOME", raising=False)
    svc = dm.Model3dService(tmp_path)
    # the pins list the computers 3D runs on (the Mac): elsewhere the answer is another sentence
    monkeypatch.setattr(type(svc.installer), "supported", property(lambda self: True))
    assert svc.ready() is False and "not set up" in (svc.problem() or "")
    res = await svc.generate(tmp_path / "c.png", tmp_path / "m.glb")
    assert not res.ok and res.reason == "missing"


async def test_a_run_holds_the_one_big_model_slot_while_it_works(service, tmp_path, monkeypatch):
    events: list[str] = []

    class Slot:
        def hold(self, owner):
            import contextlib

            @contextlib.asynccontextmanager
            async def ctx():
                events.append(f"take {owner}")
                try:
                    yield
                finally:
                    events.append(f"free {owner}")

            return ctx()

    service.slot = Slot()
    res = await service.matte(tmp_path / "in.png", tmp_path / "out")
    assert res.ok and events == ["take model3d", "free model3d"]


def test_the_state_tells_the_window_what_it_needs(service):
    state = service.state()
    assert state["installed"] is True and state["fit"]["verdict"] in ("fits", "tight", "too_big")
    assert state["about"]["built_with"] == "Built with DINOv3"
    assert state["plan"]["parts"] and state["progress"]["state"] == "idle"
