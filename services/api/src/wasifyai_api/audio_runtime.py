"""The speech runtime of the desktop engine (ADR-0066, stage V1): audio.cpp as one child process.

    AudioInstaller   the pinned prebuilt, shown and confirmed first, downloaded, SHA-256
    checked, unpacked
    AudioServer      one `audiocpp_server` for every model that is on this computer: lazy loading,
                     one model resident at a time, on loopback, stopped to give the memory back
    AudioEngine      what a product asks (`SpeechEngine`): the models with their state, speak,
    transcribe

The boundary is the loopback address and the process being the engine's own child, as for ComfyUI
(ADR-0059) and llama.cpp. The server answers a person's mistake with HTTP 500 and may accept an
option
it ignores (docs/spikes/voice-v0.md), so every request is validated against the model's descriptor
(`wasifyai_platform_sdk.voice_models`) before it is sent, and nothing here trusts a status code."""

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import platform
import secrets
import shutil
import socket
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from wasifyai_platform_sdk import (
    ConvertRequest,
    LipSyncRequest,
    LipSyncResult,
    MusicEditRequest,
    MusicRequest,
    MusicResult,
    SeparateRequest,
    SeparateResult,
    SpeechEditRequest,
    SpeechResult,
    Stem,
    TranscriptResult,
    TranscriptSegment,
    VoiceEngineError,
    VoiceModel,
    installer,
)
from wasifyai_platform_sdk.slots import Held

from wasifyai_api.components.manifest import part_pins

log = logging.getLogger(__name__)

INSTALL_RECORD = "INSTALL.json"
MIN_FREE_BYTES = 1_000_000_000
SERVER_START_TIMEOUT_S = 120.0
REQUEST_TIMEOUT_S = 900.0
FOUND_DIR = Path.home() / ".unsloth" / "audio.cpp"  # a copy another tool left (ADR-0063)
FOUND_RECORD = "UNSLOTH_AUDIO_CPP_PREBUILT_INFO.json"


# ---- the pinned runtime -------------------------------------------------------------------------


@dataclass(frozen=True)
class Pin:
    platform: str
    name: str
    url: str
    size: int
    sha256: str
    backend: str
    archive: str  # tar.gz | zip
    measured: bool


@dataclass(frozen=True)
class Pins:
    repo: str
    tag: str
    server: str
    assets: dict[str, Pin]


def load_pins(path: Path | None = None) -> Pins:
    """The speech runtime's pins: its part in this platform's component manifest (stage F2)."""
    raw = json.loads(path.read_text()) if path is not None else part_pins("audiocpp")
    assets = {
        key: Pin(key, a["name"], a["url"], int(a["size"]), a["sha256"].lower(), a["backend"],
                 a["archive"], bool(a["measured"]))
        for key, a in raw["assets"].items()
    }  # fmt: skip
    for a in assets.values():
        if not a.url.startswith("https://") or len(a.sha256) != 64 or a.size <= 0:
            raise ValueError(f"{a.platform}: a pin needs an https URL, a size and a SHA-256")
    return Pins(raw["repo"], raw["tag"], raw["server"], assets)


def platform_key() -> str:
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if sys.platform == "darwin":
        return "darwin-arm64" if arm else "darwin-x64"
    if sys.platform == "win32":
        return "windows-x64"
    return "linux-arm64" if arm else "linux-x64"


@dataclass(frozen=True)
class AudioInstall:
    tag: str
    backend: str
    server: Path
    source: str  # managed | env | found


def _runnable(p: Path) -> bool:
    return p.is_file() and (sys.platform == "win32" or os.access(p, os.X_OK))


def find_install(data_dir: Path) -> AudioInstall | None:
    """The runtime to use: the one this app installed, else `WASIFYAI_AUDIOCPP` (a binary, for
    development), else a copy the person chose to use ("found"). None when there is none."""
    root = data_dir / "engine" / "audiocpp"
    try:
        rec = json.loads((root / INSTALL_RECORD).read_text())
        server = Path(rec["server"])
        if not server.is_absolute():
            server = (root / server).resolve()
            if not str(server).startswith(str(root.resolve())):
                return None
        if _runnable(server):
            return AudioInstall(str(rec["tag"]), str(rec["backend"]), server, str(rec["source"]))
    except (OSError, ValueError, KeyError):
        pass
    env = os.environ.get("WASIFYAI_AUDIOCPP")
    if env and _runnable(Path(env)):
        return AudioInstall("env", "auto", Path(env), "env")
    return None


def find_found_copy(pins: Pins) -> dict[str, Any] | None:
    """A copy of the pinned release that another tool installed, if it is exactly ours: the same
    tag, and the binary's SHA-256 is the one that tool recorded. Offered, never used by itself."""
    try:
        rec = json.loads((FOUND_DIR / FOUND_RECORD).read_text())
        server = FOUND_DIR / str(rec["server_relpath"])
        if rec.get("release_tag") != pins.tag or not _runnable(server):
            return None
        return {
            "path": str(server),
            "tag": rec["release_tag"],
            "backend": rec.get("backend", "cpu"),
            "sha256": rec.get("server_sha256", ""),
        }
    except (OSError, ValueError, KeyError):
        return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


