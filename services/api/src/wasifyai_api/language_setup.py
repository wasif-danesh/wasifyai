"""Setting up the writing trainer (ADR-0074): mlx-lm in an environment of its own, and the small
model it teaches, under `<app data>/components/language-trainer/`. The same shape as the picture
trainer's setup (`training_setup`): nothing is fetched before the person has seen what it is and
how large, and has agreed; the packages come from a committed hashed lock
(`scripts/lock-language-trainer.sh`) and the model's files each have a pinned size and SHA-256
(its part of `components/manifests/<platform>.yaml`).

Where mlx-lm and the model are already on the computer (a copy named by `WASIFYAI_MLXLM_DIR`, a
models folder named by `WASIFYAI_LANGUAGE_BASE_DIR`) they are used where they are and nothing is
offered.
mlx-lm runs on MLX: Apple silicon only. Elsewhere the setup says so and offers nothing."""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity

from wasifyai_api.components.manifest import part_pins
from wasifyai_api.desktop_models import DownloadError, ModelEntry, ModelFile, free_disk_bytes
from wasifyai_api.identity import get_identity
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

PART = "trainer-writing"  # its pins in the component manifests
LOCK_NAME = "language-requirements-aarch64-apple-darwin.lock"
COMPONENT = "language-trainer"

STEP_TEXT = {
    "disk": "Checking free space",
    "environment": "Preparing the trainer's environment",
    "packages": "Installing the trainer's packages (about 65 MB)",
    "model": "Getting the writing model",
    "check": "Checking that it starts",
}


def load_language_pins() -> Pins:
    return load_pins(part=PART)


@dataclass(frozen=True)
class ChatPins:
    """The model in the form the chat engine (llama.cpp) runs: a GGUF file of the same base, so a
    taught adapter can be served on top of it. Kept apart from the trainer's pins so that asking
    for it later does not make the installed trainer look out of date."""

    id: str
    title: str
    repo: str
    revision: str
    file: str
    size: int
    sha256: str
    source: str
    folder: str


def load_chat_pins(path: Path | None = None) -> ChatPins:
    raw = json.loads(path.read_text()) if path is not None else part_pins(PART, "chat")
    if len(str(raw["sha256"])) != 64 or "/" in raw["file"] or ".." in raw["file"]:
        raise ValueError("the pin of the chat copy needs a plain file name and a SHA-256")
    return ChatPins(
        id=raw["id"], title=raw["title"], repo=raw["repo"], revision=raw["revision"],
        file=raw["file"], size=int(raw["size"]), sha256=str(raw["sha256"]).lower(),
        source=raw["source"], folder=raw["folder"],
    )  # fmt: skip


@dataclass(frozen=True)
class BaseSpec:
    """One base model a writing model can be taught on: the MLX weights it is taught from and the
    GGUF copy chat serves it from. The first (the one the trainer is installed with) is `main`."""

    id: str
    title: str
    repo: str
    revision: str
    source: str
    folder: str
    files: tuple[BaseFile, ...]
    chat: ChatPins
    main: bool = False

    @property
    def train_bytes(self) -> int:
        return sum(f.size for f in self.files)


def _chat_pins(raw: dict[str, Any]) -> ChatPins:
    if len(str(raw["sha256"])) != 64 or "/" in raw["file"] or ".." in raw["file"]:
        raise ValueError("the pin of a chat copy needs a plain file name and a SHA-256")
    return ChatPins(
        id=raw["id"], title=raw["title"], repo=raw["repo"], revision=raw["revision"],
        file=raw["file"], size=int(raw["size"]), sha256=str(raw["sha256"]).lower(),
        source=raw["source"], folder=raw["folder"],
    )  # fmt: skip


def load_more_bases(path: Path | None = None) -> list[BaseSpec]:
    raw = json.loads(path.read_text()) if path is not None else part_pins(PART, "more_bases")
    out = []
    for b in raw["bases"]:
        files = []
        for f in b["files"]:
            parts = Path(f["path"]).parts
            if ".." in parts or Path(f["path"]).is_absolute() or len(str(f["sha256"])) != 64:
                raise ValueError(f"the pin for {f['path']} needs a relative path and a SHA-256")
            files.append(BaseFile(f["path"], int(f["size"]), str(f["sha256"]).lower()))
        out.append(
            BaseSpec(
                id=b["id"],
                title=b["title"],
                repo=b["repo"],
                revision=b["revision"],
                source=b["source"],
                folder=b["folder"],
                files=tuple(files),
                chat=_chat_pins(b["chat"]),
            )  # fmt: skip
        )
    return out


