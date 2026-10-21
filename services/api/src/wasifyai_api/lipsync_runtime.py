"""The lip sync engine of the desktop (ADR-0066, stage V5): MuseTalk as an optional sidecar.

    MuseTalkInstaller   the pinned source and a hashed package lock, set up with the app's own `uv`
                        in an environment of its own (torch must not touch the engine's packages)
    LipSyncSidecar      one `uvicorn` process running the lip sync server (`lipsync_server/`), on
                        loopback, started on demand and stopped to give the memory back

The weights are catalogue entries (`musetalk-v15` in the voice product's `models.yaml`), fetched in
Models after the person has seen their size; the sidecar lays them out the way MuseTalk reads them
when it starts. A copy set up by hand (`WASIFYAI_MUSETALK_HOME`, with `src/` and `venv/`) is used as
it is, for development.

Every video carries a visible mark and a metadata note; the mark is drawn by the server on each
frame and cannot be switched off from here (ADR-0044)."""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import shutil
import socket
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from wasifyai_platform_sdk import LipSyncRequest, LipSyncResult, VoiceEngineError, VoiceModel

from wasifyai_api.audio_runtime import InstallError, InstallProgress, platform_key

log = logging.getLogger(__name__)

PINS_FILE = Path(__file__).with_name("musetalk_pins.json")
SERVER_DIR = Path(__file__).with_name("lipsync_server")
STATE_FILE = "state.json"
START_TIMEOUT_S = 120.0
MIN_FREE_BYTES = 2_000_000_000

# where MuseTalk reads each catalogue file from, under its `models/` folder
WEIGHTS = {
    "musetalk-v15-unet.pth": "musetalkV15/unet.pth",
    "musetalk-v15.json": "musetalkV15/musetalk.json",
    "sd-vae-ft-mse.bin": "sd-vae/diffusion_pytorch_model.bin",
    "sd-vae-ft-mse.json": "sd-vae/config.json",
    "whisper-tiny.bin": "whisper/pytorch_model.bin",
    "whisper-tiny.json": "whisper/config.json",
    "whisper-tiny-preprocessor.json": "whisper/preprocessor_config.json",
    "face-parsing-bisenet.pth": "face-parse-bisent/79999_iter.pth",
    "resnet18-5c106cde.pth": "face-parse-bisent/resnet18-5c106cde.pth",
}
# the face detector and landmark model, which the `face-alignment` package looks for in the
# torch cache
TORCH_WEIGHTS = {
    "s3fd-619a316812.pth": "hub/checkpoints/s3fd-619a316812.pth",
    "2DFAN4-11f355bf06.pth.tar": "hub/checkpoints/2DFAN4-11f355bf06.pth.tar",
}


@dataclass(frozen=True)
class Pins:
    commit: str
    url: str
    size: int
    sha256: str
    python: str
    lock: Path
    lock_sha256: str
    packages_bytes: int
    platforms: tuple[str, ...]


def load_pins(path: Path = PINS_FILE) -> Pins:
    raw = json.loads(path.read_text())
    src = raw["source"]
    if not str(src["url"]).startswith("https://") or len(str(src["sha256"])) != 64:
        raise ValueError("the lip sync source pin needs an https URL and a SHA-256")
    if len(str(raw["lock_sha256"])) != 64:
        raise ValueError("the lip sync lock pin needs a SHA-256")
    return Pins(
        str(raw["commit"]), str(src["url"]), int(src["size"]), str(src["sha256"]).lower(),
        str(raw["python"]), path.parent / str(raw["lock"]), str(raw["lock_sha256"]).lower(),
        int(raw["packages_bytes"]), tuple(raw["platforms"]),
    )  # fmt: skip


@dataclass(frozen=True)
class MuseTalkInstall:
    src: Path  # MuseTalk's code; the server changes into it
    python: Path  # the interpreter of its environment
    torch_home: Path | None  # where the face detector weights are laid out (managed installs)
    source: str  # managed | env
    in_place: bool  # the weights are already in src/models (a copy set up by hand)


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def find_install(data_dir: Path, pins: Pins | None = None) -> MuseTalkInstall | None:
    """The engine to use: the one this app installed (and still matches the pins), else the copy
    named by `WASIFYAI_MUSETALK_HOME`. None when there is none."""
    pins = pins or load_pins()
    root = data_dir / "engine" / "musetalk"
    try:
        state = json.loads((root / STATE_FILE).read_text())
        py = _venv_python(root / "venv")
        if (
            state.get("schema") == 1
            and state.get("commit") == pins.commit
            and state.get("lock_sha256") == pins.lock_sha256
            and py.is_file()
            and (root / "src" / "musetalk").is_dir()
        ):
            return MuseTalkInstall(root / "src", py, root / "torch", "managed", False)
    except (OSError, ValueError):
        pass
    env = os.environ.get("WASIFYAI_MUSETALK_HOME")
    if env:
        home = Path(env).expanduser()
        py = _venv_python(home / "venv")
        if py.is_file() and (home / "src" / "musetalk").is_dir():
            return MuseTalkInstall(home / "src", py, None, "env", True)
    return None


