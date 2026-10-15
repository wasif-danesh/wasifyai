"""ComfyUI as a sidecar of the desktop engine (ADR-0059).

`ComfySidecar` starts and supervises one ComfyUI process that the app installed itself (the
shell's installer put it under `<app data>/engine/comfyui`), on loopback with a free port.
`SidecarRunner` is the job runner that uses it: it checks the model files are there, makes sure
the process is running, and runs the job with the model kept loaded. The slot manager
(wasifyai_platform_sdk.slots) decides when the model is unloaded again.

The boundary is the loopback address and the process being the engine's own child; ComfyUI cannot
enforce a token (decision 2 of docs/phase2-stage-a-plan.md).
"""

import asyncio
import contextlib
import json
import logging
import os
import socket
import sys
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx
from wasifyai_platform_sdk import JobRequest

from wasifyai_media_worker.comfy import ComfyClient, ComfyError, ProgressFn
from wasifyai_media_worker.processor import ComfyRunner, Files, InputFiles

log = logging.getLogger(__name__)

# the folders ComfyUI looks in under a models root
MODEL_FOLDERS = (
    "checkpoints",
    "diffusion_models",
    "unet",
    "text_encoders",
    "clip",
    "vae",
    "loras",
    "controlnet",
    "upscale_models",
    "embeddings",
)
# which workflow input names a model file, and the folders that file may be in
LOADER_FIELDS: dict[str, tuple[str, ...]] = {
    "unet_name": ("diffusion_models", "unet"),
    "clip_name": ("text_encoders", "clip"),
    "vae_name": ("vae",),
    "lora_name": ("loras",),
    "ckpt_name": ("checkpoints",),
}
# folders ComfyUI needs to exist in its base directory (it stops at start-up without custom_nodes)
BASE_FOLDERS = ("models", "input", "output", "temp", "user", "custom_nodes")


@dataclass(frozen=True)
class SidecarConfig:
    data_dir: Path  # the app data folder
    models_dir: Path  # where the app puts models it downloads
    extra_model_dirs: tuple[Path, ...] = ()  # read-only roots with the standard folder layout
    startup_timeout_s: float = 120.0
    # more ComfyUI command-line arguments (memory mode and the like); empty by default
    extra_args: tuple[str, ...] = ()


def extra_model_paths_yaml(models_dir: Path, extra: Iterable[Path]) -> str:
    """ComfyUI's `extra_model_paths.yaml`: our models folder first, then the read-only ones."""
    lines: list[str] = []
    for i, root in enumerate([models_dir, *extra]):
        lines.append(f"wasifyai_{i}:")
        lines.append(f"  base_path: {json.dumps(str(root))}")
        if i == 0:
            lines.append("  is_default: true")
        for folder in MODEL_FOLDERS:
            lines.append(f"  {folder}: {folder}/")
    return "\n".join(lines) + "\n"


