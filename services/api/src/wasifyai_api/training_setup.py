"""Setting up the picture trainer (ADR-0073): mflux in an environment of its own, and the model it
teaches, under `<app data>/components/mflux/`. Nothing is fetched before the person has seen what it
is and how large, and has agreed.

Steps, the same shape as the other components, checked at the end:

    1 disk         enough free space, said before anything is downloaded
    2 environment  `uv venv` from the engine's own interpreter (no download)
    3 packages     `uv pip install --require-hashes -r <the lock>` (the lock is committed:
                   `scripts/lock-trainer.sh`); the exact versions the real runs were made with
    4 model        the base model's files, each with a pinned size and SHA-256, through the same
                   resumable downloader the Models screen uses (its part of the component
                   manifests, `components/manifests/<platform>.yaml`)
    5 check        the tool starts and every model file is there; only then `installed.json`

A failed install removes the environment it made, but keeps the model files that arrived: a new
start continues where it stopped. Where mflux and the model are already on the computer (a copy
named by `WASIFYAI_MFLUX_DIR`, a Hugging Face cache that holds the base
model) they are used where they are and nothing is offered.

mflux runs on MLX: Apple silicon only. Elsewhere the setup says so and offers nothing.
"""

import asyncio
import contextlib
import json
import logging
import os
import platform
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity, installer

from wasifyai_api.components.manifest import legacy_digest, part_pins, pins_digest
from wasifyai_api.desktop_models import (
    DownloadError,
    DownloadManager,
    ModelEntry,
    ModelFile,
    free_disk_bytes,
)
from wasifyai_api.identity import get_identity
from wasifyai_api.services import services_of

log = logging.getLogger(__name__)

PART = "trainer-pictures"  # its pins in the component manifests
LOCK_NAME = "requirements-aarch64-apple-darwin.lock"
STATE_FILE = "installed.json"
EXECUTABLE = "mflux-train"
MIN_FREE_BYTES = 3 * 1024**3  # room to work in, besides what is downloaded
HUB = "https://huggingface.co"

STEPS = ("disk", "environment", "packages", "model", "check")
STEP_TEXT = {
    "disk": "Checking free space",
    "environment": "Preparing the trainer's environment",
    "packages": "Installing the trainer's packages (about 1 GB)",
    "model": "Getting the picture model",
    "check": "Checking that it starts",
}


# the one installer's error (stage F2): `str(e)` is a sentence safe to show, `step` where it stopped
InstallError = installer.InstallError


def apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


# ---- the pins ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BaseFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Pins:
    tool_version: str
    tool_licence: str
    packages_bytes: int
    base_id: str
    base_title: str
    base_repo: str
    base_revision: str
    base_licence: str
    base_folder: str
    base_files: tuple[BaseFile, ...]
    digest: str  # of the pins: what an install records, so a changed pin asks for a new one

    legacy: str | None = None  # what installs made before the pins moved to the manifests recorded

    def made_from(self, recorded: object) -> bool:
        """Whether an install's record was made from these pins."""
        return recorded is not None and recorded in (self.digest, self.legacy)

    @property
    def base_bytes(self) -> int:
        return sum(f.size for f in self.base_files)


def load_pins(path: Path | None = None, part: str = PART) -> Pins:
    """A trainer's pins: its part in this platform's component manifest (stage F2), or a file."""
    raw = json.loads(path.read_text()) if path is not None else part_pins(part)
    tool, base = raw["tool"], raw["base"]
    files = []
    for f in base["files"]:
        parts = Path(f["path"]).parts
        if ".." in parts or Path(f["path"]).is_absolute() or len(str(f["sha256"])) != 64:
            raise ValueError(f"the pin for {f['path']} needs a relative path and a SHA-256")
        files.append(BaseFile(f["path"], int(f["size"]), str(f["sha256"]).lower()))
    return Pins(
        tool_version=str(tool["version"]),
        tool_licence=str(tool["licence"]),
        packages_bytes=int(tool["packages_bytes"]),
        base_id=str(base["id"]),
        base_title=str(base["title"]),
        base_repo=str(base["repo"]),
        base_revision=str(base["revision"]),
        base_licence=str(base["licence"]),
        base_folder=str(base["folder"]),
        base_files=tuple(files),
        digest=pins_digest(raw),
        legacy=legacy_digest(raw),
    )


