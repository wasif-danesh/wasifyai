"""The image engine: ComfyUI's pinned source in a Python environment of its own (ADR-0059), set up
by the engine (stage F2; it was the shell's `comfyui.rs`).

    1 check        this computer is supported, the bundle carries the lock for it, there is room
    2 uv           the app's own uv (the shell put it there on the first run)
    3 python       `uv python install <the app's Python>` (already there after the first run)
    4 source       the pinned release archive, SHA-256 checked, unpacked
    5 environment  `uv venv` for ComfyUI alone: its torch must not touch the engine's packages
    6 packages     the hashed lock for this platform, from the engine bundle
    7 verify       torch imports (and says what it runs on), `main.py --quick-test-for-ci`

The state file is `<app data>/engine/comfyui/state.json`, the one the media worker's sidecar has
always read, so a ComfyUI the shell set up before is still found.
"""

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from wasifyai_api.components.core import (
    ClientFactory,
    Installer,
    InstallError,
    Runner,
    Step,
    check_disk,
    clean_env,
    default_client,
    fetch_archive,
    folder_bytes,
    make_environment,
    read_state,
    run_command,
    sha256_of,
    status_installed,
    status_missing,
    status_unsupported,
    venv_python,
    write_state,
)
from wasifyai_api.components.manifest import Manifest, Pins

ID = "comfyui"
STEPS = (
    Step("check", "Checking this computer"),
    Step("uv", "Getting the installer"),
    Step("python", "Installing Python"),
    Step("source", "Getting ComfyUI"),
    Step("environment", "Creating ComfyUI's environment"),
    Step("packages", "Installing ComfyUI's packages"),
    Step("verify", "Checking ComfyUI"),
)
UNSUPPORTED = (
    "Real images need an Apple-silicon Mac in this version. The placeholder engine still works."
)
ACCEL = (
    "import torch; print('ACCEL', 'mps' if torch.backends.mps.is_available() "
    "else 'cuda' if torch.cuda.is_available() else 'cpu')"
)


def uv_env(engine_root: Path) -> dict[str, str]:
    """uv as the shell runs it: the app's own Python and cache, no outside configuration."""
    return clean_env(
        extra={
            "UV_PYTHON_INSTALL_DIR": str(engine_root / "python"),
            "UV_CACHE_DIR": str(engine_root / "cache"),
            "UV_NO_CONFIG": "1",
            "UV_PYTHON_PREFERENCE": "only-managed",
            "UV_LINK_MODE": "copy",
            "UV_NO_PROGRESS": "1",
            "NO_COLOR": "1",
        }
    )


def _runnable(program: str | None) -> bool:
    return bool(program) and (
        Path(str(program)).is_file() or shutil.which(str(program)) is not None
    )