# ---- installing it ------------------------------------------------------------------------------


# the one installer's error (stage F2): `str(e)` is a sentence safe to show
InstallError = installer.InstallError


@dataclass
class InstallProgress:
    state: str = "idle"  # idle | installing | ready | failed
    step: str | None = None
    message: str = ""
    done_bytes: int = 0
    total_bytes: int = 0

    def public(self) -> dict[str, Any]:
        return {"state": self.state, "step": self.step, "message": self.message,
                "done_bytes": self.done_bytes, "total_bytes": self.total_bytes}  # fmt: skip


class AudioInstaller:
    def __init__(self, data_dir: Path, pins: Pins | None = None, client_factory: Any = None):
        self._root = data_dir / "engine" / "audiocpp"
        self._data_dir = data_dir
        self.pins = pins or load_pins()
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60, read=120))
        )
        self.progress = InstallProgress()
        self._task: asyncio.Task[None] | None = None

    def pin(self) -> Pin | None:
        return self.pins.assets.get(platform_key())

    def plan(self) -> dict[str, Any]:
        """What installing would fetch, for the confirmation the person sees first."""
        pin = self.pin()
        found = find_found_copy(self.pins)
        return {
            "supported": pin is not None, "platform": platform_key(), "tag": self.pins.tag,
            "bytes": pin.size if pin else 0, "url": pin.url if pin else None,
            "backend": pin.backend if pin else None, "measured": bool(pin and pin.measured),
            "found": found,
        }  # fmt: skip

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, confirm_bytes: int) -> None:
        pin = self.pin()
        if pin is None:
            raise InstallError("There is no speech runtime for this kind of computer yet.")
        if confirm_bytes != pin.size:
            raise InstallError("The download changed since it was shown. Look at it again.")
        if self.running:
            raise InstallError("The speech runtime is already being set up.")
        self.progress = InstallProgress("installing", "download", "Starting", 0, pin.size)
        self._task = asyncio.create_task(self._run(pin))

    async def _run(self, pin: Pin) -> None:
        stage = Path(tempfile.mkdtemp(prefix="audiocpp-", dir=self._ensure_root()))
        try:
            await self._install(pin, stage)
            self.progress = InstallProgress("ready", None, "Ready", pin.size, pin.size)
        except InstallError as e:
            self.progress = InstallProgress("failed", self.progress.step, str(e))
        except Exception:
            log.exception("the speech runtime did not install")
            self.progress = InstallProgress(
                "failed", self.progress.step, "The speech runtime could not be set up. Try again."
            )
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def _ensure_root(self) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root

    def _say(self, step: str, message: str, done: int | None = None) -> None:
        p = self.progress
        done_bytes = p.done_bytes if done is None else done
        self.progress = InstallProgress("installing", step, message, done_bytes, p.total_bytes)

    async def _install(self, pin: Pin, stage: Path) -> None:
        free = await asyncio.to_thread(lambda: shutil.disk_usage(self._root).free)
        if free < pin.size * 3 + MIN_FREE_BYTES:
            raise InstallError("There is not enough free disk space for the speech runtime.")
        archive = stage / pin.name
        self._say("download", "Downloading the speech runtime", 0)
        # through the one installer (stage F2): size and SHA-256 checked, nothing kept otherwise
        await installer.download(
            installer.Archive(pin.url, pin.size, pin.sha256, pin.archive), archive, "download",
            lambda done, _: self._say("download", "Downloading the speech runtime", done),
            client=self._client_factory,
        )  # fmt: skip
        self._say("unpack", "Unpacking")
        target = stage / "unpacked"
        await asyncio.to_thread(installer.unpack, archive, pin.archive, 0, target, "unpack")
        server = await asyncio.to_thread(_find_server, target, self.pins.server)
        if server is None:
            raise InstallError("The download did not contain the speech runtime.")
        self._say("check", "Checking that it starts")
        ok, text = await _run([str(server), "--version"], cwd=server.parent)
        if not ok or "audio.cpp" not in text:
            raise InstallError("The speech runtime did not start on this computer.")
        final = self._root / self.pins.tag
        if final.exists():
            shutil.rmtree(final)
        shutil.move(str(target), str(final))
        rel = (final / server.relative_to(target)).relative_to(self._root)
        record = {"tag": self.pins.tag, "backend": pin.backend, "server": str(rel),
                  "source": "managed", "asset_sha256": pin.sha256}  # fmt: skip
        tmp = self._root / (INSTALL_RECORD + ".part")
        tmp.write_text(json.dumps(record))
        tmp.replace(self._root / INSTALL_RECORD)

    def use_found(self) -> AudioInstall:
        """Record the copy another tool installed as ours to use (nothing is copied)."""
        found = find_found_copy(self.pins)
        if found is None:
            raise InstallError("That copy of the speech runtime is no longer there.")
        server = Path(found["path"])
        if found["sha256"] and _sha256_file(server) != found["sha256"]:
            raise InstallError("That copy of the speech runtime has changed; it was not used.")
        self._ensure_root()
        record = {"tag": found["tag"], "backend": found["backend"], "server": str(server),
                  "source": "found"}  # fmt: skip
        (self._root / INSTALL_RECORD).write_text(json.dumps(record))
        return AudioInstall(found["tag"], found["backend"], server, "found")