# ---- where things are ----------------------------------------------------------------------------


def component_root(data_dir: Path) -> Path:
    return data_dir / "components" / "mflux"


def _tool_in(home: Path) -> bool:
    return (home / "bin" / EXECUTABLE).is_file()


def managed_tool(data_dir: Path, pins: Pins) -> Path | None:
    """The environment this app installed, when it still matches the pins."""
    root = component_root(data_dir)
    try:
        state = json.loads((root / STATE_FILE).read_text())
    except (OSError, ValueError):
        return None
    home = root / "venv"
    if state.get("schema") == 1 and pins.made_from(state.get("pins")) and _tool_in(home):
        return home
    return None


def find_tool(data_dir: Path | None, pins: Pins | None = None) -> tuple[Path, str] | None:
    """(the environment with `bin/mflux-train`, where it came from): a copy named by
    `WASIFYAI_MFLUX_DIR` (development and CI), or the one this app installed."""
    pins = pins or load_pins()
    env = os.environ.get("WASIFYAI_MFLUX_DIR")
    if env and _tool_in(Path(env).expanduser()):
        return Path(env).expanduser(), "env"
    if data_dir is not None and (managed := managed_tool(data_dir, pins)) is not None:
        return managed, "managed"
    return None


def _complete(folder: Path, pins: Pins) -> bool:
    try:
        return all((folder / f.path).stat().st_size == f.size for f in pins.base_files)
    except OSError:
        return False


def find_base(data_dir: Path | None, pins: Pins | None = None) -> tuple[Path, str] | None:
    """(the folder of the base model, where it came from): this app's own copy, or a complete
    snapshot in the Hugging Face cache (a model fetched earlier is not fetched again)."""
    pins = pins or load_pins()
    if data_dir is not None:
        own = component_root(data_dir) / "models" / pins.base_folder
        if _complete(own, pins):
            return own, "managed"
    hub = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"
    snaps = hub / ("models--" + pins.base_repo.replace("/", "--")) / "snapshots"
    with contextlib.suppress(OSError):
        for snap in sorted(snaps.iterdir()):
            if _complete(snap, pins):
                return snap, "cache"
    return None


# ---- the install ---------------------------------------------------------------------------------


@dataclass
class Progress:
    state: str = "idle"  # idle | installing | ready | failed
    step: str | None = None
    message: str = ""
    done_bytes: int = 0
    total_bytes: int = 0

    def public(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "step": self.step,
            "steps": list(STEPS),
            "message": self.message,
            "done_bytes": self.done_bytes,
            "total_bytes": self.total_bytes,
        }


Runner = Callable[[list[str], dict[str, str]], Awaitable[tuple[int, str]]]