class ComfySidecar:
    def __init__(self, cfg: SidecarConfig):
        self._cfg = cfg
        self._proc: asyncio.subprocess.Process | None = None
        self._url: str | None = None
        self._start_lock = asyncio.Lock()
        self._http = httpx.AsyncClient(timeout=3)
        self._started_with: tuple[Path, tuple[Path, ...]] | None = None

    # ---- what is installed ---------------------------------------------------------------

    @property
    def _root(self) -> Path:
        return self._cfg.data_dir / "engine" / "comfyui"

    def _state(self) -> dict[str, Any] | None:
        try:
            data = json.loads((self._root / "state.json").read_text())
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    @property
    def venv_python(self) -> Path:
        sub = Path("Scripts") / "python.exe" if sys.platform == "win32" else Path("bin") / "python"
        return self._root / "venv" / sub

    @property
    def src_dir(self) -> Path | None:
        state = self._state()
        return self._root / str(state["comfyui"]) if state and "comfyui" in state else None

    @property
    def installed(self) -> bool:
        src = self.src_dir
        return bool(src and (src / "main.py").is_file() and self.venv_python.is_file())

    # ---- models --------------------------------------------------------------------------

    def set_model_dirs(self, models_dir: Path, extra_dirs: tuple[Path, ...]) -> None:
        """The person chose other folders. A running ComfyUI is restarted by the next job."""
        self._cfg = replace(self._cfg, models_dir=models_dir, extra_model_dirs=tuple(extra_dirs))

    def model_roots(self) -> list[Path]:
        return [self._cfg.models_dir, *self._cfg.extra_model_dirs]

    def find_model(self, folders: Iterable[str], filename: str) -> Path | None:
        for root in self.model_roots():
            for folder in folders:
                candidate = root / folder / filename
                if candidate.is_file():
                    return candidate
        return None

    def missing_models(self, graph: dict[str, Any]) -> list[str]:
        """Model files the workflow names that are in none of the models folders."""
        missing: list[str] = []
        for node in graph.values():
            for field, folders in LOADER_FIELDS.items():
                name = (node.get("inputs") or {}).get(field)
                if isinstance(name, str) and name and not self.find_model(folders, name):
                    if name not in missing:
                        missing.append(name)
        return missing

    # ---- the process --------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def _healthy(self, url: str) -> bool:
        try:
            return (await self._http.get(f"{url}/system_stats")).status_code == 200
        except httpx.HTTPError:
            return False

    async def ensure_running(self) -> str:
        """The base URL of a running ComfyUI, starting it if needed."""
        async with self._start_lock:
            current = (self._cfg.models_dir, self._cfg.extra_model_dirs)
            if (
                self.running
                and self._url
                and self._started_with == current
                and await self._healthy(self._url)
            ):
                return self._url
            await self._terminate()
            if not self.installed:
                raise ComfyError(
                    "not_installed",
                    "Image generation is not set up yet. Choose Set up image generation first.",
                )
            return await self._start()

    async def _start(self) -> str:
        src = self.src_dir
        assert src is not None
        base = self._cfg.data_dir / "comfyui-data"
        for folder in BASE_FOLDERS:
            (base / folder).mkdir(parents=True, exist_ok=True)
        self._cfg.models_dir.mkdir(parents=True, exist_ok=True)
        paths_file = base / "extra_model_paths.yaml"
        paths_file.write_text(
            extra_model_paths_yaml(self._cfg.models_dir, self._cfg.extra_model_dirs)
        )
        with socket.socket() as s:  # a free port on loopback
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        logs = self._cfg.data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        out = (logs / "comfyui.log").open("ab")
        env = {**os.environ, "PYTHONNOUSERSITE": "1", "PYTHONUNBUFFERED": "1"}
        try:
            self._proc = await asyncio.create_subprocess_exec(
                str(self.venv_python),
                "main.py",
                "--listen", "127.0.0.1",
                "--port", str(port),
                "--disable-auto-launch",
                "--base-directory", str(base),
                "--extra-model-paths-config", str(paths_file),
                *self._cfg.extra_args,
                cwd=str(src),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=out,
                stderr=asyncio.subprocess.STDOUT,
            )  # fmt: skip
        finally:
            out.close()
        self._started_with = (self._cfg.models_dir, self._cfg.extra_model_dirs)
        log.info("started ComfyUI (pid %s) on %s", self._proc.pid, url)
        deadline = asyncio.get_running_loop().time() + self._cfg.startup_timeout_s
        while asyncio.get_running_loop().time() < deadline:
            if self._proc.returncode is not None:
                break
            if await self._healthy(url):
                self._url = url
                return url
            await asyncio.sleep(0.25)
        code = self._proc.returncode
        await self._terminate()
        log.error("ComfyUI did not start (exit %s); see logs/comfyui.log", code)
        raise ComfyError("start_failed", "The image engine did not start. Try again, or repair it.")

    async def _terminate(self) -> None:
        proc, self._proc, self._url = self._proc, None, None
        if proc is None or proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()

    async def stop(self) -> None:
        async with self._start_lock:
            await self._terminate()
        await self._http.aclose()

    async def unload_models(self) -> None:
        """Ask a running ComfyUI to release its models (the slot manager's unload)."""
        if self.running and self._url:
            await ComfyClient(self._url).free()


class SidecarRunner:
    """Runs jobs on the sidecar. Same shape as `ComfyRunner` (see processor.Runner)."""

    backend = "comfyui-local"
    local_gpu = True

    def __init__(self, sidecar: ComfySidecar, timeout_s: float):
        self._sidecar = sidecar
        self._timeout = timeout_s
        self._clients: dict[str, ComfyClient] = {}

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files:
        if not self._sidecar.installed:
            raise ComfyError(
                "not_installed",
                "Image generation is not set up yet. Choose Set up image generation first.",
            )
        missing = self._sidecar.missing_models(job.prompt)
        if missing:
            log.warning("model files missing for job %s: %s", job.job_id, ", ".join(missing))
            raise ComfyError(
                "models_missing",
                "The image model files are not on this computer yet. Get the model first.",
            )
        url = await self._sidecar.ensure_running()
        client = self._clients.setdefault(url, ComfyClient(url))
        runner = ComfyRunner(client, self._timeout, free_after_job=False)
        return await runner.run(job, on_progress, files=files)


class AutoRunner:
    """The real engine once it is installed, the placeholder engine until then, decided per job, so
    setting the image engine up takes effect without restarting the app."""

    local_gpu = True

    def __init__(self, sidecar: ComfySidecar, real: SidecarRunner, placeholder: Any):
        self._sidecar = sidecar
        self._real = real
        self._placeholder = placeholder

    @property
    def backend(self) -> str:
        return self._real.backend if self._sidecar.installed else self._placeholder.backend

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files:
        target = self._real if self._sidecar.installed else self._placeholder
        if files:
            return await target.run(job, on_progress, files=files)
        return await target.run(job, on_progress)