def _find_server(root: Path, name: str) -> Path | None:
    names = {name, name + ".exe"}
    for depth in (0, 1, 2):
        for p in root.glob("/".join(["*"] * depth + ["*"])):
            if p.name in names and p.is_file():
                if sys.platform != "win32":
                    p.chmod(p.stat().st_mode | 0o111)
                return p
    return None


async def _run(args: list[str], cwd: Path, limit_s: float = 30) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )  # fmt: skip
        out, _ = await asyncio.wait_for(proc.communicate(), limit_s)
    except (OSError, TimeoutError):
        return False, ""
    return proc.returncode == 0, out.decode(errors="replace")


def _backend_for(install: AudioInstall) -> str:
    if install.backend != "auto":
        return install.backend
    return "metal" if sys.platform == "darwin" else "cpu"


# ---- the process --------------------------------------------------------------------------------


@dataclass(frozen=True)
class ServedModel:
    id: str
    family: str
    task: str
    path: Path


class AudioServer:
    """One `audiocpp_server` for the models on this computer. It is restarted when that set changes,
    and stopped to give memory back (the slot calls `stop`)."""

    def __init__(self, data_dir: Path, startup_timeout_s: float = SERVER_START_TIMEOUT_S):
        self._data_dir = data_dir
        self._timeout = startup_timeout_s
        self._proc: asyncio.subprocess.Process | None = None
        self._url: str | None = None
        self._served: tuple[ServedModel, ...] = ()
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(timeout=3)
        self.install: AudioInstall | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self.running and self._proc is not None else None

    def _log_path(self) -> Path:
        return self._data_dir / "logs" / "audiocpp-server.log"

    async def _healthy(self, url: str) -> bool:
        try:
            return (await self._http.get(f"{url}/health")).status_code == 200
        except httpx.HTTPError:
            return False

    async def ensure(self, install: AudioInstall, served: list[ServedModel]) -> str:
        """The base URL of a server that knows exactly these models."""
        want = tuple(sorted(served, key=lambda m: m.id))
        async with self._lock:
            if (
                self.running and self._url and self._served == want
                and self.install == install and await self._healthy(self._url)
            ):  # fmt: skip
                return self._url
            await self._terminate()
            return await self._start(install, want)

    async def loaded(self) -> dict[str, bool]:
        """Which models are in memory now (`GET /v1/models`)."""
        if not (self.running and self._url):
            return {}
        try:
            r = await self._http.get(f"{self._url}/v1/models")
            return {m["id"]: bool(m.get("loaded")) for m in r.json().get("data", [])}
        except (httpx.HTTPError, ValueError):
            return {}

    def _open_log(self) -> Any:
        self._log_path().parent.mkdir(parents=True, exist_ok=True)
        return self._log_path().open("ab")

    async def _start(self, install: AudioInstall, served: tuple[ServedModel, ...]) -> str:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        config = {
            "host": "127.0.0.1", "port": port,
            "backend": _backend_for(install),
            "lazy_load": True, "max_loaded_models": 1, "busy_timeout_ms": 0,
            "models": [{"id": m.id, "family": m.family, "path": str(m.path), "task": m.task,
                        "mode": "offline"} for m in served],
        }  # fmt: skip
        cfg_dir = Path(tempfile.mkdtemp(prefix="audiocpp-run-"))
        cfg = cfg_dir / "server.json"
        cfg.write_text(json.dumps(config))
        out = await asyncio.to_thread(self._open_log)
        env = dict(os.environ)
        if sys.platform.startswith("linux"):
            env["LD_LIBRARY_PATH"] = (
                str(install.server.parent) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
            )
        try:
            self._proc = await asyncio.create_subprocess_exec(
                str(install.server), "--config", str(cfg), "--no-ui",
                cwd=str(install.server.parent), env=env, stdin=asyncio.subprocess.DEVNULL,
                stdout=out, stderr=asyncio.subprocess.STDOUT,
            )  # fmt: skip
        except OSError as e:
            shutil.rmtree(cfg_dir, ignore_errors=True)
            raise VoiceEngineError(
                "start_failed", "The speech runtime could not be started."
            ) from e
        finally:
            out.close()
        self._served, self.install = served, install
        log.info(
            "started audiocpp_server (pid %s) on %s for %d models", self._proc.pid, url, len(served)
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        try:
            while loop.time() < deadline:
                if self._proc.returncode is not None:
                    break
                if await self._healthy(url):
                    self._url = url
                    return url
                await asyncio.sleep(0.2)
        finally:
            shutil.rmtree(cfg_dir, ignore_errors=True)
        await self._terminate()
        raise VoiceEngineError(
            "start_failed",
            "The speech runtime did not start. See logs/audiocpp-server.log in the app folder.",
        )

    async def _terminate(self) -> None:
        proc, self._proc, self._url, self._served = self._proc, None, None, ()
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
        async with self._lock:
            was = self.running
            await self._terminate()
            return was

    async def close(self) -> None:
        await self.stop()
        await self._http.aclose()

    async def post(
        self, path: str, limit_s: float = REQUEST_TIMEOUT_S, **kw: Any
    ) -> httpx.Response:
        assert self._url, "ensure() first"
        async with httpx.AsyncClient(timeout=limit_s) as http:
            return await http.post(f"{self._url}{path}", **kw)


# ---- the engine products use ---------------------------------------------------------------------


def _friendly(status: int, body: str) -> VoiceEngineError:
    """The runtime's message in words a person can act on. Its text is never shown as it is."""
    low = body.lower()
    if "out of memory" in low or "alloc" in low:
        return VoiceEngineError(
            "out_of_memory",
            "There was not enough memory for this model. "
            "Close other apps or choose a smaller model.",
        )
    if "invalid wav" in low or "only wav" in low:
        return VoiceEngineError("bad_audio", "That audio could not be read. Use a WAV file.")
    if status == 503:
        return VoiceEngineError("busy", "The speech model is busy. Try again in a moment.")
    return VoiceEngineError("engine_failed", "The speech model could not do that. Try again.")


class AudioEngine:
    """`SpeechEngine` over the catalogue (`ModelsService`), the installer and the server."""

    def __init__(
        self,
        data_dir: Path,
        models: Any,
        installer: AudioInstaller,
        server: AudioServer,
        comfy: Any = None,
        lipsync: Any = None,
    ):
        self._data_dir = data_dir
        self._models = models  # ModelsService: catalogue, locate()
        self.installer = installer
        self.server = server
        self.comfy = comfy  # ComfyMusic: the music models the image engine runs (V3b)
        self.lipsync_sidecar = lipsync  # LipSyncSidecar: MuseTalk, an optional component (V5)
        self.slot: Any = None  # the SlotManager; set when the worker is built

    @property
    def models_service(self) -> Any:
        """The catalogue and the downloads (the engine worker fetches models through it)."""
        return self._models

    # ---- state ---------------------------------------------------------------------------

    @property
    def install(self) -> AudioInstall | None:
        return find_install(self._data_dir)

    def _entries(self) -> list[Any]:
        return [e for e in self._models.catalogue.values() if getattr(e, "voice", None)]

    def _present(self, entry: Any) -> Path | None:
        """The model's main file, when everything the entry needs is on this computer."""
        found = [self._models.locate(f) for f in entry.files]
        return found[0] if found and all(found) else None

    def state(self) -> dict[str, Any]:
        inst = self.install
        return {
            "installed": inst is not None, "tag": inst.tag if inst else None,
            "backend": inst.backend if inst else None, "source": inst.source if inst else None,
            "running": self.server.running, "plan": self.installer.plan(),
            "install": self.installer.progress.public(),
        }  # fmt: skip

    def _runtime_ready(self, model: VoiceModel) -> bool:
        """Whether what runs this model is set up: audio.cpp, or the image engine (ComfyUI)."""
        if model.engine == "comfyui":
            return bool(self.comfy is not None and self.comfy.installed)
        if model.engine == "sidecar":
            return bool(self.lipsync_sidecar is not None and self.lipsync_sidecar.installed)
        return self.install is not None

    def models(self, task: str | None = None) -> list[dict[str, Any]]:
        out = []
        for e in self._entries():
            m: VoiceModel = e.voice
            if task and task not in m.tasks:
                continue
            files = self._present(e) is not None
            runtime = self._runtime_ready(m)
            state = "ready" if files and runtime else "needs_runtime" if files else "can_install"
            if (
                not files
                and not runtime
                and m.engine == "audiocpp"
                and self.installer.pin() is None
            ):
                state = "not_available"
            missing = 0 if files else e.total_bytes
            out.append(
                {**m.public(), "state": state, "files_ready": files, "runtime_ready": runtime,
                 "bytes_missing": missing}
            )  # fmt: skip
        return out

    def resolve(self, task: str, model_id: str | None) -> VoiceModel:
        entries = {e.id: e for e in self._entries()}
        if model_id:
            e = entries.get(model_id)
            if e is None or task not in e.voice.tasks:
                raise VoiceEngineError(
                    "unknown_model", "That model is not one this app knows for this."
                )
        else:
            wanted = [x for x in entries.values() if task in x.voice.recommended]
            ready = [x for x in wanted if self._present(x)]
            e = (ready or wanted or [None])[0]
            if e is None:
                raise VoiceEngineError("no_model", "There is no model for this yet.")
        if not self._runtime_ready(e.voice):
            if e.voice.engine == "sidecar":
                raise VoiceEngineError(
                    "runtime_missing",
                    f"{e.voice.title} needs the lip sync engine, which is not set up yet. "
                    "Set it up first.",
                )
            if e.voice.engine == "comfyui":
                raise VoiceEngineError(
                    "runtime_missing",
                    f"{e.voice.title} runs on the image engine, which is not set up yet. "
                    "Set up image generation first.",
                )
            raise VoiceEngineError(
                "runtime_missing", "The speech runtime is not set up yet. Set it up first."
            )
        if self._present(e) is None:
            raise VoiceEngineError(
                "model_missing",
                f"{e.voice.title} is not on this computer yet. Get it in the Model hub.",
            )
        return e.voice

    # ---- running -------------------------------------------------------------------------

    def _served(self) -> list[ServedModel]:
        out = []
        for e in self._entries():
            path = self._present(e)
            if path is not None and e.voice.engine == "audiocpp":
                out.append(ServedModel(e.id, e.voice.family, e.voice.server_task, path))
        return out

    async def _call(self, model: VoiceModel, path: str, **kw: Any) -> tuple[httpx.Response, float]:
        r, load_s, _ = await self._call_held(model, path, None, **kw)
        return r, load_s

    async def _call_held(
        self, model: VoiceModel, path: str, beside_bytes: int | None, **kw: Any
    ) -> tuple[httpx.Response, float, Held]:
        """`_call`, and what the slot did: with `beside_bytes` the model may stay in memory next to
        the chat model (a small speech model, dictation), when the two fit together."""
        install = self.install
        if install is None:
            raise VoiceEngineError("runtime_missing", "The speech runtime is not set up yet.")
        if self.slot is None:
            hold: Any = contextlib.nullcontext()
        elif beside_bytes is None:
            hold = self.slot.hold("audio")
        else:
            hold = self.slot.hold("audio", beside_bytes=beside_bytes)
        async with hold as held:
            url = await self.server.ensure(install, self._served())
            was_loaded = (await self.server.loaded()).get(model.id, False)
            t0 = time.monotonic()
            try:
                r = await self.server.post(path, **kw)
            except asyncio.CancelledError:
                # the server keeps working on a cancelled request: restart it (shielded)
                await asyncio.shield(self.server.stop())
                raise
            except httpx.HTTPError as e:
                await self.server.stop()
                raise VoiceEngineError(
                    "engine_stopped", "The speech runtime stopped. Try again."
                ) from e
            elapsed = time.monotonic() - t0
            del url
        if r.status_code >= 300:
            log.warning("audiocpp %s -> %s %s", path, r.status_code, r.text[:300])
            raise _friendly(r.status_code, r.text)
        return r, (0.0 if was_loaded else elapsed), held or Held()

    async def _synthesize(
        self, model: VoiceModel, body: dict[str, Any], voice: str | None, *, beside: bool = False
    ) -> SpeechResult:
        t0 = time.monotonic()
        r, load_s, held = await self._call_held(
            model, "/v1/audio/speech", self._ram_bytes(model) if beside else None,
            json={"model": model.id, **body},
        )  # fmt: skip
        wav = r.content
        seconds = _wav_seconds(wav)
        if seconds <= 0:
            raise VoiceEngineError("engine_failed", "The speech model returned no audio.")
        rate = _wav_rate(wav) or model.sample_rate
        return SpeechResult(
            wav, rate, seconds, model.id, voice, load_s, time.monotonic() - t0, held.displaced
        )

    async def speak(
        self,
        model: VoiceModel,
        text: str,
        voice: str | None,
        options: dict[str, Any],
        *,
        beside: bool = False,
    ) -> SpeechResult:
        body: dict[str, Any] = {"input": text}
        if voice:
            body["voice"] = voice
        if options:
            body["options"] = options
        return await self._synthesize(model, body, voice, beside=beside)

    async def design(
        self, model: VoiceModel, text: str, description: str, options: dict[str, Any]
    ) -> SpeechResult:
        """Speak in a voice described in words. How the description reaches the model is the
        descriptor's `design.via`: Qwen3-TTS takes it as an option, VoxCPM2 as a bracketed prefix
        and silently ignores the option (docs/spikes/voice-v0.md)."""
        via = model.design.get("via")
        if via == "instruct_option":
            body: dict[str, Any] = {"input": text, "options": {**options, "instruct": description}}
        elif via == "text_prefix":
            body = {"input": f"({description}){text}"}
            if options:
                body["options"] = options
        else:
            raise VoiceEngineError("wrong_task", f"{model.title} cannot make a voice from words.")
        return await self._synthesize(model, body, None)

    async def clone(
        self,
        model: VoiceModel,
        text: str,
        reference: Path,
        reference_text: str | None,
        options: dict[str, Any],
    ) -> SpeechResult:
        """Speak in the voice of a recording that is a file on this computer."""
        if "clone" not in model.tasks:
            raise VoiceEngineError("wrong_task", f"{model.title} cannot clone a voice.")
        body: dict[str, Any] = {"input": text, "voice_ref": str(reference)}
        if reference_text:
            body["reference_text"] = reference_text
        if options:
            body["options"] = options
        return await self._synthesize(model, body, None)

    async def music(self, model: VoiceModel, req: MusicRequest) -> MusicResult:
        """Make music. The shape of the request is the descriptor's (`music.request`): where the
        duration goes, which option carries the lyrics, what an instrumental is called. The
        runtime's default seed is fixed, so one is chosen here when none was asked for."""
        if "music" not in model.tasks:
            raise VoiceEngineError("wrong_task", f"{model.title} does not make music.")
        if model.engine == "comfyui":
            if self.comfy is None:
                raise VoiceEngineError("runtime_missing", "The image engine is not available.")
            hold = self.slot.hold("image") if self.slot is not None else contextlib.nullcontext()
            async with hold:  # ComfyUI's memory is the image engine's: one big model at a time
                return await self.comfy.music(model, req)  # type: ignore[no-any-return]
        rules = model.music["request"]
        options = dict(req.options)
        request: dict[str, Any] = {"text": req.description}
        if rules["duration"] == "top":
            request["duration_seconds"] = req.duration
        else:
            options[rules["duration"].split(":", 1)[1]] = req.duration
        lyrics = req.lyrics
        if req.instrumental and rules.get("instrumental_lyrics"):
            lyrics = rules["instrumental_lyrics"]
        if lyrics and rules.get("lyrics_option"):
            options[rules["lyrics_option"]] = lyrics
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31 - 1)
        request["seed"] = str(seed)
        if options:
            request["options"] = options
        t0 = time.monotonic()
        wait = max(300.0, min(7200.0, req.duration * 40))  # Metal runs music far slower than CUDA
        r, load_s = await self._call(
            model, "/v1/tasks/run", limit_s=wait, json={"model": model.id, "request": request}
        )
        wav = _audio_of_task(r.headers.get("content-type", ""), r.content)
        seconds = _wav_seconds(wav)
        if seconds <= 0:
            raise VoiceEngineError("engine_failed", "The music model returned no audio.")
        rate = _wav_rate(wav) or model.sample_rate
        return MusicResult(wav, rate, seconds, model.id, seed, load_s, time.monotonic() - t0)

    async def music_edit(
        self, model: VoiceModel, req: MusicEditRequest, source: Path
    ) -> MusicResult:
        """Change a clip that is a file on this computer. How a family takes an edit is named by the
        descriptor (`music.request.edit`); the option names are the runtime's (V3 real runs)."""
        recipe = (model.music.get("request") or {}).get("edit")
        if recipe is None:
            raise VoiceEngineError("wrong_task", f"{model.title} cannot change a clip.")
        request: dict[str, Any] = {"text": req.description, "audio": str(source)}
        options = dict(req.options)
        if recipe == "ace_step":
            _ace_edit(req, options)
        else:
            _stable_edit(req, options, request)
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31 - 1)
        request["seed"] = str(seed)
        if options:
            request["options"] = options
        t0 = time.monotonic()
        wait = max(300.0, min(7200.0, (req.source_seconds + (req.extend_s or 0)) * 40))
        r, load_s = await self._call(
            model, "/v1/tasks/run", limit_s=wait, json={"model": model.id, "request": request}
        )
        wav = _audio_of_task(r.headers.get("content-type", ""), r.content)
        seconds = _wav_seconds(wav)
        if seconds <= 0:
            raise VoiceEngineError("engine_failed", "The music model returned no audio.")
        rate = _wav_rate(wav) or model.sample_rate
        return MusicResult(wav, rate, seconds, model.id, seed, load_s, time.monotonic() - t0)

    async def separate(
        self, model: VoiceModel, req: SeparateRequest, source: Path
    ) -> SeparateResult:
        """Split a recording that is a file on this computer (at the model's rate) into stems. The
        separation families refuse any request key but the audio; the stems come back named."""
        if "separate" not in model.tasks:
            raise VoiceEngineError("wrong_task", f"{model.title} does not split music.")
        t0 = time.monotonic()
        wait = max(300.0, min(7200.0, req.source_seconds * 30))
        r, load_s = await self._call(
            model, "/v1/tasks/run", limit_s=wait,
            json={"model": model.id, "request": {"audio": str(source)}},
        )  # fmt: skip
        named = _named_wavs(r.content)
        order = {name: i for i, name in enumerate(model.separate["stems"])}
        stems = tuple(
            Stem(name, wav, _wav_rate(wav) or model.sample_rate, _wav_seconds(wav))
            for name, wav in sorted(named, key=lambda x: order.get(x[0], len(order)))
            if _wav_seconds(wav) > 0
        )
        if not stems:
            raise VoiceEngineError("engine_failed", "The model returned no parts.")
        return SeparateResult(stems, model.id, load_s, time.monotonic() - t0)

    async def convert(
        self, model: VoiceModel, req: ConvertRequest, source: Path, reference: Path
    ) -> SpeechResult:
        """Make the recording at `source` sound like the voice in `reference`. Both are files at the
        rate the model reads (`convert.input_rate`); which request fields carry them is the
        descriptor's."""
        if "convert" not in model.tasks:
            raise VoiceEngineError("wrong_task", f"{model.title} does not change a voice.")
        fields = model.convert["request"]
        request: dict[str, Any] = {
            fields["source"]: str(source),
            fields["reference"]: str(reference),
        }
        options = dict(req.options)
        if req.seed is not None:
            options["seed"] = req.seed
        if options:
            request["options"] = options
        t0 = time.monotonic()
        wait = max(300.0, min(7200.0, req.source_seconds * 30))
        r, load_s = await self._call(
            model, "/v1/tasks/run", limit_s=wait, json={"model": model.id, "request": request}
        )
        wav = _audio_of_task(r.headers.get("content-type", ""), r.content)
        seconds = _wav_seconds(wav)
        if seconds <= 0:
            raise VoiceEngineError("engine_failed", "The voice model returned no audio.")
        rate = _wav_rate(wav) or model.sample_rate
        return SpeechResult(wav, rate, seconds, model.id, None, load_s, time.monotonic() - t0)

    async def speech_edit(
        self, model: VoiceModel, req: SpeechEditRequest, source: Path
    ) -> SpeechResult:
        """Change the words in the recording at `source` (a file at the model's rate). The editing
        model takes the original words with the changes tagged as the text to speak, and the
        recording as an option; it answers a speech request with the edited recording."""
        if "edit" not in model.tasks:
            raise VoiceEngineError("wrong_task", f"{model.title} does not edit speech.")
        options = {**req.options, "template_name": "edit", "source_audio": str(source)}
        if req.seed is not None:
            options["seed"] = req.seed
        t0 = time.monotonic()
        r, load_s = await self._call(
            model, "/v1/audio/speech",
            limit_s=max(300.0, min(3600.0, req.source_seconds * 40)),
            json={"model": model.id, "input": req.instruction, "options": options},
        )  # fmt: skip
        wav = r.content
        seconds = _wav_seconds(wav)
        if seconds <= 0:
            raise VoiceEngineError("engine_failed", "The editing model returned no audio.")
        rate = _wav_rate(wav) or model.sample_rate
        return SpeechResult(wav, rate, seconds, model.id, None, load_s, time.monotonic() - t0)

    async def lipsync(
        self, model: VoiceModel, req: LipSyncRequest, picture: Path, voice: Path
    ) -> LipSyncResult:
        """A video of the face in the picture saying the voice. The sidecar draws the mark."""
        if "lipsync" not in model.tasks:
            raise VoiceEngineError("wrong_task", f"{model.title} does not make talking videos.")
        sidecar = self.lipsync_sidecar
        if sidecar is None or not sidecar.installed:
            raise VoiceEngineError(
                "runtime_missing", "The lip sync engine is not set up yet. Set it up first."
            )
        entry = next(e for e in self._entries() if e.id == model.id)
        files = {f.name: self._models.locate(f) for f in entry.files}
        hold = self.slot.hold("lipsync") if self.slot is not None else contextlib.nullcontext()
        async with hold:  # MuseTalk takes about 12 GB: one big model at a time
            return await sidecar.generate(  # type: ignore[no-any-return]
                model, req, picture, voice, {k: v for k, v in files.items() if v is not None}
            )

    def _ram_bytes(self, model: VoiceModel) -> int:
        """What the model asks for in memory, by the catalogue (about, in bytes)."""
        entry = next((e for e in self._entries() if e.id == model.id), None)
        return int(float(getattr(entry, "approx_ram_gb", 0) or 3) * 1_000_000_000)

    async def transcribe(
        self, model: VoiceModel, wav: bytes, options: dict[str, Any], *, beside: bool = False
    ) -> TranscriptResult:
        t0 = time.monotonic()
        files = {"file": ("audio.wav", wav, "audio/wav")}
        data = {"model": model.id, **{k: str(v) for k, v in options.items()}}
        r, _, held = await self._call_held(
            model, "/v1/audio/transcriptions/details",
            self._ram_bytes(model) if beside else None, files=files, data=data,
        )  # fmt: skip
        try:
            j = r.json()
        except ValueError:
            raise VoiceEngineError(
                "engine_failed", "The model's answer could not be read."
            ) from None
        rate = int(j.get("sample_rate") or 16000)
        words = [(w["word"], w["start_sample"] / rate, w["end_sample"] / rate)
                 for w in j.get("words", [])]  # fmt: skip
        seconds = float(j.get("timing", {}).get("audio_duration_ms", 0)) / 1000
        text = str(j.get("text", ""))
        return TranscriptResult(
            text.strip(), tuple(_segments(words, text)), seconds, model.id,
            time.monotonic() - t0, held.displaced,
        )  # fmt: skip

    async def stop(self) -> bool:
        return await self.server.stop()


