"""The desktop's ComfyUI sidecar: its model paths, its process, and the runner that uses it."""

import json
import stat
import sys
import textwrap
from pathlib import Path

import pytest
import yaml
from wasifyai_media_worker.comfy import ComfyError
from wasifyai_media_worker.processor import StubRunner
from wasifyai_media_worker.sidecar import (
    AutoRunner,
    ComfySidecar,
    SidecarConfig,
    SidecarRunner,
    extra_model_paths_yaml,
)
from wasifyai_platform_sdk import JobRequest

RUN, THREAD = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
KLEIN = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "products/wasifyai-image/workflows/flux2-klein-4b.json"
    ).read_text()
)

# a stand-in for ComfyUI's main.py: answers /system_stats, records how it was started
FAKE_MAIN = textwrap.dedent(
    """
    import http.server, json, os, sys
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1])
    base = args[args.index("--base-directory") + 1]
    with open(os.path.join(base, "started.json"), "w") as f:
        json.dump({"args": args, "cwd": os.getcwd(), "pid": os.getpid()}, f)
    if "EXIT_AT_START" in os.environ.get("FAKE_MODE", ""):
        sys.exit(3)
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
        def log_message(self, *a): pass
    http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
    """
)


def job(graph: dict) -> JobRequest:
    return JobRequest(
        tenant_id="t1", product_id="p1", user_id="u1", run_id=RUN, thread_id=THREAD,
        capability="image.generate", workflow="flux2-klein-4b", prompt=graph,
        outputs={"image": {"node": "13", "type": "image"}},
    )  # fmt: skip


def install_fake(data: Path, main: str = FAKE_MAIN) -> None:
    """The files the shell's installer would have made, with a fake ComfyUI in them."""
    root = data / "engine" / "comfyui"
    (root / "0.40.0").mkdir(parents=True)
    (root / "0.40.0" / "main.py").write_text(main)
    (root / "state.json").write_text(json.dumps({"schema": 1, "comfyui": "0.40.0"}))
    py = root / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    py.chmod(py.stat().st_mode | stat.S_IXUSR)


def sidecar(tmp_path: Path, extra: tuple[Path, ...] = (), timeout: float = 20) -> ComfySidecar:
    return ComfySidecar(
        SidecarConfig(tmp_path, tmp_path / "models", extra, startup_timeout_s=timeout)
    )


# ---- model paths ------------------------------------------------------------------------------


def test_the_extra_paths_file_lists_our_folder_first_and_the_read_only_ones_after(tmp_path):
    text = extra_model_paths_yaml(tmp_path / "models", [Path("/Users/me/ComfyUI-Shared/models")])
    doc = yaml.safe_load(text)
    assert list(doc) == ["wasifyai_0", "wasifyai_1"]
    assert doc["wasifyai_0"]["base_path"] == str(tmp_path / "models")
    assert doc["wasifyai_0"]["is_default"] is True
    assert doc["wasifyai_1"]["base_path"] == "/Users/me/ComfyUI-Shared/models"
    assert "is_default" not in doc["wasifyai_1"]
    assert doc["wasifyai_1"]["diffusion_models"] == "diffusion_models/"
    assert doc["wasifyai_1"]["text_encoders"] == "text_encoders/"


def test_missing_models_are_found_in_every_folder_the_workflow_may_use(tmp_path):
    shared = tmp_path / "shared"
    for folder, name in [
        ("diffusion_models", "flux-2-klein-4b.safetensors"),
        ("text_encoders", "qwen_3_4b.safetensors"),
    ]:
        (shared / folder).mkdir(parents=True)
        (shared / folder / name).write_bytes(b"x")
    s = sidecar(tmp_path, (shared,))
    assert s.missing_models(KLEIN) == ["flux2-vae.safetensors"]
    (tmp_path / "models" / "vae").mkdir(parents=True)
    (tmp_path / "models" / "vae" / "flux2-vae.safetensors").write_bytes(b"x")
    assert s.missing_models(KLEIN) == []
    assert s.missing_models({"1": {"class_type": "SaveImage", "inputs": {}}}) == []


# ---- the process ------------------------------------------------------------------------------

unix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake interpreter is a script")