async def run_command(args: list[str], env: dict[str, str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace")


@dataclass
class TrainingSetup:
    """What the engine holds for the trainer's component: what is there, what it would take, and
    the install."""

    data_dir: Path
    lock: Path | None = None  # the hashed requirements; None where this build has none
    uv: str | None = None
    python: str = field(default_factory=lambda: sys.executable)
    pins: Pins = field(default_factory=load_pins)
    base_url: str = HUB  # where the model's files are fetched from (a test serves its own)
    cache_dir: Path | None = None
    run: Runner = run_command
    downloads: DownloadManager = field(default_factory=DownloadManager)
    progress: Progress = field(default_factory=Progress)
    _task: asyncio.Task[None] | None = None

    # ---- what is there, and what it would take -----------------------------------------------

    @property
    def supported(self) -> bool:
        return apple_silicon()

    @property
    def root(self) -> Path:
        return component_root(self.data_dir)

    def tool(self) -> tuple[Path, str] | None:
        return find_tool(self.data_dir, self.pins)

    def base(self) -> tuple[Path, str] | None:
        return find_base(self.data_dir, self.pins)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def missing_bytes(self) -> int:
        """What an install would fetch: only the parts that are not already on this computer."""
        return (0 if self.tool() else self.pins.packages_bytes) + (
            0 if self.base() else self.pins.base_bytes
        )

    def problem(self) -> str | None:
        """Why this cannot be set up here, in words, or None."""
        if not self.supported:
            return (
                "Teaching a picture model works on a Mac with Apple silicon for now. Windows and "
                "Linux (with an NVIDIA graphics card) come later."
            )
        if self.tool() is None and (self.lock is None or not self.lock.is_file() or not self.uv):
            return "The tool that sets up the trainer is not part of this build."
        return None

    def plan(self) -> dict[str, Any]:
        p = self.pins
        tool, base = self.tool(), self.base()
        return {
            "supported": self.supported,
            "bytes": self.missing_bytes() if self.supported else 0,
            "needs_free_bytes": self.missing_bytes() + MIN_FREE_BYTES,
            "parts": [
                {
                    "name": "Trainer (mflux)", "version": p.tool_version,
                    "bytes": 0 if tool else p.packages_bytes, "have": tool is not None,
                    "licence": p.tool_licence, "source": "pypi.org",
                },
                {
                    "name": p.base_title, "version": "the picture model it learns on",
                    "bytes": 0 if base else p.base_bytes, "have": base is not None,
                    "licence": p.base_licence, "source": "huggingface.co",
                },
            ],
        }  # fmt: skip

    def state(self) -> dict[str, Any]:
        tool, base = self.tool(), self.base()
        return {
            "installed": tool is not None and base is not None,
            "tool": tool[1] if tool else None,
            "base": base[1] if base else None,
            "problem": self.problem(),
            "plan": self.plan(),
            "progress": self.progress.public(),
        }

    # ---- the install -------------------------------------------------------------------------

    def start(self, confirm_bytes: int) -> None:
        if (why := self.problem()) is not None:
            raise InstallError(why)
        if confirm_bytes != self.missing_bytes():
            raise InstallError("The size shown is out of date. Look at it again.")
        if self.running:
            raise InstallError("The trainer is already being set up.")
        if self.missing_bytes() == 0:
            raise InstallError("The trainer is already set up.")
        self.progress = Progress("installing", STEPS[0], STEP_TEXT["disk"], 0, confirm_bytes)
        self._task = asyncio.create_task(self._run())

    def cancel(self) -> bool:
        """Stop an install; what arrived of the model is kept, and a later start continues it."""
        if not self.running or self._task is None:
            return False
        self._task.cancel()
        return True

    async def wait(self) -> None:
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

    def remove(self) -> int:
        """Take the component off the computer; the bytes that came back."""
        if self.running:
            raise InstallError("The trainer is being set up. Stop it first.")
        freed = 0
        if self.root.is_dir():
            for p in self.root.rglob("*"):
                with contextlib.suppress(OSError):
                    if p.is_file() and not p.is_symlink():
                        freed += p.stat().st_size
            shutil.rmtree(self.root, ignore_errors=True)
        self.progress = Progress()
        return freed

    def _say(self, step: str, done: int | None = None) -> None:
        p = self.progress
        self.progress = Progress(
            "installing",
            step,
            STEP_TEXT[step],
            p.done_bytes if done is None else done,
            p.total_bytes,
        )

    async def _run(self) -> None:
        try:
            await self._install()
        except asyncio.CancelledError:
            self.progress = Progress(
                "failed", self.progress.step, "Stopped. Starting again continues where it stopped."
            )
        except (InstallError, DownloadError) as e:
            step = e.step if isinstance(e, InstallError) else "model"
            self.progress = Progress("failed", step or self.progress.step, str(e))
        except Exception:
            log.exception("the trainer did not set up")
            self.progress = Progress(
                "failed", self.progress.step, "Setting up the trainer did not work. Try again."
            )
        else:
            t = self.progress.total_bytes
            self.progress = Progress("ready", None, "The trainer is ready.", t, t)

    def _env(self) -> dict[str, str]:
        env = {
            k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "PYTHONHOME"))
        }
        if self.cache_dir is not None:
            env["UV_CACHE_DIR"] = str(self.cache_dir)
        return env

    async def _install(self) -> None:
        p = self.pins
        need_tool, need_base = self.tool() is None, self.base() is None
        self._say("disk", 0)
        self.root.mkdir(parents=True, exist_ok=True)
        free = await asyncio.to_thread(free_disk_bytes, self.root)
        if free < self.progress.total_bytes + MIN_FREE_BYTES:
            raise InstallError(
                "There is not enough free space: about "
                f"{(self.progress.total_bytes + MIN_FREE_BYTES) / 1e9:.0f} GB is needed and "
                f"{free / 1e9:.0f} GB is free.",
                "disk",
            )
        done = 0
        if need_tool:
            await self._install_tool()
            done = p.packages_bytes
        if need_base:
            await self._get_base(done)
        self._say("check", self.progress.total_bytes - 1)
        await self._check()
        record = {
            "schema": 1, "pins": p.digest, "tool": p.tool_version, "base": p.base_revision,
        }  # fmt: skip
        tmp = self.root / (STATE_FILE + ".part")
        tmp.write_text(json.dumps(record))
        tmp.replace(self.root / STATE_FILE)  # last: this is what makes it installed

    async def _install_tool(self) -> None:
        """The trainer's own environment from its hashed lock, through the one installer (F2)."""
        assert self.lock is not None and self.uv is not None
        (self.root / STATE_FILE).unlink(missing_ok=True)  # an old install never looks whole

        async def run(args: list[str], env: dict[str, str], _cwd: Path | None) -> tuple[int, str]:
            return await self.run(args, env)

        await installer.make_environment(
            self.uv, self.python, self.root / "venv", self.lock, None, "environment", "packages",
            run, self._env(), on_step=self._say, on_line=lambda text: log.info("%s", text[-300:]),
            owner="The trainer",
        )  # fmt: skip

    async def _get_base(self, before: int) -> None:
        """The model's files, through the resumable, hash-checked downloader."""
        p = self.pins
        entry = ModelEntry(
            p.base_id, "wasifyai-training", p.base_title, p.base_licence, "", "", 0, ()
        )
        files = []
        for f in p.base_files:
            folder = "/".join([p.base_folder, *Path(f.path).parent.parts])
            url = f"{self.base_url}/{p.base_repo}/resolve/{p.base_revision}/{f.path}"
            files.append(ModelFile(folder, Path(f.path).name, url, f.size, f.sha256))
        d = self.downloads.start(entry, files, self.root / "models")
        try:
            while d.status == "running":
                self._say("model", before + d.bytes_done)
                await asyncio.sleep(0.4)
        except asyncio.CancelledError:
            self.downloads.cancel(d.id)
            raise
        if d.status != "done":
            raise DownloadError(d.error or "The picture model could not be downloaded.")
        self._say("model", before + d.bytes_total)

    async def _check(self) -> None:
        # the record that makes it installed is written after this check: look at the folder itself
        found = self.tool()
        home = found[0] if found else self.root / "venv"
        if self.base() is None:
            raise InstallError("Some files of the picture model are missing. Try again.", "check")
        if not _tool_in(home):
            raise InstallError("The trainer was installed but could not be found.", "check")
        code, out = await self.run([str(home / "bin" / EXECUTABLE), "--help"], self._env())
        if code != 0 or "mflux-train" not in out:
            log.error("the trainer check failed: %s", out[-600:])
            raise InstallError("The trainer was installed but did not start.", "check")


# ---- the routes ----------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop/training-setup", tags=["desktop"])


def _setup(request: Request) -> TrainingSetup:
    found: TrainingSetup | None = services_of(request).training_setup
    if found is None:
        raise HTTPException(404, "not available in this deployment")
    return found


class ConfirmInstall(BaseModel):
    """What the person was shown and agreed to: the size of the download."""

    confirm_bytes: int


@router.get("")
async def setup_state(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return _setup(request).state()


@router.post("/install", status_code=202)
async def setup_install(
    body: ConfirmInstall, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    setup = _setup(request)
    try:
        setup.start(body.confirm_bytes)
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return setup.state()


@router.post("/install/cancel")
async def setup_cancel(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    setup = _setup(request)
    setup.cancel()
    return setup.state()


@router.post("/uninstall")
async def setup_uninstall(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    setup = _setup(request)
    try:
        freed = setup.remove()
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return {"freed_bytes": freed, **setup.state()}