def _ace_edit(req: MusicEditRequest, options: dict[str, Any]) -> None:
    """ACE-Step: repaint a part, extend past the end (a repaint that starts at the end), or cover
    (restyle the whole clip). A cover's strength is how much to change; the runtime's share is the
    part of the steps that stay conditioned on the source, so it is the other way round."""
    if req.action == "repaint":
        start, end = req.ranges[0]
        options.update({"route": "repaint", "repainting_start": start, "repainting_end": end})
        if req.strength is not None:
            options["repaint_strength"] = req.strength
    elif req.action == "extend":
        end = req.source_seconds + float(req.extend_s or 0)
        options.update(
            {"route": "repaint", "repainting_start": req.source_seconds, "repainting_end": end}
        )
    else:  # cover
        options["route"] = "cover"
        if req.strength is not None:
            options["audio_cover_strength"] = 1.0 - req.strength


def _seconds_text(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _stable_edit(req: MusicEditRequest, options: dict[str, Any], request: dict[str, Any]) -> None:
    """Stable Audio: inpaint the parts (the runtime takes the starts and ends as two lists), or
    restyle the whole clip from a noisy copy of it. The length of the result is the clip's."""
    if req.action == "inpaint":
        options["audio_input_kind"] = "inpaint_audio"
        options["inpaint_mask_start_seconds"] = ",".join(_seconds_text(a) for a, _ in req.ranges)
        options["inpaint_mask_end_seconds"] = ",".join(_seconds_text(b) for _, b in req.ranges)
    else:  # restyle
        options["audio_input_kind"] = "init_audio"
        if req.strength is not None:
            options["init_noise_level"] = req.strength
    request["duration_seconds"] = req.source_seconds


def _named_wavs(data: bytes) -> list[tuple[str, bytes]]:
    """The named audio files a separation answers with: `named_audio_outputs`, each with an `id`
    and its WAV as base64."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except ValueError:
        raise VoiceEngineError("engine_failed", "The model's answer could not be read.") from None
    out: list[tuple[str, bytes]] = []
    for item in (payload.get("named_audio_outputs") if isinstance(payload, dict) else None) or []:
        try:
            wav = base64.b64decode(str(item.get("audio", "")), validate=False)
        except ValueError:
            continue
        if wav[:4] == b"RIFF" and isinstance(item.get("id"), str):
            out.append((item["id"], wav))
    return out


def _audio_candidates(node: Any):
    if isinstance(node, dict):
        for key in ("audio", "wav", "data", "b64_json", "audio_base64"):
            value = node.get(key)
            if isinstance(value, str):
                yield value.split(",", 1)[-1]
        for value in node.values():
            if isinstance(value, dict | list):
                yield from _audio_candidates(value)
    elif isinstance(node, list):
        for item in node:
            yield from _audio_candidates(item)


def _audio_of_task(content_type: str, data: bytes) -> bytes:
    """WAV bytes from `/v1/tasks/run`: raw audio, or JSON that carries it as base64."""
    if data[:4] == b"RIFF" or content_type.startswith("audio/"):
        return data
    try:
        payload = json.loads(data.decode("utf-8"))
    except ValueError:
        raise VoiceEngineError(
            "engine_failed", "The music model's answer could not be read."
        ) from None
    for candidate in _audio_candidates(payload):
        try:
            decoded = base64.b64decode(candidate, validate=False)
        except ValueError:
            continue
        if decoded[:4] == b"RIFF":
            return decoded
    raise VoiceEngineError("engine_failed", "The music model returned no audio.")


def _wav_rate(wav: bytes) -> int:
    import io
    import wave

    try:
        with wave.open(io.BytesIO(wav)) as w:
            return int(w.getframerate())
    except (wave.Error, EOFError):
        return 0


def _wav_seconds(wav: bytes) -> float:
    import io
    import wave

    try:
        with wave.open(io.BytesIO(wav)) as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError):
        return 0.0


_SENTENCE_END = (".", "!", "?", "…", "。", "！", "？")
_MAX_SEGMENT_S = 12.0


def _segments(
    words: list[tuple[str, float, float]], text: str | None = None
) -> list[TranscriptSegment]:
    """Timed words grouped into sentences (or 12 seconds at most), for reading and subtitles.

    The runtime sometimes joins words it normalised ("is" and "$350,000" come back as one word),
    so when the words add up to the same letters as the full `text`, each segment's text is cut
    from `text` itself, which has the right spaces."""
    groups: list[list[tuple[str, float, float]]] = []
    cur: list[tuple[str, float, float]] = []
    for w in words:
        cur.append(w)
        if w[0].endswith(_SENTENCE_END) or w[2] - cur[0][1] >= _MAX_SEGMENT_S:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    texts = [" ".join(x[0] for x in g) for g in groups]
    if text is not None and "".join(x[0] for g in groups for x in g).replace(" ", "") == "".join(
        text.split()
    ):
        texts = []
        rest = text.strip()
        for g in groups:
            need = len("".join(x[0] for x in g).replace(" ", ""))
            end = taken = 0
            while taken < need and end < len(rest):
                taken += 0 if rest[end].isspace() else 1
                end += 1
            texts.append(rest[:end].strip())
            rest = rest[end:]
    return [TranscriptSegment(g[0][1], g[-1][2], t) for g, t in zip(groups, texts, strict=True)]
