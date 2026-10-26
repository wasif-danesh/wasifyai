# ruff: noqa: E501  (prose in the docstrings and the sentences shown to people are easier to read on one line)
"""Setting up the video trainer (ADR-0073, video amendment): PyTorch with `diffusers` and `peft` in an
environment of its own, and the small files of the video model's repository that it needs, under
`<app data>/components/video-trainer/`. The same shape as the decision trainer's setup
(`decision_setup`): nothing is fetched before the person has seen what it is and how large, and has
agreed; the packages come from a committed hashed lock (`scripts/lock-video-trainer.sh`) and each
small file has a pinned size and SHA-256 (`video_pins.json`).

The big files, the video model and its text encoder (16 GB), are **not** fetched here: they are the
ones the Video screens already use, found where the Models screen keeps them (any models folder the
person chose). If they are not on this computer the trainer says so and where to get them.

Where the packages are already on the computer (a copy named by `WASIFYAI_VIDEO_TRAINER_DIR`) they are
used where they are and nothing is offered. PyTorch uses the graphics chip of a Mac with Apple
silicon; elsewhere the setup says so and offers nothing."""

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from wasifyai_platform_sdk import Identity

from wasifyai_api.decision_setup import _whole
from wasifyai_api.desktop_models import DownloadError
from wasifyai_api.identity import get_identity
from wasifyai_api.language_setup import ConfirmInstall
from wasifyai_api.training_setup import (
    STATE_FILE,
    InstallError,
    Pins,
    Progress,
    TrainingSetup,
    load_pins,
)

PINS_FILE = Path(__file__).with_name("video_pins.json")
LOCK_NAME = "video-requirements-aarch64-apple-darwin.lock"
COMPONENT = "video-trainer"

STEP_TEXT = {
    "disk": "Checking free space",
    "environment": "Preparing the trainer's environment",
    "packages": "Installing the trainer's packages (about 180 MB)",
    "model": "Getting the video model's settings",
    "check": "Checking that it starts",
}


def load_video_pins() -> Pins:
    return load_pins(PINS_FILE)


def component_root(data_dir: Path) -> Path:
    return data_dir / "components" / COMPONENT


def _python_in(home: Path) -> Path:
    return home / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def find_python(data_dir: Path | None, pins: Pins | None = None) -> Path | None:
    """The Python with `diffusers`: a copy named by `WASIFYAI_VIDEO_TRAINER_DIR` (development and CI), or the
    one this app installed, when it still matches the pins."""
    env = os.environ.get("WASIFYAI_VIDEO_TRAINER_DIR")
    if env and _python_in(Path(env).expanduser()).is_file():
        return _python_in(Path(env).expanduser())
    if data_dir is None:
        return None
    root, pins = component_root(data_dir), pins or load_video_pins()
    try:
        state = json.loads((root / STATE_FILE).read_text())
    except (OSError, ValueError):
        return None
    python = _python_in(root / "venv")
    if state.get("schema") == 1 and state.get("pins") == pins.digest and python.is_file():
        return python
    return None


def find_small(data_dir: Path | None, pins: Pins | None = None) -> Path | None:
    """The folder of the tokenizer and settings files: a folder named by `WASIFYAI_VIDEO_SMALL_DIR`
    (development), or this app's own copy when every file of it is whole."""
    env = os.environ.get("WASIFYAI_VIDEO_SMALL_DIR")
    if env and (Path(env).expanduser() / "tokenizer").is_dir():
        return Path(env).expanduser()
    if data_dir is None:
        return None
    p = pins or load_video_pins()
    own = component_root(data_dir) / "models" / p.base_folder
    return own if _whole(own, p.base_files) else None


@dataclass
class VideoSetup(TrainingSetup):
    """What the engine holds for the video trainer's component: the decision trainer's setup with its
    own pins, folder, tool and words, and a way to find the video model the Video screens use."""

    pins: Pins = field(default_factory=load_video_pins)
    # (the video model, its text encoder) as the Models screen keeps them, or None: set by the engine
    video_model: Callable[[], tuple[Path, Path] | None] = lambda: None  # noqa: E731
    video_model_bytes: int = 0

    @property
    def root(self) -> Path:
        return component_root(self.data_dir)

    def tool(self) -> tuple[Path, str] | None:  # type: ignore[override]
        python = find_python(self.data_dir, self.pins)
        if python is None:
            return None
        return python.parent.parent, "managed" if self.root in python.parents else "env"

    def base(self) -> tuple[Path, str] | None:  # type: ignore[override]
        found = find_small(self.data_dir, self.pins)
        if found is None:
            return None
        return found, "managed" if self.root in found.parents else "env"

    def problem(self) -> str | None:
        if not self.supported:
            return (
                "Teaching the video model works on a Mac with Apple silicon for now. Windows and "
                "Linux (with an NVIDIA graphics card) come later."
            )
        if self.tool() is None and (self.lock is None or not self.lock.is_file() or not self.uv):
            return "The tool that sets up the trainer is not part of this build."
        return None

    def plan(self) -> dict[str, Any]:
        p = self.pins
        tool, base = self.tool(), self.base()
        have_video = self.video_model() is not None
        return {
            "supported": self.supported,
            "bytes": self.missing_bytes() if self.supported else 0,
            "needs_free_bytes": self.missing_bytes() + 3 * 1024**3,
            "parts": [
                {
                    "name": "Trainer (PyTorch and diffusers)", "version": p.tool_version,
                    "bytes": 0 if tool else p.packages_bytes, "have": tool is not None,
                    "licence": p.tool_licence, "source": "pypi.org",
                },
                {
                    "name": p.base_title, "version": "a few small files",
                    "bytes": 0 if base else p.base_bytes, "have": base is not None,
                    "licence": p.base_licence, "source": "huggingface.co",
                },
            ],
            # what teaching also needs and this setup does not fetch: the video model of the Video screens
            "needs": [
                {
                    "name": "The video model (LTX-Video 2B) and its text encoder",
                    "have": have_video, "bytes": self.video_model_bytes,
                    "how": "Choose Select video model on a Video screen to get it.",
                }
            ],
        }  # fmt: skip

    def _say(self, step: str, done: int | None = None) -> None:
        p = self.progress
        self.progress = Progress(
            "installing", step, STEP_TEXT[step], p.done_bytes if done is None else done,
            p.total_bytes,
        )  # fmt: skip

    async def _check(self) -> None:
        found = self.tool()
        python = found[0] / "bin" / "python" if found else _python_in(self.root / "venv")
        if self.base() is None:
            raise InstallError(
                "Some of the video model's settings files are missing. Try again.", "check"
            )
        if not python.is_file():
            raise InstallError("The trainer was installed but could not be found.", "check")
        code, out = await self.run(
            [
                str(python),
                "-I",
                "-c",
                "import torch, diffusers, peft; print('ok', diffusers.__version__)",
            ],
            self._env(),
        )
        if code != 0 or "ok" not in out:
            raise InstallError("The trainer was installed but did not start.", "check")

    async def _get_base(self, before: int) -> None:
        try:
            await super()._get_base(before)
        except DownloadError as e:
            if "picture model" in str(e):
                raise DownloadError("The video model's settings could not be downloaded.") from None
            raise


# ---- the routes ----------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop/video-trainer-setup", tags=["desktop"])


def _setup(request: Request) -> VideoSetup:
    found: VideoSetup | None = getattr(request.app.state, "video_setup", None)
    if found is None:
        raise HTTPException(404, "not available in this deployment")
    return found


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
