"""The 3D component (ADR-0080, TD1): the pinned `pixal3d.cpp` command line (`trellis-cli`, a
Metal build), the Pixal3D single-view weights with their image encoder, and the BiRefNet cut-out
model, set up on request under `<app data>/components/model3d/`.

Nothing is fetched before the person has seen the total size and confirmed it. The binary and every
weight file have a pinned size and SHA-256 (its part of `components/manifests/<platform>.yaml`);
the weights download with the same resumable, hash-checked downloader the Models screen uses. The
licence texts the component must carry (pixal3d.cpp's MIT licence and notice, Meta's DINOv3
agreement) are written next to the files.

Layout, and what a person's own copy (`WASIFYAI_MODEL3D_HOME`, for development and CI) looks like:

    bin/trellis-cli (and its dylibs)     models/pixal3d-sv/*.gguf     models/matte/birefnet.gguf
"""

import asyncio
import json
import logging
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from wasifyai_platform_sdk import installer

from wasifyai_api.audio_runtime import InstallError, InstallProgress, platform_key
from wasifyai_api.components.manifest import legacy_digest, part_pins, pins_digest
from wasifyai_api.desktop_models import (
    DownloadError,
    DownloadManager,
    ModelEntry,
    ModelFile,
    free_disk_bytes,
)

log = logging.getLogger(__name__)

PART = "model3d"  # its pins in the component manifests
NOTICES_DIR = Path(__file__).with_name("model3d_notices")
STATE_FILE = "state.json"
MIN_FREE_BYTES = 3_000_000_000
INSTALL_LIMIT_S = 4 * 3600.0


@dataclass(frozen=True)
class WeightFile:
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Pins:
    binary_url: str
    binary_size: int
    binary_sha256: str
    binary_release: str
    cli: str
    sv_folder: str
    sv_files: tuple[WeightFile, ...]
    matte_folder: str
    matte_files: tuple[WeightFile, ...]
    platforms: tuple[str, ...]
    need_gb: float
    digest: str  # of the pins: what an install records, so a changed pin asks for a new one

    legacy: str | None = None  # what installs made before the pins moved to the manifests recorded

    def made_from(self, recorded: object) -> bool:
        """Whether an install's record was made from these pins."""
        return recorded is not None and recorded in (self.digest, self.legacy)

    @property
    def weight_bytes(self) -> int:
        return sum(f.size for f in (*self.sv_files, *self.matte_files))

    @property
    def total_bytes(self) -> int:
        return self.binary_size + self.weight_bytes


def _files(raw: list[dict[str, Any]], what: str) -> tuple[WeightFile, ...]:
    out = []
    for f in raw:
        name, url, digest = str(f["name"]), str(f["url"]), str(f["sha256"]).lower()
        if (
            not url.startswith("https://")
            or len(digest) != 64
            or "/" in name
            or name.startswith(".")
        ):
            raise ValueError(
                f"the {what} pin for {name} needs an https URL, a SHA-256 and a plain name"
            )
        out.append(WeightFile(name, url, int(f["size"]), digest))
    return tuple(out)


def load_pins(path: Path | None = None) -> Pins:
    """The 3D pins: its part in this platform's component manifest (stage F2), or a file."""
    raw = json.loads(path.read_text()) if path is not None else part_pins(PART)
    b = raw["binary"]
    if not str(b["url"]).startswith("https://") or len(str(b["sha256"])) != 64:
        raise ValueError("the 3D binary pin needs an https URL and a SHA-256")
    return Pins(
        binary_url=str(b["url"]), binary_size=int(b["size"]),
        binary_sha256=str(b["sha256"]).lower(), binary_release=str(b["release"]), cli=str(b["cli"]),
        sv_folder=str(raw["weights"]["folder"]),
        sv_files=_files(raw["weights"]["files"], "weights"),
        matte_folder=str(raw["matte"]["folder"]),
        matte_files=_files(raw["matte"]["files"], "cut-out"),
        platforms=tuple(raw["platforms"]), need_gb=float(raw["need_gb"]),
        digest=pins_digest(raw), legacy=legacy_digest(raw),
    )  # fmt: skip


@dataclass(frozen=True)
class Model3dInstall:
    root: Path
    cli: Path  # trellis-cli
    sv_dir: Path  # the Pixal3D single-view weights
    matte_dir: Path  # the cut-out model
    source: str  # managed | env


def component_root(data_dir: Path) -> Path:
    return data_dir / "components" / "model3d"


def _layout(root: Path, pins: Pins, source: str) -> Model3dInstall:
    return Model3dInstall(
        root=root,
        cli=root / "bin" / pins.cli,
        sv_dir=root / "models" / pins.sv_folder,
        matte_dir=root / "models" / pins.matte_folder,
        source=source,
    )


