"""The Indian-language speech engine (docs/voice-languages-plan.md, stages L5 and L6): Indic
Parler-TTS and IndicConformer as an optional sidecar, set up like the lip sync engine.

    IndicInstaller   a hashed package lock, installed with the app's own `uv` in an environment of
                     its own (torch and transformers 4.46 must not touch the engine's packages)
    IndicSidecar     one `uvicorn` process running `indic_server/` on loopback, started on demand
                     and stopped to give the memory back

The weights are catalogue entries (`indic-parler-tts`, `indic-conformer-600m` in the voice product's
`models.yaml`), fetched in Models after the person has seen their size. A catalogue file named
`a--b--c` is laid out as `a/b/c` under the engine's `models/` folder, so each model finds its files
where its own code reads them. Every platform: the lock is universal (CUDA on Linux, the CPU on
Windows, the graphics chip on a Mac)."""

import asyncio
import contextlib
import json
import logging
import os
import shutil
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from wasifyai_platform_sdk import (
    SpeechResult,
    TranscriptResult,
    TranscriptSegment,
    VoiceEngineError,
    VoiceModel,
    installer,
)

from wasifyai_api.audio_runtime import InstallError, InstallProgress, platform_key
from wasifyai_api.components.manifest import PACKAGE_DIR, part_pins
from wasifyai_api.lipsync_runtime import _run, _sha256_file, _venv_python, find_uv

log = logging.getLogger(__name__)

PART = "indic"
NOUN = "Indian-language speech engine"
STEP_WORDS = {
    "environment": "Creating the environment",
    "packages": "Installing the packages (a few minutes)",
}
SERVER_DIR = Path(__file__).with_name("indic_server")
STATE_FILE = "state.json"
START_TIMEOUT_S = 120.0
MIN_FREE_BYTES = 2_000_000_000
SEP = "--"  # a catalogue file `a--b--c` is laid out as `a/b/c`


@dataclass(frozen=True)
class Pins:
    python: str
    lock: Path
    lock_sha256: str
    packages_bytes: int
    platforms: tuple[str, ...]


def load_pins(path: Path | None = None) -> Pins:
    """The engine's pins: its part in this platform's component manifest, or a file (tests)."""
    raw = json.loads(path.read_text()) if path is not None else part_pins(PART)
    base = path.parent if path is not None else PACKAGE_DIR
    if len(str(raw["lock_sha256"])) != 64:
        raise ValueError("the Indian-language speech lock pin needs a SHA-256")
    return Pins(
        str(raw["python"]), base / str(raw["lock"]), str(raw["lock_sha256"]).lower(),
        int(raw["packages_bytes"]), tuple(raw["platforms"]),
    )  # fmt: skip


@dataclass(frozen=True)
class IndicInstall:
    python: Path
    source: str  # managed | env


def find_install(data_dir: Path, pins: Pins) -> IndicInstall | None:
    """The environment this app set up (and still matches the pins), else the one named by
    `WASIFYAI_INDIC_VENV` (development). None when there is none."""
    root = data_dir / "engine" / PART
    state = installer.read_state(root / STATE_FILE) or {}
    py = _venv_python(root / "venv")
    if state.get("schema") == 1 and state.get("lock_sha256") == pins.lock_sha256 and py.is_file():
        return IndicInstall(py, "managed")
    env = os.environ.get("WASIFYAI_INDIC_VENV")
    if env:
        py = _venv_python(Path(env).expanduser())
        if py.is_file():
            return IndicInstall(py, "env")
    return None


