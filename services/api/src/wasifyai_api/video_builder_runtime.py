"""The Motion graphics component of the desktop (ADR-0077, stage V1a): the render engine.

    Pins            what is installed: a Node.js build, the Chrome headless shell for Testing and
    the
                    npm packages of `video_builder/package-lock.json`, each with a size and a
                    SHA-256
    VideoBuilderInstaller
                    fetches them after the person saw the size and confirmed it, checks every hash,
                    installs the packages from the lock (integrity hashes, no install scripts) and
                    writes `state.json` last: that is what makes it installed
    find_install    the installed component, when it still matches the pins
    render_env      the environment a render runs in: no telemetry, no skills download, a home
    folder
                    of its own inside the component

Everything lives in `<app data>/components/video-builder/`. Nothing else in the app needs it: with
the
component absent the feature shows one setup card (ADR-0077 decision 3). The sandbox a render runs
in
is `video_builder_sandbox.py`."""

import asyncio
import hashlib
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
from wasifyai_api.components.manifest import PACKAGE_DIR, part_pins

log = logging.getLogger(__name__)

STATE_FILE = "state.json"
MIN_FREE_BYTES = 2_000_000_000
INSTALL_LIMIT_S = 900.0

# set for every process the component starts (V0: the CLI asks npm and GitHub unless told not to,
# and writes `~/.hyperframes` and `~/.cache/hyperframes` outside any per-app folder)
QUIET_ENV = {
    "HYPERFRAMES_NO_TELEMETRY": "1",
    "HYPERFRAMES_SKIP_SKILLS": "1",
    "DO_NOT_TRACK": "1",
    "npm_config_update_notifier": "false",
    "npm_config_fund": "false",
    "npm_config_audit": "false",
    "NO_COLOR": "1",
}


@dataclass(frozen=True)
class Download:
    version: str
    url: str
    size: int
    sha256: str
    licence: str


@dataclass(frozen=True)
class Pins:
    node: Download
    shell: Download
    lock: Path
    lock_sha256: str
    package: Path
    package_sha256: str
    packages_bytes: int
    platforms: tuple[str, ...]


def _download(raw: dict[str, Any], what: str) -> Download:
    url = str(raw["url"])
    digest = str(raw["sha256"]).lower()
    if not url.startswith("https://") or len(digest) != 64:
        raise ValueError(f"the {what} pin needs an https URL and a SHA-256")
    return Download(str(raw["version"]), url, int(raw["size"]), digest, str(raw["licence"]))


def load_pins(path: Path | None = None) -> Pins:
    """Motion graphics' pins: its part in this platform's component manifest (stage F2)."""
    raw = json.loads(path.read_text()) if path is not None else part_pins("video-builder")
    base = path.parent if path is not None else PACKAGE_DIR
    pk = raw["packages"]
    for key in ("lock_sha256", "package_sha256"):
        if len(str(pk[key])) != 64:
            raise ValueError(f"the Motion graphics package pin needs a SHA-256 ({key})")
    return Pins(
        _download(raw["node"], "Node.js"),
        _download(raw["shell"], "browser"),
        base / str(pk["lock"]),
        str(pk["lock_sha256"]).lower(),
        base / str(pk["package"]),
        str(pk["package_sha256"]).lower(),
        int(pk["bytes"]),
        tuple(raw["platforms"]),
    )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class VideoBuilderInstall:
    root: Path
    node: Path  # the node binary
    shell: Path  # the Chrome headless shell binary
    cli: Path  # hyperframes' command line entry (a script run by node)
    app: Path  # where node_modules is (and gsap, copied into each project)
    source: str  # managed | env


def component_root(data_dir: Path) -> Path:
    return data_dir / "components" / "video-builder"


def _layout(root: Path, source: str) -> VideoBuilderInstall:
    return VideoBuilderInstall(
        root=root,
        node=root / "node" / "bin" / "node",
        shell=root / "shell" / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell",
        cli=root / "app" / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs",
        app=root / "app",
        source=source,
    )