def _complete(found: Model3dInstall, pins: Pins) -> bool:
    """Every file is there at its pinned size (a hash was checked when it arrived)."""
    try:
        if not found.cli.is_file():
            return False
        return all(
            (d / f.name).is_file() and (d / f.name).stat().st_size == f.size
            for d, files in ((found.sv_dir, pins.sv_files), (found.matte_dir, pins.matte_files))
            for f in files
        )
    except OSError:
        return False


def find_install(data_dir: Path, pins: Pins | None = None) -> Model3dInstall | None:
    """The component this app installed, when it still matches the pins; else the copy named by
    `WASIFYAI_MODEL3D_HOME` (development and CI); None when there is none."""
    pins = pins or load_pins()
    root = component_root(data_dir)
    try:
        state = json.loads((root / STATE_FILE).read_text())
        found = _layout(root, pins, "managed")
        if (
            state.get("schema") == 1
            and pins.made_from(state.get("pins"))
            and _complete(found, pins)
        ):
            return found
    except (OSError, ValueError):
        pass
    env = os.environ.get("WASIFYAI_MODEL3D_HOME")
    if env:
        found = _layout(Path(env).expanduser(), pins, "env")
        if _complete(found, pins):
            return found
    return None


def run_env(install: Model3dInstall) -> dict[str, str]:
    """The environment `trellis-cli` runs in: nothing of the person's, a home of its own."""
    home = install.root / "home"
    home.mkdir(parents=True, exist_ok=True)
    return {"HOME": str(home), "TMPDIR": str(home), "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}


def uninstall(data_dir: Path) -> int:
    """Remove the component; the number of bytes that came back."""
    root = component_root(data_dir)
    freed = 0
    if root.is_dir():
        for p in root.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    freed += p.stat().st_size
            except OSError:
                continue
        shutil.rmtree(root, ignore_errors=True)
    return freed


def write_notices(root: Path) -> None:
    """The licence texts that travel with the files (MIT asks for them with copies; Meta's DINOv3
    agreement must accompany the encoder)."""
    target = root / "notices"
    target.mkdir(parents=True, exist_ok=True)
    for src in NOTICES_DIR.iterdir():
        if src.is_file():
            shutil.copyfile(src, target / src.name)


class Model3dInstaller:
    """Sets up the component. Nothing is fetched before the person has seen the size and confirmed
    it."""

    def __init__(
        self,
        data_dir: Path,
        pins: Pins | None = None,
        client_factory: Any = None,
        downloads: DownloadManager | None = None,
    ):
        self._data_dir = data_dir
        self._root = component_root(data_dir)
        self.pins = pins or load_pins()
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60, read=120))
        )
        self._downloads = downloads or DownloadManager(client_factory)
        self.progress = InstallProgress()
        self._task: asyncio.Task[None] | None = None
        self.run: Any = _run  # replaced in tests

    @property
    def supported(self) -> bool:
        return platform_key() in self.pins.platforms

    @property
    def total_bytes(self) -> int:
        return self.pins.total_bytes

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def plan(self) -> dict[str, Any]:
        p = self.pins
        found = find_install(self._data_dir, p)
        return {
            "supported": self.supported,
            "platform": platform_key(),
            "bytes": self.total_bytes if self.supported else 0,
            "parts": [
                {"name": "3D engine (pixal3d.cpp)", "version": p.binary_release,
                 "bytes": p.binary_size, "licence": "MIT", "source": "github.com"},
                {"name": "Pixal3D models", "version": "single view, Q8_0",
                 "bytes": sum(f.size for f in p.sv_files),
                 "licence": "MIT, and the DINOv3 licence for its image encoder (Built with DINOv3)",
                 "source": "huggingface.co"},
                {"name": "Cut-out model (BiRefNet)", "version": "Q8_0",
                 "bytes": sum(f.size for f in p.matte_files), "licence": "MIT",
                 "source": "huggingface.co"},
            ],
            "found": {"path": str(found.root)}
            if found is not None and found.source == "env"
            else None,
        }  # fmt: skip

    def start(self, confirm_bytes: int) -> None:
        if not self.supported:
            raise InstallError(
                "3D models are not available on this kind of computer yet "
                "(they were measured on Apple-silicon Macs)."
            )
        if confirm_bytes != self.total_bytes:
            raise InstallError("The download changed since it was shown. Look at it again.")
        if self.running:
            raise InstallError("The 3D component is already being set up.")
        self.progress = InstallProgress("installing", "engine", "Starting", 0, self.total_bytes)
        self._task = asyncio.create_task(self._run_install())

    def cancel(self) -> bool:
        """Stop a download in progress; what arrived is kept, and a later start continues it."""
        if not self.running or self._task is None:
            return False
        self._task.cancel()
        return True

    def _say(self, step: str, message: str, done: int | None = None) -> None:
        p = self.progress
        self.progress = InstallProgress(
            "installing", step, message, p.done_bytes if done is None else done, p.total_bytes
        )

    async def _run_install(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix="stage-", dir=self._root))
        try:
            await asyncio.wait_for(self._install(stage), INSTALL_LIMIT_S)
            self.progress = InstallProgress(
                "ready", None, "Ready", self.total_bytes, self.total_bytes
            )
        except asyncio.CancelledError:
            self.progress = InstallProgress(
                "failed", self.progress.step, "Stopped. Starting again continues where it stopped."
            )
        except (InstallError, DownloadError) as e:
            self.progress = InstallProgress("failed", self.progress.step, str(e))
        except Exception:
            log.exception("the 3D component did not install")
            self.progress = InstallProgress(
                "failed", self.progress.step, "The 3D component could not be set up. Try again."
            )
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    async def _fetch_binary(self, to: Path) -> None:
        """Through the one installer (stage F2): size and SHA-256 checked, else nothing kept."""
        p = self.pins
        self._say("engine", "Getting the 3D engine", 0)
        await installer.download(
            installer.Archive(p.binary_url, p.binary_size, p.binary_sha256, "tar.gz"), to,
            "engine", lambda done, _: self._say("engine", "Getting the 3D engine", done),
            client=self._client_factory,
        )  # fmt: skip

    async def _install(self, stage: Path) -> None:
        p = self.pins
        free = await asyncio.to_thread(free_disk_bytes, self._root)
        if free < self.total_bytes + MIN_FREE_BYTES:
            raise InstallError(
                f"There is not enough free disk space: about {self.total_bytes / 1e9:.0f} GB is "
                f"needed and {free / 1e9:.0f} GB is free."
            )
        archive = stage / "engine.tar.gz"
        await self._fetch_binary(archive)
        unpacked = stage / "engine"
        await asyncio.to_thread(installer.unpack, archive, "tar.gz", 0, unpacked, "engine")
        found_cli = next(iter(unpacked.rglob(p.cli)), None)
        if found_cli is None:
            raise InstallError("The 3D engine download did not contain the engine.")
        bin_dir = self._root / "bin"
        shutil.rmtree(bin_dir, ignore_errors=True)
        (self._root / STATE_FILE).unlink(missing_ok=True)  # an old install never looks whole
        shutil.copytree(found_cli.parent, bin_dir)
        for tool in bin_dir.iterdir():
            if tool.is_file() and not tool.suffix:
                tool.chmod(tool.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        # a file fetched here carries no quarantine flag, but clear one if it is there
        await self.run(["/usr/bin/xattr", "-dr", "com.apple.quarantine", str(bin_dir)],
                       self._root, {}, 60)  # fmt: skip
        await asyncio.to_thread(write_notices, self._root)

        entry = ModelEntry("model3d", "wasifyai-model3d", "3D", "", "", "", 0, ())
        models = self._root / "models"
        for folder, files in ((p.sv_folder, p.sv_files), (p.matte_folder, p.matte_files)):
            mf = [ModelFile(folder, f.name, f.url, f.size, f.sha256) for f in files]
            await self._download(entry, mf, models)

        self._say("verify", "Checking that it starts", self.total_bytes - 1)
        install = _layout(self._root, p, "managed")
        if not _complete(install, p):
            raise InstallError("Some files of the 3D component are missing. Try again.")
        ok, text = await self.run([str(install.cli), "--help"], self._root, run_env(install), 60)
        if not ok or "trellis-cli" not in text:
            log.error("the 3D engine check failed: %s", text[-600:])
            raise InstallError("The 3D engine did not start on this computer.")
        record = {"schema": 1, "pins": p.digest, "release": p.binary_release}
        tmp = self._root / (STATE_FILE + ".part")
        tmp.write_text(json.dumps(record))
        tmp.replace(self._root / STATE_FILE)  # last: this is what makes it installed

    async def _download(self, entry: ModelEntry, files: list[ModelFile], models: Path) -> None:
        """One group of files, through the resumable downloader; its bytes are added to ours."""
        base = self.progress.done_bytes
        d = self._downloads.start(entry, files, models)
        try:
            while d.status == "running":
                self._say("models", f"Getting {d.current or 'the models'}", base + d.bytes_done)
                await asyncio.sleep(0.4)
        except asyncio.CancelledError:
            self._downloads.cancel(d.id)
            raise
        if d.status != "done":
            raise DownloadError(d.error or "The models could not be downloaded.")
        self._say("models", "Models downloaded", base + d.bytes_total)


async def _run(
    args: list[str], cwd: Path, env: dict[str, str], limit_s: float = 600
) -> tuple[bool, str]:
    """Run one command; (it exited 0, what it printed). Never raises for a command that fails."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd), env=env or None,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )  # fmt: skip
        out, _ = await asyncio.wait_for(proc.communicate(), limit_s)
    except (TimeoutError, OSError) as e:
        return False, str(e)
    return proc.returncode == 0, out.decode(errors="replace")


__all__ = [
    "Model3dInstall", "Model3dInstaller", "Pins", "WeightFile", "component_root", "find_install",
    "load_pins", "run_env", "uninstall",
]  # fmt: skip