@unix_only
async def test_it_starts_comfyui_once_with_the_right_arguments_and_folders(tmp_path):
    install_fake(tmp_path)
    s = sidecar(tmp_path, (tmp_path / "shared",))
    try:
        url = await s.ensure_running()
        assert url.startswith("http://127.0.0.1:")
        assert await s.ensure_running() == url  # reused, not started again

        started = json.loads((tmp_path / "comfyui-data" / "started.json").read_text())
        args = started["args"]
        assert args[args.index("--listen") + 1] == "127.0.0.1"
        assert "--disable-auto-launch" in args
        assert args[args.index("--base-directory") + 1] == str(tmp_path / "comfyui-data")
        assert started["cwd"] == str(tmp_path / "engine" / "comfyui" / "0.40.0")
        for folder in ("models", "input", "output", "temp", "user", "custom_nodes"):
            assert (tmp_path / "comfyui-data" / folder).is_dir(), folder
        paths = yaml.safe_load((tmp_path / "comfyui-data" / "extra_model_paths.yaml").read_text())
        assert paths["wasifyai_1"]["base_path"] == str(tmp_path / "shared")
        assert (tmp_path / "logs" / "comfyui.log").exists()
    finally:
        await s.stop()
    assert not s.running


@unix_only
async def test_it_starts_a_new_process_when_the_old_one_died(tmp_path):
    install_fake(tmp_path)
    s = sidecar(tmp_path)
    try:
        first = await s.ensure_running()
        s._proc.kill()  # type: ignore[union-attr]
        await s._proc.wait()  # type: ignore[union-attr]
        second = await s.ensure_running()
        assert second != first or s.running
        assert s.running
    finally:
        await s.stop()


@unix_only
async def test_a_process_that_exits_at_start_is_a_plain_error(tmp_path, monkeypatch):
    install_fake(tmp_path)
    monkeypatch.setenv("FAKE_MODE", "EXIT_AT_START")
    s = sidecar(tmp_path, timeout=10)
    with pytest.raises(ComfyError) as e:
        await s.ensure_running()
    assert e.value.code == "start_failed"
    assert "did not start" in e.value.message
    assert not s.running
    await s.stop()


async def test_nothing_is_started_when_the_component_is_not_installed(tmp_path):
    s = sidecar(tmp_path)
    assert not s.installed
    with pytest.raises(ComfyError) as e:
        await s.ensure_running()
    assert e.value.code == "not_installed"
    await s.stop()


# ---- the runner -------------------------------------------------------------------------------


class FakeSidecar:
    """What the runner needs from a sidecar, pointed at the fake ComfyUI of the test fixture."""

    def __init__(self, url: str, installed=True, missing=None):
        self.url, self.installed, self._missing = url, installed, missing or []
        self.started = 0

    def missing_models(self, graph):
        return self._missing

    async def ensure_running(self):
        self.started += 1
        return self.url


GRAPH = {
    "8": {"class_type": "KSampler", "inputs": {}},
    "10": {"class_type": "SaveImage", "inputs": {}},
}


def graph_job() -> JobRequest:
    j = job(GRAPH)
    j.outputs = {"image": {"node": "10", "type": "image"}}
    return j


async def test_the_runner_runs_the_job_and_keeps_the_model_loaded(comfy):
    base, fake = comfy
    s = FakeSidecar(base)
    progress: list[float] = []

    async def on_progress(p: float) -> None:
        progress.append(p)

    files = await SidecarRunner(s, 10).run(graph_job(), on_progress)  # type: ignore[arg-type]
    assert list(files) == ["image"] and files["image"][1] == "image/png"
    assert progress and progress[-1] == 1.0
    assert fake.freed == 0  # the web profile frees after every job; the desktop does not
    assert s.started == 1


async def test_the_runner_says_so_when_model_files_are_missing(comfy):
    base, fake = comfy
    s = FakeSidecar(base, missing=["flux-2-klein-4b.safetensors"])
    with pytest.raises(ComfyError) as e:
        await SidecarRunner(s, 10).run(graph_job(), lambda p: None)  # type: ignore[arg-type]
    assert e.value.code == "models_missing" and "model" in e.value.message
    assert fake.submitted == [] and s.started == 0  # nothing was started or sent


async def test_the_runner_says_so_when_the_engine_is_not_installed(comfy):
    base, _ = comfy
    s = FakeSidecar(base, installed=False)
    with pytest.raises(ComfyError) as e:
        await SidecarRunner(s, 10).run(graph_job(), lambda p: None)  # type: ignore[arg-type]
    assert e.value.code == "not_installed"


async def test_auto_uses_the_placeholder_until_the_engine_is_installed(comfy):
    base, fake = comfy
    s = FakeSidecar(base, installed=False)
    auto = AutoRunner(s, SidecarRunner(s, 10), StubRunner())  # type: ignore[arg-type]
    assert auto.backend == "stub"

    async def on_progress(p: float) -> None:
        pass

    out = await auto.run(graph_job(), on_progress)
    assert out["image"][1] == "image/png" and fake.submitted == []  # the fake ComfyUI saw nothing

    s.installed = True
    assert auto.backend == "comfyui-local"
    await auto.run(graph_job(), on_progress)
    assert len(fake.submitted) == 1