def main_spec(pins: Pins | None = None, chat: ChatPins | None = None) -> BaseSpec:
    p = pins or load_language_pins()
    return BaseSpec(
        id=p.base_id, title=p.base_title, repo=p.base_repo, revision=p.base_revision,
        source="huggingface.co", folder=p.base_folder,
        files=p.base_files, chat=chat or load_chat_pins(), main=True,
    )  # fmt: skip


def catalogue() -> list[BaseSpec]:
    """Every base a writing model can be taught on, the main one first."""
    return [main_spec(), *load_more_bases()]


def spec_of(
    base_id: str, pins: Pins | None = None, chat: ChatPins | None = None
) -> BaseSpec | None:
    main = main_spec(pins, chat)
    if base_id == main.id:
        return main
    return next((b for b in load_more_bases() if b.id == base_id), None)


def find_chat_copy(
    data_dir: Path | None, pins: ChatPins | None = None, base_id: str | None = None
) -> Path | None:
    """The chat form of a base model: a file named by `WASIFYAI_LANGUAGE_CHAT_COPY` (development;
    only for the main base), or this app's own copy when it is whole (the pinned size)."""
    main = base_id is None or base_id == load_language_pins().base_id
    env = os.environ.get("WASIFYAI_LANGUAGE_CHAT_COPY")
    if main and env and Path(env).expanduser().is_file():
        return Path(env).expanduser()
    if data_dir is None:
        return None
    if pins is None:
        found = spec_of(base_id) if base_id else main_spec()
        if found is None:
            return None
        pins = found.chat
    own = component_root(data_dir) / "chat" / pins.folder / pins.file
    try:
        return own if own.stat().st_size == pins.size else None
    except OSError:
        return None


def component_root(data_dir: Path) -> Path:
    return data_dir / "components" / COMPONENT


def _python_in(home: Path) -> Path:
    return home / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def managed_python(data_dir: Path, pins: Pins) -> Path | None:
    """The environment this app installed, when it still matches the pins."""
    root = component_root(data_dir)
    try:
        state = json.loads((root / STATE_FILE).read_text())
    except (OSError, ValueError):
        return None
    python = _python_in(root / "venv")
    if state.get("schema") == 1 and pins.made_from(state.get("pins")) and python.is_file():
        return python
    return None


def find_python(data_dir: Path | None, pins: Pins | None = None) -> Path | None:
    """The Python with `mlx_lm`: a copy named by `WASIFYAI_MLXLM_DIR` (development and CI), or the
    one this app installed."""
    env = os.environ.get("WASIFYAI_MLXLM_DIR")
    if env and _python_in(Path(env).expanduser()).is_file():
        return _python_in(Path(env).expanduser())
    if data_dir is not None:
        return managed_python(data_dir, pins or load_language_pins())
    return None


def _whole(folder: Path, files: tuple[BaseFile, ...]) -> bool:
    try:
        return all((folder / f.path).stat().st_size == f.size for f in files)
    except OSError:
        return False


def find_model(
    data_dir: Path | None, base_id: str, pins: Pins | None = None, spec: BaseSpec | None = None
) -> Path | None:
    """The folder of a base model in MLX format (`config.json` and the weights): a models folder
    named by `WASIFYAI_LANGUAGE_BASE_DIR` as `<dir>/<id>` (development), or this app's own copy
    when every file of it is whole."""
    env = os.environ.get("WASIFYAI_LANGUAGE_BASE_DIR")
    if env and (Path(env).expanduser() / base_id / "config.json").is_file():
        return Path(env).expanduser() / base_id
    if data_dir is not None:
        spec = spec or spec_of(base_id, pins)
        if spec is not None:
            own = component_root(data_dir) / "models" / spec.folder
            if _whole(own, spec.files):
                return own
    return None


