# ruff: noqa: E501  (prose in the docstrings and a script in a string are easier to read on one line)
"""Setting up the decision trainer (ADR-0075): Laya and PyTorch in an environment of their own, and the
model it teaches, under `<app data>/components/decision-trainer/`. The same shape as the writing
trainer's setup (`language_setup`): nothing is fetched before the person has seen what it is and how
large, and has agreed; the packages come from a committed hashed lock
(`scripts/lock-decision-trainer.sh`) and each model file has a pinned size and SHA-256
(its part of `components/manifests/<platform>.yaml`). The English model comes with the trainer; the model for many languages is
fetched when it is chosen.

Where Laya and the model are already on the computer (a copy named by `WASIFYAI_LAYA_DIR`, a models
folder named by `WASIFYAI_DECISION_BASE_DIR`) they are used where they are and nothing is offered.
PyTorch uses the graphics chip of a Mac with Apple silicon; elsewhere the setup says so and offers
nothing."""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from wasifyai_platform_sdk import Identity

from wasifyai_api.components.manifest import part_pins
from wasifyai_api.desktop_models import DownloadError, ModelEntry, ModelFile, free_disk_bytes
from wasifyai_api.identity import get_identity
from wasifyai_api.language_setup import ConfirmInstall
from wasifyai_api.services import services_of
from wasifyai_api.training_setup import (
    STATE_FILE,
    BaseFile,
    InstallError,
    Pins,
    Progress,
    TrainingSetup,
    load_pins,
)

PART = "trainer-deciding"  # its pins in the component manifests
LOCK_NAME = "decision-requirements-aarch64-apple-darwin.lock"
COMPONENT = "decision-trainer"

STEP_TEXT = {
    "disk": "Checking free space",
    "environment": "Preparing the trainer's environment",
    "packages": "Installing the trainer's packages (about 170 MB)",
    "model": "Getting the model",
    "check": "Checking that it starts",
}


def load_decision_pins() -> Pins:
    return load_pins(part=PART)


@dataclass(frozen=True)
class BaseSpec:
    """One model a decision model can be taught on. The first (the one the trainer is installed
    with) is `main`."""

    id: str
    title: str
    repo: str
    revision: str
    folder: str
    files: tuple[BaseFile, ...]
    subfolder: str = ""  # where the files are in the repository
    main: bool = False

    @property
    def bytes(self) -> int:
        return sum(f.size for f in self.files)


def _files(raw: list[dict[str, Any]]) -> tuple[BaseFile, ...]:
    out = []
    for f in raw:
        parts = Path(f["path"]).parts
        if ".." in parts or Path(f["path"]).is_absolute() or len(str(f["sha256"])) != 64:
            raise ValueError(f"the pin for {f['path']} needs a relative path and a SHA-256")
        out.append(BaseFile(f["path"], int(f["size"]), str(f["sha256"]).lower()))
    return tuple(out)


def catalogue(pins: Pins | None = None, path: Path | None = None) -> list[BaseSpec]:
    """Every model a decision model can be taught on, the main one first."""
    p = pins or (load_pins(path) if path is not None else load_decision_pins())
    raw = json.loads(path.read_text()) if path is not None else part_pins(PART)
    main = BaseSpec(
        p.base_id, p.base_title, p.base_repo, p.base_revision, p.base_folder,
        p.base_files, main=True,
    )  # fmt: skip
    more = [
        BaseSpec(
            b["id"], b["title"], b["repo"], b["revision"], b["folder"],
            _files(b["files"]), subfolder=b.get("subfolder", ""),
        )
        for b in raw.get("more", [])
    ]  # fmt: skip
    return [main, *more]


def component_root(data_dir: Path) -> Path:
    return data_dir / "components" / COMPONENT


def _python_in(home: Path) -> Path:
    return home / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def find_python(data_dir: Path | None, pins: Pins | None = None) -> Path | None:
    """The Python with `laya`: a copy named by `WASIFYAI_LAYA_DIR` (development and CI), or the one
    this app installed, when it still matches the pins."""
    env = os.environ.get("WASIFYAI_LAYA_DIR")
    if env and _python_in(Path(env).expanduser()).is_file():
        return _python_in(Path(env).expanduser())
    if data_dir is None:
        return None
    root, pins = component_root(data_dir), pins or load_decision_pins()
    try:
        state = json.loads((root / STATE_FILE).read_text())
    except (OSError, ValueError):
        return None
    python = _python_in(root / "venv")
    if state.get("schema") == 1 and pins.made_from(state.get("pins")) and python.is_file():
        return python
    return None


