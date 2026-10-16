"""Setting up the document reader, with the commands and downloads replaced by fakes."""

import hashlib
import http.server
import json
import shutil
import threading
from pathlib import Path

import pytest
from wasifyai_notebooks import reader_install
from wasifyai_notebooks.reader_install import (
    PACKAGES_BYTES,
    InstallError,
    ReaderInstaller,
    WeightFile,
    fetch_file,
    load_weights,
    uv_target,
)

ROOT = Path(__file__).resolve().parents[1]


def test_the_shipped_weights_manifest_is_complete_and_safe():
    files = load_weights(ROOT / "reader" / "models.yaml")
    assert len(files) == 9
    assert all(f.url.startswith("https://") and len(f.sha256) == 64 for f in files)
    assert 400_000_000 < sum(f.size for f in files) < 430_000_000
    assert all(".." not in Path(f.path).parts and not Path(f.path).is_absolute() for f in files)
    assert {Path(f.path).parts[0] for f in files} == {
        "docling-project--docling-layout-heron",
        "docling-project--docling-models",
        "RapidOcr",
    }


def test_a_manifest_cannot_name_a_path_outside_the_folder(tmp_path):
    bad = tmp_path / "m.yaml"
    bad.write_text(
        "files:\n  - {path: ../../x, url: 'https://e.test/x', size: 1, sha256: '"
        + "a" * 64
        + "'}\n"
    )
    with pytest.raises(ValueError, match="not a relative path"):
        load_weights(bad)
    bad.write_text(
        "files:\n  - {path: a/b, url: 'http://e.test/x', size: 1, sha256: '" + "a" * 64 + "'}\n"
    )
    with pytest.raises(ValueError, match="https"):
        load_weights(bad)


class Rig:
    def __init__(
        self, tmp_path, *, packages_ok=True, read_text="Wasify reader check", fetch_bad=None
    ):
        self.calls: list[list[str]] = []
        self.packages_ok = packages_ok
        self.read_text = read_text
        self.fetch_bad = fetch_bad
        self.fetched: list[str] = []
        self.weights = [
            WeightFile("a/one.bin", "https://e.test/one", 10, "0" * 64),
            WeightFile("RapidOcr/two.onnx", "https://e.test/two", 20, "1" * 64),
        ]
        self.dir = tmp_path / "components" / "reader"
        self.installer = ReaderInstaller(
            reader_dir=self.dir,
            lock=tmp_path / "lock",
            weights=self.weights,
            worker_script=tmp_path / "worker.py",
            uv="uv",
            python="python3",
            run=self.run,
            fetch=self.fetch,
        )

    async def run(self, args, env):
        self.calls.append(args)
        if args[1:2] == ["venv"]:
            (Path(args[-1]) / "bin").mkdir(parents=True)
            (Path(args[-1]) / "bin" / "python").write_text("")
            return 0, ""
        if args[1:3] == ["pip", "install"]:
            return (0, "") if self.packages_ok else (1, "no network")
        if "--out" in args:
            out = Path(args[args.index("--out") + 1])
            out.write_text(json.dumps({"markdown": self.read_text}))  # noqa: ASYNC240
            return 0, ""
        return 0, ""

    async def fetch(self, item, target, tick):
        self.fetched.append(item.path)
        if self.fetch_bad == item.path:
            raise InstallError("weights", f"{target.name} did not download correctly (checksum).")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * item.size)
        tick(item.size)


async def test_an_install_runs_five_steps_and_records_the_result(tmp_path):
    rig = Rig(tmp_path)
    inst = rig.installer
    inst.start(PACKAGES_BYTES + 30)
    steps = []
    for _ in range(200):
        steps.append(inst.progress.step)
        if inst.progress.state != "installing":
            break
        import asyncio

        await asyncio.sleep(0.005)
    await inst.wait()
    assert inst.progress.state == "ready" and inst.is_installed()
    assert rig.fetched == ["a/one.bin", "RapidOcr/two.onnx"]
    assert (rig.dir / "models" / "RapidOcr" / "two.onnx").stat().st_size == 20
    cmds = [" ".join(c[:3]) for c in rig.calls]
    assert cmds[0].startswith("uv venv") and cmds[1].startswith("uv pip install")
    assert "--require-hashes" in rig.calls[1] and "--no-deps" in rig.calls[1]
    assert inst.progress.done_bytes == 30
    marker = json.loads((rig.dir / "installed.json").read_text())
    assert marker["id"] == "docling" and marker["target"] == uv_target()


async def test_the_size_the_person_was_shown_must_match(tmp_path):
    rig = Rig(tmp_path)
    with pytest.raises(InstallError, match="out of date"):
        rig.installer.start(123)
    assert rig.installer.progress.state == "idle" and not rig.calls


async def test_a_failed_step_removes_what_was_made_and_says_where(tmp_path):
    rig = Rig(tmp_path, packages_ok=False)
    rig.installer.start(rig.installer.total_bytes)
    await rig.installer.wait()
    p = rig.installer.progress
    assert p.state == "failed" and p.step == "packages" and "online" in p.message
    assert not rig.dir.exists()  # the next try starts clean


async def test_a_wrong_checksum_stops_at_the_weights(tmp_path):
    rig = Rig(tmp_path, fetch_bad="RapidOcr/two.onnx")
    rig.installer.start(rig.installer.total_bytes)
    await rig.installer.wait()
    p = rig.installer.progress
    assert p.state == "failed" and p.step == "weights" and "checksum" in p.message
    assert not rig.dir.exists() and not (tmp_path / "components" / "reader").exists()


async def test_a_reader_that_cannot_read_the_test_page_is_not_installed(tmp_path):
    rig = Rig(tmp_path, read_text="")
    rig.installer.start(rig.installer.total_bytes)
    await rig.installer.wait()
    p = rig.installer.progress
    assert p.state == "failed" and p.step == "check" and not rig.installer.is_installed()


async def test_too_little_disk_is_said_before_anything_is_fetched(tmp_path, monkeypatch):
    rig = Rig(tmp_path)

    class Usage:
        free = 1024**3

    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage())
    rig.installer.start(rig.installer.total_bytes)
    await rig.installer.wait()
    p = rig.installer.progress
    assert p.state == "failed" and p.step == "disk" and "free space" in p.message
    assert rig.calls == [] and rig.fetched == []


async def test_fetch_checks_size_and_sha256_and_keeps_only_a_good_file(tmp_path):
    body = b"weights" * 1000
    srv_dir = tmp_path / "srv"
    srv_dir.mkdir()
    (srv_dir / "w.bin").write_bytes(body)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(srv_dir), **k)

        def log_message(self, format, *args):  # noqa: A002
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/w.bin"
    seen = []
    try:
        good = WeightFile("d/w.bin", url, len(body), hashlib.sha256(body).hexdigest())
        await fetch_file(good, tmp_path / "out" / "w.bin", seen.append)
        assert (tmp_path / "out" / "w.bin").read_bytes() == body and sum(seen) == len(body)
        bad = WeightFile("d/w.bin", url, len(body), "f" * 64)
        with pytest.raises(InstallError, match="checksum"):
            await fetch_file(bad, tmp_path / "out2" / "w.bin", seen.append)
        assert not (tmp_path / "out2" / "w.bin").exists()
        assert not list((tmp_path / "out2").glob("*.part"))
    finally:
        server.shutdown()
    assert reader_install  # keep the import used