class IndicInstaller:
    """Sets up the engine's environment. Nothing is fetched before the person has seen the size and
    confirmed it; the weights are separate (Models)."""

    def __init__(self, data_dir: Path, pins: Pins | None = None):
        self._data_dir = data_dir
        self._root = data_dir / "engine" / PART
        self.pins = pins or load_pins()
        self.progress = InstallProgress()
        self._task: asyncio.Task[None] | None = None
        self.run = _run  # replaced in tests

    @property
    def supported(self) -> bool:
        return platform_key() in self.pins.platforms

    @property
    def total_bytes(self) -> int:
        return self.pins.packages_bytes

    def plan(self) -> dict[str, Any]:
        found = find_install(self._data_dir, self.pins)
        return {
            "supported": self.supported, "platform": platform_key(),
            "commit": self.pins.lock_sha256[:7], "bytes": self.total_bytes if self.supported else 0,
            "uv": find_uv(self._data_dir) is not None,
            "found": {"path": os.environ.get("WASIFYAI_INDIC_VENV")}
            if found is not None and found.source == "env" else None,
        }  # fmt: skip

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, confirm_bytes: int) -> None:
        if not self.supported:
            raise InstallError(f"There is no {NOUN} for this kind of computer yet.")
        if confirm_bytes != self.total_bytes:
            raise InstallError("The download changed since it was shown. Look at it again.")
        if self.running:
            raise InstallError(f"The {NOUN} is already being set up.")
        if find_uv(self._data_dir) is None:
            raise InstallError("The installer tool (uv) was not found. Repair the app first.")
        self.progress = InstallProgress(
            "installing", "environment", "Starting", 0, self.total_bytes
        )
        self._task = asyncio.create_task(self._run())

    def cancel(self) -> bool:
        if not self.running or self._task is None:
            return False
        self._task.cancel()
        return True

    async def wait(self) -> None:
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def _say(self, step: str, message: str, done: int = 0) -> None:
        self.progress = InstallProgress(
            "installing", step, message, done, self.progress.total_bytes
        )

    async def _run(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        try:
            await self._install()
            self.progress = InstallProgress(
                "ready", None, "Ready", self.total_bytes, self.total_bytes
            )
        except asyncio.CancelledError:
            self.progress = InstallProgress("failed", self.progress.step, "Stopped.")
            raise
        except InstallError as e:
            self.progress = InstallProgress("failed", self.progress.step, str(e))
        except Exception:
            log.exception("the Indian-language speech engine did not install")
            self.progress = InstallProgress(
                "failed", self.progress.step, f"The {NOUN} could not be set up. Try again."
            )

    def _uv_env(self) -> dict[str, str]:
        root = self._data_dir / "engine"
        return {
            **os.environ, "UV_PYTHON_INSTALL_DIR": str(root / "python"),
            "UV_CACHE_DIR": str(root / "cache"), "UV_NO_CONFIG": "1",
            "UV_PYTHON_PREFERENCE": "only-managed", "UV_LINK_MODE": "copy",
            "UV_NO_PROGRESS": "1", "NO_COLOR": "1",
        }  # fmt: skip

    async def _install(self) -> None:
        pins = self.pins
        free = await asyncio.to_thread(lambda: shutil.disk_usage(self._root).free)
        if free < self.total_bytes * 2 + MIN_FREE_BYTES:
            raise InstallError(f"There is not enough free disk space for the {NOUN}.")
        uv = find_uv(self._data_dir)
        if uv is None:
            raise InstallError("The installer tool (uv) was not found. Repair the app first.")
        if await asyncio.to_thread(_sha256_file, pins.lock) != pins.lock_sha256:
            raise InstallError("The package list shipped with the app does not match its pin.")
        final = self._root
        (final / STATE_FILE).unlink(missing_ok=True)  # never an old record over a new venv
        venv = final / "venv"
        env = self._uv_env()

        async def run(args: list[str], env_: dict[str, str], cwd: Path | None) -> tuple[int, str]:
            ok, text = await self.run(args, cwd or final, env_)
            return (0 if ok else 1), text

        # the lock is whole (an override in it would not survive a resolve), so no resolving here
        py = await installer.make_environment(
            uv, pins.python, venv, pins.lock, pins.lock_sha256, "environment", "packages", run,
            env, no_deps=True, on_step=lambda step: self._say(step, STEP_WORDS.get(step, step)),
            owner=f"The {NOUN}",
        )  # fmt: skip

        self._say("verify", "Checking that it starts", pins.packages_bytes - 1)
        ok, text = await self.run(
            [str(py), "-I", "-c",
             "import torch,parler_tts,onnxruntime,soundfile,transformers;"
             "print('accelerator', 'mps' if torch.backends.mps.is_available() else "
             "'cuda' if torch.cuda.is_available() else 'cpu')"],
            final, env, 300,
        )  # fmt: skip
        if not ok or "accelerator" not in text:
            log.error("the Indian-language speech check failed: %s", text[-600:])
            raise InstallError(f"The {NOUN} did not start on this computer.")
        installer.write_state(
            final / STATE_FILE,
            {"schema": 1, "python": pins.python, "lock_sha256": pins.lock_sha256,
             "accelerator": text.split("accelerator", 1)[1].split()[0]},
        )  # fmt: skip


# ---- the process ---------------------------------------------------------------------------------


def lay_out(root: Path, files: dict[str, Path]) -> None:
    """Links (a copy where links are not allowed) from `root/a/b/c` to each downloaded `a--b--c`."""
    for name, source in files.items():
        parts = name.split(SEP)
        if any(p in ("", ".", "..") for p in parts):
            raise VoiceEngineError("model_missing", "A model file has a name this app cannot use.")
        dest = root.joinpath(*parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink() or dest.exists():
            if dest.is_symlink() and dest.resolve() == source.resolve():
                continue
            dest.unlink()
        try:
            dest.symlink_to(source)
        except OSError:
            shutil.copyfile(source, dest)


class IndicSidecar:
    def __init__(self, data_dir: Path, pins: Pins | None = None):
        self._data_dir = data_dir
        self.pins = pins or load_pins()
        self.installer = IndicInstaller(data_dir, self.pins)
        self.models_root = data_dir / "engine" / PART / "models"
        self._proc: asyncio.subprocess.Process | None = None
        self._url: str | None = None
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(timeout=3)

    @property
    def install(self) -> IndicInstall | None:
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
        await asyncio.to_thread(lay_out, self.models_root, files)
        async with self._lock:
            if self.running and self._url and await self._health(self._url) is not None:
                return self._url
            await self._terminate()
            install = self.install
            if install is None:
                raise VoiceEngineError(
                    "runtime_missing", f"The {NOUN} is not set up yet. Set it up first."
                )
            return await self._start(install)

    async def _start(self, install: IndicInstall) -> str:
        with socket.socket() as s:  # a free port on loopback
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        logs = self._data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        out = (logs / "indic.log").open("ab")
        env = {
            **os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1", "PYTHONNOUSERSITE": "1",
            "PYTHONUNBUFFERED": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }  # fmt: skip
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
        log.error("the Indian-language speech server did not start (exit %s); see logs", code)
        raise VoiceEngineError("engine_stopped", f"The {NOUN} did not start. Try again.")

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

    async def _post(self, url: str, path: str, wait: float, **kw: Any) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=wait)) as http:
                return await http.post(f"{url}{path}", **kw)
        except asyncio.CancelledError:
            await asyncio.shield(self.stop())  # the server keeps working on what was asked
            raise
        except httpx.HTTPError as e:
            await self.stop()
            raise VoiceEngineError("engine_stopped", f"The {NOUN} stopped. Try again.") from e

    async def speak(
        self, model: VoiceModel, text: str, voice: str | None, files: dict[str, Path],
        seed: int | None = None,
    ) -> SpeechResult:  # fmt: skip
        t0 = time.monotonic()
        url = await self.ensure_running(files)
        warm = bool(((await self._health(url)) or {}).get("loaded", {}).get("speak"))
        speaker = voice or model.default_voice or ""
        if model.voices and model.voice(speaker) is None:
            raise VoiceEngineError("unknown_voice", f"{model.title} has no voice called {speaker}.")
        r = await self._post(
            url, "/v1/speech", max(600.0, len(text) * 2.0),
            json={"folder": str(self.models_root), "text": text, "speaker": speaker,
                  "seed": seed},
        )  # fmt: skip
        if r.status_code >= 300:
            log.warning("indic speech answered %s: %s", r.status_code, r.text[:300])
            raise VoiceEngineError("engine_failed", "The speech could not be made. Try again.")
        from wasifyai_api.audio_runtime import _wav_rate, _wav_seconds

        wav = r.content
        seconds = _wav_seconds(wav)
        if seconds <= 0:
            raise VoiceEngineError("engine_failed", "The speech model returned no audio.")
        elapsed = time.monotonic() - t0
        return SpeechResult(
            wav, _wav_rate(wav) or model.sample_rate, seconds, model.id, speaker,
            0.0 if warm else min(elapsed, 60.0), elapsed,
        )  # fmt: skip

    async def transcribe(
        self, model: VoiceModel, wav: bytes, language: str, files: dict[str, Path]
    ) -> TranscriptResult:
        t0 = time.monotonic()
        url = await self.ensure_running(files)
        r = await self._post(
            url, "/v1/transcribe", 1800.0,
            data={"folder": str(self.models_root), "language": language},
            files={"file": ("audio.wav", wav, "audio/wav")},
        )  # fmt: skip
        if r.status_code == 422:
            raise VoiceEngineError("wrong_language", f"{model.title} does not write that language.")
        if r.status_code >= 300:
            log.warning("indic transcription answered %s: %s", r.status_code, r.text[:300])
            raise VoiceEngineError(
                "engine_failed", "The recording could not be written down. Try again."
            )
        try:
            j = r.json()
        except ValueError:
            raise VoiceEngineError(
                "engine_failed", "The model's answer could not be read."
            ) from None
        segments = tuple(
            TranscriptSegment(float(s["start"]), float(s["end"]), str(s["text"]))
            for s in j.get("segments", [])
        )
        return TranscriptResult(
            str(j.get("text", "")).strip(), segments, float(j.get("seconds", 0)), model.id,
            time.monotonic() - t0,
        )  # fmt: skip