def find_install(data_dir: Path, pins: Pins | None = None) -> VideoBuilderInstall | None:
    """The component this app installed, when it still matches the pins; else the copy named by
    `WASIFYAI_VIDEO_BUILDER_HOME` (development and CI); None when there is none."""
    pins = pins or load_pins()
    root = component_root(data_dir)
    try:
        state = json.loads((root / STATE_FILE).read_text())
        found = _layout(root, "managed")
        if (
            state.get("schema") == 1
            and state.get("node") == pins.node.sha256
            and state.get("shell") == pins.shell.sha256
            and state.get("lock_sha256") == pins.lock_sha256
            and found.node.is_file()
            and found.shell.is_file()
            and found.cli.is_file()
        ):
            return found
    except (OSError, ValueError):
        pass
    env = os.environ.get("WASIFYAI_VIDEO_BUILDER_HOME")
    if env:
        home = Path(env).expanduser()
        found = _layout(home, "env")
        if found.node.is_file() and found.shell.is_file() and found.cli.is_file():
            return found
    return None


# HyperFrames needs ffmpeg and ffprobe and brings neither. The component carries its own (two npm
# packages of its lock: `@ffmpeg-installer/<platform>` and `@ffprobe-installer/<platform>`, FFmpeg
# 4.4 builds with libx264, libvpx-vp9, prores_ks and aac); a computer's own (Homebrew's) is the
# fallback for a component set up before they were added. With neither, the screen says so in words.
MEDIA_TOOLS = ("ffmpeg", "ffprobe")
MEDIA_BYTES = 24_100_000  # the two platform packages, part of the packages' size
MEDIA_ENCODERS = ("libx264", "libvpx-vp9", "prores_ks", "aac")  # what the templates' files need
MEDIA_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")
MEDIA_HINT = (
    "Motion graphics needs FFmpeg (with ffprobe) and this copy of it does not have one. "
    "In Terminal run: brew install ffmpeg. Then choose Check again."
)


def bundled_media_tool(install: "VideoBuilderInstall", name: str) -> Path:
    """Where the component's own copy of `name` is, once set up."""
    return install.app / "node_modules" / f"@{name}-installer" / platform_key() / name


def find_media_tools(install: "VideoBuilderInstall | None" = None) -> dict[str, str]:
    """The FFmpeg tools to use: name -> path (only the ones found). The component's own first,
    then the computer's."""
    found: dict[str, str] = {}
    for name in MEDIA_TOOLS:
        own = bundled_media_tool(install, name) if install is not None else None
        path = (
            str(own)
            if own is not None and own.is_file() and os.access(own, os.X_OK)
            else shutil.which(name)
            or next((f"{d}/{name}" for d in MEDIA_DIRS if Path(f"{d}/{name}").is_file()), None)
        )
        if path:
            found[name] = path
    return found


