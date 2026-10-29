"""The image engine on the one installer (stage F2; it was the shell's comfyui.rs): seven steps, the
lock from the engine bundle, the state file the media worker's sidecar has always read. uv and the
environment's python are fakes that answer the way the real ones do."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import httpx
import pytest
from wasifyai_api.components.comfyui import STEPS, ComfyUiComponent
from wasifyai_api.components.manifest import Manifest, Pins, load_manifest
from wasifyai_platform_sdk.installer import Archive, InstallError

URL = "https://example.test/ComfyUI-0.40.0.tar.gz"
TRIPLE = "aarch64-apple-darwin"
LOCK = "torch==2.0 --hash=sha256:abc\n"


def source(with_main: bool = True) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        files = {"ComfyUI-0.40.0/nodes.py": b"x"}
        if with_main:
            files["ComfyUI-0.40.0/main.py"] = b"print('hi')"
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def bundle(tmp_path: Path, version: str = "0.40.0") -> Path:
    d = tmp_path / "bundle"
    (d / "comfyui").mkdir(parents=True)
    lock = d / "comfyui" / f"requirements-{TRIPLE}.lock"
    lock.write_text(LOCK)
    sha = hashlib.sha256(LOCK.encode()).hexdigest()
    (d / "bundle.json").write_text(json.dumps({"schema": 1, "comfyui": {
        "version": version, "locks": {TRIPLE: {"file": f"comfyui/requirements-{TRIPLE}.lock",
                                              "sha256": sha}}}}))  # fmt: skip
    return d


class Tools:
    """uv and the new environment's python, answering as the real ones do."""

    def __init__(self, accel: str = "mps", quick_test_ok: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.accel, self.quick_test_ok = accel, quick_test_ok

    async def __call__(self, args, env, cwd):
        self.calls.append(args)
        if args[1:3] == ["python", "install"]:
            assert env["UV_PYTHON_PREFERENCE"] == "only-managed" and env["UV_NO_CONFIG"] == "1"
            return 0, "installed Python 3.12.15"
        if args[1] == "venv":
            py = Path(args[-1]) / "bin" / "python"
            py.parent.mkdir(parents=True)
            py.write_text("#!/bin/sh\n")
            return 0, "Creating virtual environment"
        if args[1:3] == ["pip", "install"]:
            assert "--require-hashes" in args
            return 0, "Installed 40 packages"
        if args[1] == "-c":
            return 0, f"ACCEL {self.accel}\n"
        if args[1] == "main.py":
            return (0, "quick test passed") if self.quick_test_ok else (1, "ImportError: torch")
        raise AssertionError(args)


def component(tmp_path: Path, body: bytes, tools: Tools, bundle_dir: Path | None = None):
    pin = Archive(URL, len(body), hashlib.sha256(body).hexdigest(), "tar.gz", strip=1)
    pins = Pins("comfyui", "Image engine (ComfyUI)", "0.40.0", "", 1000, pin,
                {"lock": f"comfyui/requirements-{TRIPLE}.lock"})  # fmt: skip
    client = lambda: httpx.AsyncClient(  # noqa: E731
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    )
    uv = tmp_path / "uv"
    uv.write_text("#!/bin/sh\n")
    return ComfyUiComponent(
        tmp_path / "data", Manifest("darwin-arm64", "3.12.15", {"comfyui": pins}),
        bundle_dir if bundle_dir is not None else bundle(tmp_path), str(uv), run=tools,
        client=client,
    )  # fmt: skip


async def test_it_installs_in_seven_steps_and_records_what_torch_runs_on(tmp_path):
    tools = Tools()
    c = component(tmp_path, source(), tools)
    heard: list[dict] = []
    c.installer.listeners.append(lambda cid, s: heard.append(s))
    assert c.status() == {"state": "not_installed", "needs_bytes": 1000}
    c.install(1000)
    await c.wait()
    assert c.status() == {"state": "installed", "version": "0.40.0", "accelerator": "mps"}
    steps = [s["progress"]["step"] for s in heard if s["state"] == "installing"]
    assert list(dict.fromkeys(steps)) == [s.id for s in STEPS]
    root = tmp_path / "data" / "engine" / "comfyui"
    state = json.loads((root / "state.json").read_text())
    assert state == {"schema": 1, "comfyui": "0.40.0", "python": "3.12.15",
                     "lock_sha256": hashlib.sha256(LOCK.encode()).hexdigest(),
                     "accelerator": "mps"}  # fmt: skip
    assert (root / "0.40.0" / "main.py").is_file()
    # the sidecar reads the same place it always did
    from wasifyai_media_worker.sidecar import ComfySidecar, SidecarConfig

    sidecar = ComfySidecar(SidecarConfig(tmp_path / "data", tmp_path / "models", ()))
    assert sidecar.installed


async def test_without_the_lock_in_the_bundle_nothing_is_fetched(tmp_path):
    tools = Tools()
    c = component(tmp_path, source(), tools, bundle_dir=bundle(tmp_path, version="0.39.0"))
    c.install(1000)
    await c.wait()
    s = c.status()
    assert (s["state"], s["step"]) == ("failed", "check") and "package list" in s["message"]
    assert tools.calls == []


async def test_a_lock_that_changed_makes_an_install_look_missing(tmp_path):
    tools = Tools()
    b = bundle(tmp_path)
    c = component(tmp_path, source(), tools, bundle_dir=b)
    c.install(1000)
    await c.wait()
    assert c.status()["state"] == "installed"
    lock = b / "comfyui" / f"requirements-{TRIPLE}.lock"
    lock.write_text(LOCK + "numpy==2 --hash=sha256:def\n")
    record = json.loads((b / "bundle.json").read_text())
    record["comfyui"]["locks"][TRIPLE]["sha256"] = hashlib.sha256(lock.read_bytes()).hexdigest()
    (b / "bundle.json").write_text(json.dumps(record))
    assert c.status()["state"] == "not_installed"  # a new build of the app brings new packages


async def test_comfyui_that_does_not_start_stops_at_verify_and_is_not_recorded(tmp_path):
    c = component(tmp_path, source(), Tools(quick_test_ok=False))
    c.install(1000)
    await c.wait()
    assert (c.status()["state"], c.status()["step"]) == ("failed", "verify")
    assert not (tmp_path / "data" / "engine" / "comfyui" / "state.json").exists()


async def test_a_source_without_main_py_stops_at_the_source_step(tmp_path):
    c = component(tmp_path, source(with_main=False), Tools())
    c.install(1000)
    await c.wait()
    assert (c.status()["state"], c.status()["step"]) == ("failed", "source")


async def test_a_repair_makes_the_environment_again_and_the_size_must_match(tmp_path):
    tools = Tools()
    c = component(tmp_path, source(), tools)
    with pytest.raises(InstallError, match="out of date"):
        c.install(999)
    c.install(1000)
    await c.wait()
    with pytest.raises(InstallError, match="already set up"):
        c.install(1000)
    before = len(tools.calls)
    c.install(None, repair=True)
    await c.wait()
    assert c.status()["state"] == "installed"
    assert any(call[1] == "venv" for call in tools.calls[before:])


def test_only_apple_silicon_pins_the_image_engine():
    for key in ("darwin-x64", "linux-x64", "linux-arm64", "windows-x64"):
        assert load_manifest(key).get("comfyui") is None, key
    pins = load_manifest("darwin-arm64").get("comfyui")
    assert pins is not None and pins.archive is not None and pins.min_free_bytes > 1_000_000_000
    assert pins.archive.url.endswith(f"v{pins.version}.tar.gz")


def test_a_computer_without_a_pin_is_told_so_in_words(tmp_path):
    c = ComfyUiComponent(tmp_path, Manifest("linux-x64", "3.12.15", {}), None, None)
    s = c.status()
    assert s["state"] == "unsupported" and "Apple-silicon Mac" in s["reason"]