def _whole(folder: Path, files: tuple[BaseFile, ...]) -> bool:
    try:
        return all((folder / f.path).stat().st_size == f.size for f in files)
    except OSError:
        return False


def find_model(data_dir: Path | None, base_id: str, spec: BaseSpec | None = None) -> Path | None:
    """The folder of a model (`rl_agent_config.json`, `model.safetensors`, `tokenizer`, `encoder`): a
    models folder named by `WASIFYAI_DECISION_BASE_DIR` as `<dir>/<id>` (development), or this app's
    own copy when every file of it is whole."""
    env = os.environ.get("WASIFYAI_DECISION_BASE_DIR")
    if env and (Path(env).expanduser() / base_id / "rl_agent_config.json").is_file():
        return Path(env).expanduser() / base_id
    if data_dir is not None:
        found = spec or next((b for b in catalogue() if b.id == base_id), None)
        if found is not None:
            own = component_root(data_dir) / "models" / found.folder
            if _whole(own, found.files):
                return own
    return None


@dataclass
class DecisionSetup(TrainingSetup):
    """What the engine holds for the decision trainer's component: the writing trainer's setup with
    its own pins, folder, tool and words."""

    pins: Pins = field(default_factory=load_decision_pins)
    pins_file: Path | None = None  # a file in place of the manifest's pins (tests)
    # the other models, on request: what is being fetched, by base id
    parts: dict[str, Progress] = field(default_factory=dict)
    _fetches: dict[str, asyncio.Task[None]] = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return component_root(self.data_dir)

    def tool(self) -> tuple[Path, str] | None:  # type: ignore[override]
        python = find_python(self.data_dir, self.pins)
        if python is None:
            return None
        return python.parent.parent, "managed" if self.root in python.parents else "env"

    def base(self) -> tuple[Path, str] | None:  # type: ignore[override]
        found = find_model(self.data_dir, self.pins.base_id, self.catalogue()[0])
        if found is None:
            return None
        return found, "managed" if self.root in found.parents else "env"

    def problem(self) -> str | None:
        if not self.supported:
            return (
                "Teaching it to decide works on a Mac with Apple silicon for now. Windows and "
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
            "needs_free_bytes": self.missing_bytes() + 3 * 1024**3,
            "parts": [
                {
                    "name": "Trainer (Laya and PyTorch)", "version": p.tool_version,
                    "bytes": 0 if tool else p.packages_bytes, "have": tool is not None,
                    "source": "pypi.org",
                },
                {
                    "name": p.base_title, "version": "the model it learns on",
                    "bytes": 0 if base else p.base_bytes, "have": base is not None,
                    "source": "huggingface.co",
                },
            ],
        }  # fmt: skip

    def _say(self, step: str, done: int | None = None) -> None:
        p = self.progress
        self.progress = Progress(
            "installing", step, STEP_TEXT[step], p.done_bytes if done is None else done,
            p.total_bytes,
        )  # fmt: skip

    async def _check(self) -> None:
        # the record that makes it installed is written after this check: look at the folder itself
        found = self.tool()
        python = found[0] / "bin" / "python" if found else _python_in(self.root / "venv")
        if self.base() is None:
            raise InstallError("Some files of the model are missing. Try again.", "check")
        if not python.is_file():
            raise InstallError("The trainer was installed but could not be found.", "check")
        code, out = await self.run(
            [str(python), "-I", "-c", "import laya, torch; print('laya', laya.__version__)"],
            self._env(),
        )
        if code != 0 or "laya" not in out:
            raise InstallError("The trainer was installed but did not start.", "check")

    async def _get_base(self, before: int) -> None:
        try:
            await super()._get_base(before)
        except DownloadError as e:
            if "picture model" in str(e):
                raise DownloadError("The model could not be downloaded.") from None
            raise

    # ---- the other models, asked for when one is chosen ----------------------------------------

    def catalogue(self) -> list[BaseSpec]:
        return catalogue(self.pins, self.pins_file)

    def spec(self, base_id: str | None = None) -> BaseSpec | None:
        found = self.catalogue()
        return found[0] if base_id is None else next((b for b in found if b.id == base_id), None)

    def has_model(self, spec: BaseSpec) -> bool:
        if spec.main:
            return self.base() is not None
        return find_model(self.data_dir, spec.id, spec) is not None

    def fetching(self, base_id: str) -> bool:
        task = self._fetches.get(base_id)
        return task is not None and not task.done()

    def bases_state(self) -> list[dict[str, Any]]:
        """Every model a decision model can be taught on, and for each what is on this computer and
        what getting it would cost: the screen's list."""
        out = []
        for spec in self.catalogue():
            have = self.has_model(spec)
            pr = self.parts.get(spec.id, Progress())
            out.append(
                {
                    "id": spec.id, "title": spec.title,
                    "source": "huggingface.co", "main": spec.main,
                    "problem": self.problem() if not self.supported else None,
                    "model": {
                        "have": have, "bytes": 0 if have else spec.bytes, "title": spec.title,
                        "needs_free_bytes": 0 if have else spec.bytes + 1024**3,
                        "progress": {"state": pr.state, "message": pr.message,
                                     "done_bytes": pr.done_bytes, "total_bytes": pr.total_bytes},
                    },
                }
            )  # fmt: skip
        return out

    def fetch_start(self, base_id: str, confirm_bytes: int) -> None:
        if not self.supported:
            raise InstallError(self.problem() or "This computer cannot do that.")
        spec = self.spec(base_id)
        if spec is None:
            raise InstallError("That model is not one the app can teach.")
        if spec.main:
            raise InstallError("This model is set up with the trainer.")
        if self.has_model(spec):
            raise InstallError("That is already on this computer.")
        if confirm_bytes != spec.bytes:
            raise InstallError("The size shown is out of date. Look at it again.")
        if self.fetching(base_id):
            raise InstallError("It is already being downloaded.")
        self.parts[base_id] = Progress("installing", "model", "Downloading", 0, spec.bytes)
        self._fetches[base_id] = asyncio.create_task(self._fetch(spec))

    def fetch_cancel(self, base_id: str) -> bool:
        task = self._fetches.get(base_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def fetch_wait(self) -> None:
        if self._fetches:
            await asyncio.gather(*self._fetches.values(), return_exceptions=True)

    async def _fetch(self, spec: BaseSpec) -> None:
        entry = ModelEntry(spec.id, "wasifyai-training", spec.title, "", "", 0, ())
        prefix = f"{spec.subfolder}/" if spec.subfolder else ""
        files = [
            ModelFile(
                "/".join([spec.folder, *Path(f.path).parent.parts]),
                Path(f.path).name,
                f"{self.base_url}/{spec.repo}/resolve/{spec.revision}/{prefix}{f.path}",
                f.size,
                f.sha256,
            )
            for f in spec.files
        ]  # fmt: skip
        try:
            free = await asyncio.to_thread(free_disk_bytes, self.data_dir)
            if free < spec.bytes + 1024**3:
                raise InstallError(
                    f"There is not enough free space: about {(spec.bytes + 1024**3) / 1e9:.1f} GB "
                    f"is needed and {free / 1e9:.1f} GB is free.",
                    "disk",
                )
            d = self.downloads.start(entry, files, self.root / "models")
            try:
                while d.status == "running":
                    self.parts[spec.id] = Progress(
                        "installing", "model", "Getting the model", d.bytes_done, spec.bytes
                    )
                    await asyncio.sleep(0.4)
            except asyncio.CancelledError:
                self.downloads.cancel(d.id)
                raise
            if d.status != "done":
                raise DownloadError(d.error or "The model could not be downloaded.")
        except asyncio.CancelledError:
            self.parts[spec.id] = Progress(
                "failed", "model", "Stopped. Starting again continues where it stopped."
            )
        except (InstallError, DownloadError) as e:
            self.parts[spec.id] = Progress("failed", "model", str(e))
        except Exception:
            self.parts[spec.id] = Progress(
                "failed", "model", "The download did not work. Try again."
            )
        else:
            self.parts[spec.id] = Progress("ready", None, "Ready.", spec.bytes, spec.bytes)


# ---- the routes ----------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop/decision-setup", tags=["desktop"])


def _setup(request: Request) -> DecisionSetup:
    found: DecisionSetup | None = services_of(request).decision_setup
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


@router.get("/bases")
async def bases_state(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return {"bases": _setup(request).bases_state()}


@router.post("/bases/{base_id}/install", status_code=202)
async def base_install(
    base_id: str, body: ConfirmInstall, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    setup = _setup(request)
    try:
        setup.fetch_start(base_id, body.confirm_bytes)
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return {"bases": setup.bases_state()}


@router.post("/bases/{base_id}/cancel")
async def base_cancel(
    base_id: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    setup = _setup(request)
    setup.fetch_cancel(base_id)
    return {"bases": setup.bases_state()}


@router.post("/uninstall")
async def setup_uninstall(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    setup = _setup(request)
    try:
        freed = setup.remove()
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return {"freed_bytes": freed, **setup.state()}