def find_uv(data_dir: Path) -> str | None:
    """The `uv` the shell downloaded (it tells the engine in `WASIFYAI_UV`), else one on PATH."""
    env = os.environ.get("WASIFYAI_UV")
    if env and Path(env).is_file():
        return env
    managed = sorted((data_dir / "engine" / "tools").glob("uv-*/uv*"))
    for p in reversed(managed):
        if p.is_file() and p.name in ("uv", "uv.exe"):
            return str(p)
    return shutil.which("uv")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


# ---- installing it -------------------------------------------------------------------------------


async def _run(
    args: list[str], cwd: Path, env: dict[str, str], limit_s: float = 3600
) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )  # fmt: skip
        out, _ = await asyncio.wait_for(proc.communicate(), limit_s)
    except (OSError, TimeoutError):
        return False, ""
    return proc.returncode == 0, out.decode(errors="replace")


class MuseTalkInstaller:
    """Sets up MuseTalk's code and environment. Nothing is fetched before the person has seen the
    size and confirmed it; the weights are separate (Models)."""

    def __init__(self, data_dir: Path, pins: Pins | None = None, client_factory: Any = None):
        self._data_dir = data_dir
        self._root = data_dir / "engine" / "musetalk"
        self.pins = pins or load_pins()
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60, read=120))
        )
        self.progress = InstallProgress()
        self._task: asyncio.Task[None] | None = None
        self.run = _run  # replaced in tests

    @property
    def supported(self) -> bool:
        return platform_key() in self.pins.platforms

    @property
    def total_bytes(self) -> int:
        return self.pins.size + self.pins.packages_bytes

    def plan(self) -> dict[str, Any]:
        env = os.environ.get("WASIFYAI_MUSETALK_HOME")
        found = find_install(self._data_dir, self.pins)
        return {
            "supported": self.supported, "platform": platform_key(),
            "commit": self.pins.commit[:7], "bytes": self.total_bytes if self.supported else 0,
            "uv": find_uv(self._data_dir) is not None,
            "found": {"path": env} if found is not None and found.source == "env" else None,
        }  # fmt: skip

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, confirm_bytes: int) -> None:
        if not self.supported:
            raise InstallError("There is no lip sync engine for this kind of computer yet.")
        if confirm_bytes != self.total_bytes:
            raise InstallError("The download changed since it was shown. Look at it again.")
        if self.running:
            raise InstallError("The lip sync engine is already being set up.")
        if find_uv(self._data_dir) is None:
            raise InstallError("The installer tool (uv) was not found. Repair the app first.")
        self.progress = InstallProgress("installing", "source", "Starting", 0, self.total_bytes)
        self._task = asyncio.create_task(self._run())

    def _say(self, step: str, message: str, done: int | None = None) -> None:
        p = self.progress
        self.progress = InstallProgress(
            "installing", step, message, p.done_bytes if done is None else done, p.total_bytes
        )

    async def _run(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix="stage-", dir=self._root))
        try:
            await self._install(stage)
            self.progress = InstallProgress(
                "ready", None, "Ready", self.total_bytes, self.total_bytes
            )
        except InstallError as e:
            self.progress = InstallProgress("failed", self.progress.step, str(e))
        except Exception:
            log.exception("the lip sync engine did not install")
            self.progress = InstallProgress(
                "failed", self.progress.step, "The lip sync engine could not be set up. Try again."
            )
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def _uv_env(self) -> dict[str, str]:
        root = self._data_dir / "engine"
        return {
            **os.environ, "UV_PYTHON_INSTALL_DIR": str(root / "python"),
            "UV_CACHE_DIR": str(root / "cache"), "UV_NO_CONFIG": "1",
            "UV_PYTHON_PREFERENCE": "only-managed", "UV_LINK_MODE": "copy",
            "UV_NO_PROGRESS": "1", "NO_COLOR": "1",
        }  # fmt: skip

    async def _install(self, stage: Path) -> None:
        pins = self.pins
        free = await asyncio.to_thread(lambda: shutil.disk_usage(self._root).free)
        if free < self.total_bytes * 2 + MIN_FREE_BYTES:
            raise InstallError("There is not enough free disk space for the lip sync engine.")
        uv = find_uv(self._data_dir)
        if uv is None:
            raise InstallError("The installer tool (uv) was not found. Repair the app first.")
        if _sha256_file(pins.lock) != pins.lock_sha256:
            raise InstallError("The package list shipped with the app does not match its pin.")

        archive = stage / "musetalk.tar.gz"
        self._say("source", "Getting MuseTalk", 0)
        digest, size = hashlib.sha256(), 0
        async with self._client_factory() as http, http.stream("GET", pins.url) as r:
            r.raise_for_status()
            with archive.open("wb") as f:
                async for block in r.aiter_bytes(1 << 20):
                    f.write(block)
                    digest.update(block)
                    size += len(block)
                    self._say("source", "Getting MuseTalk", size)
        if size != pins.size or digest.hexdigest() != pins.sha256:
            raise InstallError("The download did not match what was expected. Nothing was kept.")

        self._say("unpack", "Unpacking", pins.size)
        unpacked = stage / "unpacked"
        await asyncio.to_thread(_unpack, archive, unpacked)
        tops = [p for p in unpacked.iterdir() if p.is_dir()]
        if len(tops) != 1 or not (tops[0] / "musetalk").is_dir():
            raise InstallError("The download did not contain MuseTalk.")

        env = self._uv_env()
        final = self._root
        # the old install goes first, so a failure never leaves one that looks whole
        for name in (STATE_FILE, "src", "venv"):
            target = final / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        shutil.move(str(tops[0]), str(final / "src"))
        venv = final / "venv"  # made where it will stay: a virtual environment is not relocatable
        self._say("environment", "Creating the environment", pins.size)
        ok, text = await self.run([uv, "venv", "--python", pins.python, str(venv)], final, env)
        if not ok:
            log.error("uv venv failed: %s", text[-600:])
            raise InstallError("The environment for lip sync could not be created.")
        self._say("packages", "Installing the packages (a few minutes)", pins.size)
        py = _venv_python(venv)
        ok, text = await self.run(
            [uv, "pip", "install", "--python", str(py), "--require-hashes", "-r", str(pins.lock)],
            final, env,
        )  # fmt: skip
        if not ok:
            log.error("uv pip install failed: %s", text[-800:])
            raise InstallError("The packages for lip sync could not be installed.")

        self._say("verify", "Checking that it starts", pins.size + pins.packages_bytes - 1)
        ok, text = await self.run(
            [str(py), "-c",
             "import torch,cv2,face_alignment,transformers,diffusers;"
             "print('accelerator', 'mps' if torch.backends.mps.is_available() else "
             "'cuda' if torch.cuda.is_available() else 'cpu')"],
            final, env, 300,
        )  # fmt: skip
        if not ok or "accelerator" not in text:
            log.error("the lip sync check failed: %s", text[-600:])
            raise InstallError("The lip sync engine did not start on this computer.")
        accelerator = text.split("accelerator", 1)[1].split()[0]
        record = {
            "schema": 1, "commit": pins.commit, "python": pins.python,
            "lock_sha256": pins.lock_sha256, "accelerator": accelerator,
        }  # fmt: skip
        tmp = final / (STATE_FILE + ".part")
        tmp.write_text(json.dumps(record))
        tmp.replace(final / STATE_FILE)  # last: this is what makes it installed