def make_media_tools_executable(install: "VideoBuilderInstall") -> None:
    """The npm packages set the executable bit in an install script, and the component is
    installed without scripts: set it here."""
    for name in MEDIA_TOOLS:
        path = bundled_media_tool(install, name)
        if path.is_file():
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_env(install: VideoBuilderInstall, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a component process runs in. It starts from nothing, not from the person's
    environment: no proxy settings, no tokens, no PATH entries that were not put here."""
    home = install.root / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(home),
        "XDG_CACHE_HOME": str(install.root / "cache"),
        "TMPDIR": str(install.root / "tmp"),
        "PATH": f"{install.node.parent}:/usr/bin:/bin",
        "LANG": "en_US.UTF-8",
        **QUIET_ENV,
    }
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    for name, path in find_media_tools(install).items():  # the ones found, so the render uses these
        env[f"HYPERFRAMES_{name.upper()}_PATH"] = path
    env.update(extra or {})
    return env


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
                pass
        shutil.rmtree(root, ignore_errors=True)
    return freed


# ---- installing it -------------------------------------------------------------------------------


async def _run(
    args: list[str], cwd: Path, env: dict[str, str], limit_s: float = 600
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


class VideoBuilderInstaller:
    """Sets up the component. Nothing is fetched before the person has seen the size and confirmed
    it."""

    def __init__(self, data_dir: Path, pins: Pins | None = None, client_factory: Any = None):
        self._data_dir = data_dir
        self._root = component_root(data_dir)
        self.pins = pins or load_pins()
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60, read=120))
        )
        self.progress = InstallProgress()
        self._task: asyncio.Task[None] | None = None
        self.run: Any = _run  # replaced in tests

    @property
    def supported(self) -> bool:
        return platform_key() in self.pins.platforms

    @property
    def total_bytes(self) -> int:
        return self.pins.node.size + self.pins.shell.size + self.pins.packages_bytes

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def plan(self) -> dict[str, Any]:
        found = find_install(self._data_dir, self.pins)
        return {
            "supported": self.supported,
            "platform": platform_key(),
            "bytes": self.total_bytes if self.supported else 0,
            "parts": [
                {"name": "Node.js", "version": self.pins.node.version, "bytes": self.pins.node.size,
                 "licence": self.pins.node.licence, "source": "nodejs.org"},
                {"name": "Chrome headless shell", "version": self.pins.shell.version,
                 "bytes": self.pins.shell.size, "licence": self.pins.shell.licence,
                 "source": "googleapis.com (Chrome for Testing)"},
                {"name": "HyperFrames and GSAP", "version": "0.8.171 and 3.15.0",
                 "bytes": self.pins.packages_bytes - MEDIA_BYTES,
                 "licence": "Apache-2.0 and the GSAP Standard no charge licence",
                 "source": "registry.npmjs.org"},
                {"name": "FFmpeg and ffprobe", "version": "4.4 and 4.4.1", "bytes": MEDIA_BYTES,
                 "licence": "FFmpeg (a GPL build, run as separate programs)",
                 "source": "registry.npmjs.org"},
            ],
            "found": {"path": str(found.root)}
            if found is not None and found.source == "env"
            else None,
        }  # fmt: skip

    def start(self, confirm_bytes: int) -> None:
        if not self.supported:
            raise InstallError(
                "Motion graphics is not available on this kind of computer yet "
                "(it was measured on Apple-silicon Macs)."
            )
        if confirm_bytes != self.total_bytes:
            raise InstallError("The download changed since it was shown. Look at it again.")
        if self.running:
            raise InstallError("Motion graphics is already being set up.")
        self.progress = InstallProgress("installing", "node", "Starting", 0, self.total_bytes)
        self._task = asyncio.create_task(self._run_install())

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
        except InstallError as e:
            self.progress = InstallProgress("failed", self.progress.step, str(e))
        except Exception:
            log.exception("Motion graphics did not install")
            self.progress = InstallProgress(
                "failed", self.progress.step, "Motion graphics could not be set up. Try again."
            )
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    async def _fetch(self, item: Download, to: Path, step: str, label: str, base: int) -> None:
        """Through the one installer (stage F2): size and SHA-256 checked, else nothing kept."""
        self._say(step, label, base)
        await installer.download(
            installer.Archive(item.url, item.size, item.sha256, "file"), to, step,
            lambda done, _: self._say(step, label, base + done), client=self._client_factory,
        )  # fmt: skip

    async def _install(self, stage: Path) -> None:
        pins = self.pins
        free = await asyncio.to_thread(lambda: shutil.disk_usage(self._root).free)
        if free < self.total_bytes * 2 + MIN_FREE_BYTES:
            raise InstallError("There is not enough free disk space for Motion graphics.")
        if _sha256_file(pins.lock) != pins.lock_sha256 or _sha256_file(pins.package) != (
            pins.package_sha256
        ):
            raise InstallError("The package list shipped with the app does not match its pin.")

        node_tar = stage / "node.tar.gz"
        await self._fetch(pins.node, node_tar, "node", "Getting Node.js", 0)
        shell_zip = stage / "shell.zip"
        await self._fetch(pins.shell, shell_zip, "browser", "Getting the browser", pins.node.size)

        self._say("unpack", "Unpacking", pins.node.size + pins.shell.size)
        node_dir, shell_dir = stage / "node-unpacked", stage / "shell"
        await asyncio.to_thread(installer.unpack, node_tar, "tar.gz", 0, node_dir, "unpack")
        await asyncio.to_thread(installer.unpack, shell_zip, "zip", 0, shell_dir, "unpack")
        tops = [p for p in node_dir.iterdir() if p.is_dir()]
        if len(tops) != 1 or not (tops[0] / "bin" / "node").is_file():
            raise InstallError("The Node.js download did not contain Node.js.")

        # the old install goes first, so a failure never leaves one that looks whole
        for name in (STATE_FILE, "node", "shell", "app"):
            target = self._root / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        shutil.move(str(tops[0]), str(self._root / "node"))
        shutil.move(str(shell_dir), str(self._root / "shell"))
        install = _layout(self._root, "managed")
        if not install.shell.is_file():
            raise InstallError("The browser download did not contain the browser.")
        # a file fetched here carries no quarantine flag, but clear one if it is there (V0: with the
        # flag the browser hangs silently until Gatekeeper is satisfied)
        await self.run(["/usr/bin/xattr", "-dr", "com.apple.quarantine", str(self._root / "shell")],
                       self._root, {}, 60)  # fmt: skip

        app = install.app
        app.mkdir(parents=True)
        shutil.copyfile(pins.package, app / "package.json")
        shutil.copyfile(pins.lock, app / "package-lock.json")
        env = render_env(install)
        env["npm_config_cache"] = str(self._root / "cache" / "npm")
        npm_cli = self._root / "node" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
        self._say(
            "packages", "Installing the packages (a minute)", pins.node.size + pins.shell.size
        )
        ok, text = await self.run(
            [str(install.node), str(npm_cli), "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
            app, env, 600,
        )  # fmt: skip
        if not ok:
            log.error("npm ci failed: %s", text[-800:])
            raise InstallError("The packages for Motion graphics could not be installed.")

        self._say("verify", "Checking that it starts", self.total_bytes - 1)
        ok, text = await self.run([str(install.node), str(install.cli), "--version"], app, env, 120)
        if not ok:
            log.error("the hyperframes check failed: %s", text[-600:])
            raise InstallError("Motion graphics did not start on this computer.")
        make_media_tools_executable(install)  # the packages do this in an install script
        ffmpeg, ffprobe = (bundled_media_tool(install, n) for n in MEDIA_TOOLS)
        ok, text = await self.run([str(ffmpeg), "-hide_banner", "-encoders"], app, env, 60)
        if not ok or any(f" {name} " not in text for name in MEDIA_ENCODERS):
            log.error("the ffmpeg check failed: %s", text[-600:])
            raise InstallError("FFmpeg for Motion graphics did not start on this computer.")
        ok, text = await self.run([str(ffprobe), "-version"], app, env, 60)
        if not ok or "ffprobe version" not in text:
            log.error("the ffprobe check failed: %s", text[-600:])
            raise InstallError("ffprobe for Motion graphics did not start on this computer.")
        ok, text = await self.run([str(install.shell), "--version"], app, env, 60)
        if not ok or "Chrome" not in text:
            log.error("the browser check failed: %s", text[-600:])
            raise InstallError("The browser for Motion graphics did not start on this computer.")
        shutil.rmtree(
            self._root / "cache", ignore_errors=True
        )  # npm's download cache is not needed
        record = {
            "schema": 1,
            "node": pins.node.sha256,
            "shell": pins.shell.sha256,
            "lock_sha256": pins.lock_sha256,
            "node_version": pins.node.version,
            "browser": text.strip()[:80],
        }
        tmp = self._root / (STATE_FILE + ".part")
        tmp.write_text(json.dumps(record))
        tmp.replace(self._root / STATE_FILE)  # last: this is what makes it installed