class ComfyUiComponent:
    id = ID
    title = "Image engine (ComfyUI)"

    def __init__(
        self,
        data_dir: Path,
        manifest: Manifest,
        bundle_dir: Path | None,
        uv: str | None,
        run: Runner = run_command,
        client: ClientFactory = default_client,
        allow_http: bool = False,
    ):
        self.engine_root = data_dir / "engine"
        self.root = self.engine_root / "comfyui"
        self.python = manifest.python
        self.pins: Pins | None = manifest.get(ID)
        self.bundle_dir = bundle_dir
        self.uv = uv
        self.installer = Installer(ID, STEPS, data_dir / "logs")
        self._run = run
        self._client = client
        self._allow_http = allow_http

    # ---- what is there ---------------------------------------------------------------------

    def lock(self) -> tuple[Path, str] | None:
        """The package lock this build carries for this computer, with its SHA-256 (the bundle's
        `bundle.json` records both)."""
        p = self.pins
        if p is None or self.bundle_dir is None:
            return None
        try:
            bundle = json.loads((self.bundle_dir / "bundle.json").read_text())
            comfy = bundle.get("comfyui") or {}
            triple = str(p.extra.get("lock", "")).split("requirements-")[-1].removesuffix(".lock")
            entry = (comfy.get("locks") or {}).get(triple)
            if not entry or comfy.get("version") != p.version:
                return None
            path = (self.bundle_dir / str(entry["file"])).resolve()
            if self.bundle_dir.resolve() not in path.parents:
                return None
            return path, str(entry["sha256"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def installed(self) -> dict[str, Any] | None:
        p = self.pins
        state = read_state(self.root / "state.json")
        if p is None or state is None:
            return None
        lock = self.lock()
        lock_ok = lock is None or state.get("lock_sha256") == lock[1]  # no bundle: as it is
        whole = (
            venv_python(self.root / "venv").is_file()
            and (self.root / p.version / "main.py").is_file()
        )
        if (
            state.get("schema") != 1
            or state.get("comfyui") != p.version
            or state.get("python") != self.python
            or not lock_ok
            or not whole
        ):
            return None
        return state

    def status(self) -> dict[str, Any]:
        if (now := self.installer.current()) is not None:
            return now
        p = self.pins
        if p is None or p.archive is None:
            return status_unsupported(UNSUPPORTED)
        if (state := self.installed()) is not None:
            return status_installed(str(state["comfyui"]), str(state.get("accelerator", "")))
        return status_missing(p.min_free_bytes)

    # ---- changing it -----------------------------------------------------------------------

    def install(self, confirm_bytes: int | None, repair: bool = False) -> None:
        p = self.pins
        if p is None or p.archive is None:
            raise InstallError(UNSUPPORTED)
        if not repair and self.installed() is not None:
            raise InstallError("The image engine is already set up.")
        if confirm_bytes is not None and confirm_bytes != p.min_free_bytes:
            raise InstallError("The size shown is out of date. Look at it again.")
        self.installer.start(lambda inst: self._steps(inst, p, repair), self.status)

    def cancel(self) -> bool:
        return self.installer.cancel()

    async def wait(self) -> None:
        await self.installer.wait()

    def uninstall(self) -> int:
        if self.installer.running:
            raise InstallError("The image engine is being set up. Stop it first.")
        freed = folder_bytes(self.root)
        shutil.rmtree(self.root, ignore_errors=True)
        self.installer.failed = None
        return freed

    async def _steps(self, inst: Installer, p: Pins, repair: bool) -> None:
        assert p.archive is not None
        inst.at("check")
        lock = await asyncio.to_thread(self.lock)
        if lock is None:
            raise InstallError(
                "This build carries no package list for the image engine on this computer. "
                "Build the engine files again with scripts/build-engine-bundle.sh.",
                "check",
            )
        what = "Image generation"
        await asyncio.to_thread(check_disk, self.root, p.min_free_bytes, what, "check")
        src, venv = self.root / p.version, self.root / "venv"
        (self.root / "state.json").unlink(missing_ok=True)
        if repair:
            shutil.rmtree(venv, ignore_errors=True)
            shutil.rmtree(src, ignore_errors=True)

        inst.at("uv")
        uv = self.uv
        if uv is None or not await asyncio.to_thread(_runnable, uv):
            raise InstallError("The installer (uv) is missing. Repair the app and try again.", "uv")
        env = uv_env(self.engine_root)

        inst.at("python")
        code, out = await self._run([uv, "python", "install", self.python], env, None)
        inst.line(out.strip()[-300:])
        if code != 0:
            raise InstallError("Python could not be installed. Are you online?", "python")

        if not (src / "main.py").is_file():
            await fetch_archive(
                inst, p.archive, self.root / "downloads", src, "main.py", "source",
                client=self._client, allow_http=self._allow_http,
            )  # fmt: skip
        else:
            inst.at("source")

        py = await make_environment(
            inst, uv, self.python, venv, lock[0], lock[1], "environment", "packages",
            self._run, env,
        )  # fmt: skip

        inst.at("verify")
        py_env = clean_env(extra={"PYTHONNOUSERSITE": "1"})
        code, out = await self._run([str(py), "-c", ACCEL], py_env, src)
        accel = next((ln.split()[-1] for ln in out.splitlines() if ln.startswith("ACCEL ")), "")
        if code != 0 or not accel:
            inst.line(out.strip()[-600:])
            raise InstallError("torch does not start in its new environment.", "verify")
        code, out = await self._run([str(py), "main.py", "--quick-test-for-ci"], py_env, src)
        inst.line(out.strip()[-600:])
        if code != 0:
            raise InstallError("ComfyUI does not start.", "verify")
        inst.line(f"accelerator: {accel}")
        write_state(
            self.root / "state.json",
            {
                "schema": 1, "comfyui": p.version, "python": self.python,
                "lock_sha256": sha256_of(lock[0]), "accelerator": accel,
            },
        )  # fmt: skip
        shutil.rmtree(self.engine_root / "cache", ignore_errors=True)
        shutil.rmtree(self.root / "downloads", ignore_errors=True)