@dataclass
class LanguageSetup(TrainingSetup):
    """What the engine holds for the writing trainer's component, the picture trainer's setup with
    its own pins, folder, tool and words."""

    pins: Pins = field(default_factory=load_language_pins)
    chat_pins: ChatPins = field(default_factory=load_chat_pins)
    # the other models, on request: what is being fetched, by (base id, "model" or "chat")
    bases: list[BaseSpec] | None = None
    parts: dict[tuple[str, str], Progress] = field(default_factory=dict)
    _fetches: dict[tuple[str, str], asyncio.Task[None]] = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return component_root(self.data_dir)

    def tool(self) -> tuple[Path, str] | None:  # type: ignore[override]
        python = find_python(self.data_dir, self.pins)
        if python is None:
            return None
        return python.parent.parent, "managed" if self.root in python.parents else "env"

    def base(self) -> tuple[Path, str] | None:  # type: ignore[override]
        found = find_model(self.data_dir, self.pins.base_id, self.pins)
        if found is None:
            return None
        return found, "managed" if self.root in found.parents else "env"

    def problem(self) -> str | None:
        if not self.supported:
            return (
                "Teaching a writing model works on a Mac with Apple silicon for now. Windows and "
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
            "needs_free_bytes": self.missing_bytes() + 1024**3,
            "parts": [
                {
                    "name": "Trainer (mlx-lm)", "version": p.tool_version,
                    "bytes": 0 if tool else p.packages_bytes, "have": tool is not None,
                    "source": "pypi.org",
                },
                {
                    "name": p.base_title, "version": "the writing model it learns on",
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
            raise InstallError("Some files of the writing model are missing. Try again.", "check")
        if not python.is_file():
            raise InstallError("The trainer was installed but could not be found.", "check")
        code, out = await self.run(
            [str(python), "-I", "-c", "import mlx_lm; print('mlx_lm', mlx_lm.__version__)"],
            self._env(),
        )
        if code != 0 or "mlx_lm" not in out:
            raise InstallError("The trainer was installed but did not start.", "check")

    # ---- the other models: asked for when one is chosen, and the chat copy when it is used in chat

    def catalogue(self) -> list[BaseSpec]:
        """The main base (with this setup's own pins) and the others."""
        if self.bases is not None:
            return self.bases
        return [main_spec(self.pins, self.chat_pins), *load_more_bases()]

    def spec(self, base_id: str | None = None) -> BaseSpec | None:
        found = self.catalogue()
        return found[0] if base_id is None else next((b for b in found if b.id == base_id), None)

    def chat_copy(self, base_id: str | None = None) -> Path | None:
        spec = self.spec(base_id)
        if spec is None:
            return None
        return find_chat_copy(self.data_dir, spec.chat, spec.id if not spec.main else None)

    def has_model(self, spec: BaseSpec) -> bool:
        if spec.main:
            return self.base() is not None
        return find_model(self.data_dir, spec.id, self.pins, spec) is not None

    def part_bytes(self, spec: BaseSpec, part: str) -> int:
        """What fetching this part would take: nothing when it is there."""
        if part == "chat":
            return 0 if self.chat_copy(spec.id) is not None else spec.chat.size
        return 0 if self.has_model(spec) else spec.train_bytes

    def fetching(self, base_id: str, part: str) -> bool:
        task = self._fetches.get((base_id, part))
        return task is not None and not task.done()

    def bases_state(self) -> list[dict[str, Any]]:
        """Every base a writing model can be taught on, and for each what is on this computer
        and what getting the rest would cost: the screen's list."""
        out = []
        for spec in self.catalogue():
            row: dict[str, Any] = {
                "id": spec.id,
                "title": spec.title,
                "source": spec.source,
                "main": spec.main,
                "problem": self.problem() if not self.supported else None,
            }
            for part, title in (("model", spec.title), ("chat", spec.chat.title)):
                pr = self.parts.get((spec.id, part), Progress())
                have = self.part_bytes(spec, part) == 0
                size = spec.train_bytes if part == "model" else spec.chat.size
                row[part] = {
                    "have": have, "bytes": 0 if have else size, "title": title,
                    "needs_free_bytes": 0 if have else size + 1024**3,
                    "progress": {"state": pr.state, "message": pr.message,
                                 "done_bytes": pr.done_bytes, "total_bytes": pr.total_bytes},
                }  # fmt: skip
            out.append(row)
        return out

    def fetch_start(self, base_id: str, part: str, confirm_bytes: int) -> None:
        if not self.supported:
            raise InstallError(self.problem() or "This computer cannot do that.")
        spec = self.spec(base_id)
        if spec is None or part not in ("model", "chat"):
            raise InstallError("That model is not one the app can teach.")
        if part == "model" and spec.main:
            raise InstallError("This model is set up with the trainer.")
        if self.part_bytes(spec, part) == 0:
            raise InstallError("That is already on this computer.")
        size = spec.chat.size if part == "chat" else spec.train_bytes
        if confirm_bytes != size:
            raise InstallError("The size shown is out of date. Look at it again.")
        if self.fetching(base_id, part):
            raise InstallError("It is already being downloaded.")
        self.parts[(base_id, part)] = Progress("installing", "model", "Downloading", 0, size)
        self._fetches[(base_id, part)] = asyncio.create_task(self._fetch(spec, part))

    def fetch_cancel(self, base_id: str, part: str) -> bool:
        task = self._fetches.get((base_id, part))
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def fetch_wait(self) -> None:
        if self._fetches:
            await asyncio.gather(*self._fetches.values(), return_exceptions=True)

    async def _fetch(self, spec: BaseSpec, part: str) -> None:
        key = (spec.id, part)
        if part == "chat":
            c = spec.chat
            entry = ModelEntry(c.id, "wasifyai-training", c.title, "", "", 0, ())
            files = [
                ModelFile(
                    c.folder,
                    c.file,
                    f"{self.base_url}/{c.repo}/resolve/{c.revision}/{c.file}",
                    c.size,
                    c.sha256,
                )
            ]
            target, size, say = self.root / "chat", c.size, "Getting the model for chat"
        else:
            entry = ModelEntry(spec.id, "wasifyai-training", spec.title, "", "", 0, ())
            files = [
                ModelFile(
                    "/".join([spec.folder, *Path(f.path).parent.parts]),
                    Path(f.path).name,
                    f"{self.base_url}/{spec.repo}/resolve/{spec.revision}/{f.path}",
                    f.size,
                    f.sha256,
                )
                for f in spec.files
            ]
            target, size, say = self.root / "models", spec.train_bytes, "Getting the writing model"
        try:
            free = await asyncio.to_thread(free_disk_bytes, self.data_dir)
            if free < size + 1024**3:
                raise InstallError(
                    f"There is not enough free space: about {(size + 1024**3) / 1e9:.1f} GB is "
                    f"needed and {free / 1e9:.1f} GB is free.",
                    "disk",
                )
            d = self.downloads.start(entry, files, target)
            try:
                while d.status == "running":
                    self.parts[key] = Progress("installing", "model", say, d.bytes_done, size)
                    await asyncio.sleep(0.4)
            except asyncio.CancelledError:
                self.downloads.cancel(d.id)
                raise
            if d.status != "done":
                raise DownloadError(d.error or "The model could not be downloaded.")
        except asyncio.CancelledError:
            self.parts[key] = Progress(
                "failed", "model", "Stopped. Starting again continues where it stopped."
            )
        except (InstallError, DownloadError) as e:
            self.parts[key] = Progress("failed", "model", str(e))
        except Exception:
            self.parts[key] = Progress("failed", "model", "The download did not work. Try again.")
        else:
            self.parts[key] = Progress("ready", None, "Ready.", size, size)

    async def _get_base(self, before: int) -> None:
        try:
            await super()._get_base(before)
        except DownloadError as e:
            if "picture model" in str(e):
                raise DownloadError("The writing model could not be downloaded.") from None
            raise


# ---- the routes ----------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop/language-setup", tags=["desktop"])


def _setup(request: Request) -> LanguageSetup:
    found: LanguageSetup | None = services_of(request).language_setup
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


@router.get("/bases")
async def bases_state(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return {"bases": _setup(request).bases_state()}


@router.post("/bases/{base_id}/{part}/install", status_code=202)
async def base_install(
    base_id: str, part: str, body: ConfirmInstall, request: Request,
    _: Identity = Depends(get_identity),
) -> dict[str, Any]:  # fmt: skip
    setup = _setup(request)
    try:
        setup.fetch_start(base_id, part, body.confirm_bytes)
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return {"bases": setup.bases_state()}


@router.post("/bases/{base_id}/{part}/cancel")
async def base_cancel(
    base_id: str, part: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    setup = _setup(request)
    setup.fetch_cancel(base_id, part)
    return {"bases": setup.bases_state()}


@router.post("/uninstall")
async def setup_uninstall(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    setup = _setup(request)
    try:
        freed = setup.remove()
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return {"freed_bytes": freed, **setup.state()}