def _unpack(archive: Path, target: Path) -> None:
    target.mkdir(parents=True)
    with tarfile.open(archive) as t:
        t.extractall(target, filter="data")  # refuses absolute paths, '..' and links outside


# ---- the process ---------------------------------------------------------------------------------


def _lay_out(install: MuseTalkInstall, files: dict[str, Path]) -> None:
    """Put the weights where MuseTalk and the face-alignment package read them: links to the files
    Models downloaded (a copy where links are not allowed)."""
    pairs = [(files.get(name), install.src / "models" / rel) for name, rel in WEIGHTS.items()]
    if install.torch_home is not None:
        pairs += [(files.get(n), install.torch_home / rel) for n, rel in TORCH_WEIGHTS.items()]
    for source, dest in pairs:
        if source is None:
            raise VoiceEngineError("model_missing", "MuseTalk is not on this computer yet.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink() or dest.exists():
            if dest.is_symlink() and dest.resolve() == source.resolve():
                continue
            dest.unlink()
        try:
            dest.symlink_to(source)
        except OSError:
            shutil.copyfile(source, dest)


class LipSyncSidecar:
    def __init__(self, data_dir: Path, pins: Pins | None = None):
        self._data_dir = data_dir
        self.pins = pins or load_pins()
        self.installer = MuseTalkInstaller(data_dir, self.pins)
        self._proc: asyncio.subprocess.Process | None = None
        self._url: str | None = None
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(timeout=3)
        self.slot: Any = None

    @property
    def install(self) -> MuseTalkInstall | None:
        return find_install(self._data_dir, self.pins)

    @property
    def installed(self) -> bool:
        return self.install is not None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def state(self) -> dict[str, Any]:
        inst = self.install
        return {
            "installed": inst is not None, "source": inst.source if inst else None,
            "running": self.running, "plan": self.installer.plan(),
            "install": self.installer.progress.public(),
        }  # fmt: skip

    async def _health(self, url: str) -> dict[str, Any] | None:
        try:
            r = await self._http.get(f"{url}/health")
            return r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    async def ensure_running(self, files: dict[str, Path]) -> str:
        async with self._lock:
            if self.running and self._url and await self._health(self._url) is not None:
                return self._url
            await self._terminate()
            install = self.install
            if install is None:
                raise VoiceEngineError(
                    "runtime_missing", "The lip sync engine is not set up yet. Set it up first."
                )
            if not install.in_place:
                await asyncio.to_thread(_lay_out, install, files)
            return await self._start(install)

    async def _start(self, install: MuseTalkInstall) -> str:
        with socket.socket() as s:  # a free port on loopback
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        logs = self._data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        out = (logs / "lipsync.log").open("ab")
        env = {
            **os.environ, "MUSETALK_DIR": str(install.src), "PYTORCH_ENABLE_MPS_FALLBACK": "1",
            "PYTHONNOUSERSITE": "1", "PYTHONUNBUFFERED": "1",
            # torch compiles the face finder with a C++ build that does not quote a folder with a
            # space in its name (macOS "Application Support"); the eager model is as fast here
            "TORCHDYNAMO_DISABLE": "1",
        }  # fmt: skip
        if install.torch_home is not None:
            env["TORCH_HOME"] = str(install.torch_home)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                str(install.python), "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
                "--port", str(port), cwd=str(SERVER_DIR), env=env,
                stdin=asyncio.subprocess.DEVNULL, stdout=out, stderr=asyncio.subprocess.STDOUT,
            )  # fmt: skip
        finally:
            out.close()
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc.returncode is not None:
                break
            if await self._health(url) is not None:
                self._url = url
                return url
            await asyncio.sleep(0.25)
        code = self._proc.returncode
        await self._terminate()
        log.error("the lip sync server did not start (exit %s); see logs/lipsync.log", code)
        raise VoiceEngineError("engine_stopped", "The lip sync engine did not start. Try again.")

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

    async def stop(self) -> bool:
        was = self.running
        async with self._lock:
            await self._terminate()
        return was

    async def close(self) -> None:
        await self.stop()
        await self._http.aclose()

    async def generate(
        self,
        model: VoiceModel,
        req: LipSyncRequest,
        picture: Path,
        voice: Path,
        files: dict[str, Path],
    ) -> LipSyncResult:
        t0 = time.monotonic()
        url = await self.ensure_running(files)
        health = await self._health(url) or {}
        warm = bool(health.get("loaded"))
        wait = max(600.0, req.voice_seconds * 40)
        pic, wav = await asyncio.gather(
            asyncio.to_thread(picture.read_bytes), asyncio.to_thread(voice.read_bytes)
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=wait)) as http:
                r = await http.post(
                    f"{url}/v1/lipsync",
                    data={"fps": str(req.fps), "mark": req.mark},
                    files={"image": ("face.png", pic, "image/png"),
                           "audio": ("voice.wav", wav, "audio/wav")},
                )  # fmt: skip
        except asyncio.CancelledError:
            await asyncio.shield(self.stop())  # the server keeps working on what was asked
            raise
        except httpx.HTTPError as e:
            await self.stop()
            raise VoiceEngineError(
                "engine_stopped", "The lip sync engine stopped. Try again."
            ) from e
        if r.status_code == 422:
            raise VoiceEngineError(
                "no_face", "No clear face was found in the picture. Try a front-facing one."
            )
        if r.status_code >= 300:
            log.warning("lip sync server answered %s: %s", r.status_code, r.text[:300])
            raise VoiceEngineError("engine_failed", "The lip sync could not be made. Try again.")
        elapsed = time.monotonic() - t0
        width, height = await asyncio.to_thread(_video_size, r.content)
        return LipSyncResult(
            r.content, req.voice_seconds, req.fps, width, height, model.id,
            0.0 if warm else min(elapsed, 30.0), elapsed,
        )  # fmt: skip


def _video_size(mp4: bytes) -> tuple[int, int]:
    """Width and height of an MP4's video track, from its `tkhd` box ((0, 0) if unreadable). An
    audio track's box has no size (0 by 0), so the first box with one is the video's."""
    i = mp4.find(b"tkhd")
    while i != -1:
        box = mp4[i + 4 : i + 4 + 100]
        if box:
            skip = 4 + (20 if box[0] == 0 else 32) + 52  # version and flags, times and ids, matrix
            if len(box) >= skip + 8:
                w = int.from_bytes(box[skip : skip + 4], "big") >> 16
                h = int.from_bytes(box[skip + 4 : skip + 8], "big") >> 16
                if w and h:
                    return w, h
        i = mp4.find(b"tkhd", i + 4)
    return 0, 0
