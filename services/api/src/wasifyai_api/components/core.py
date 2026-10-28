"""One installer for the optional components (stage F2 of the 2026-10-27 plan).

Every optional part of the engine (the image engine, the language engine, the speech runtime, lip
sync, 3D, Motion graphics, the trainers, the notebooks reader) is set up the same way: nothing is
fetched before the person has seen what it is and how large and has agreed; every download has a
pinned size and SHA-256 and continues where it stopped; an archive is unpacked only inside its own
folder; a Python environment is made from a hashed lock; a check command proves it starts; and the
record that makes it installed (`state.json`) is written last. Each step's lines go to
`<app data>/logs/provision.log`, the file the shell's first-run install writes too.

A component is a `Component`: what it is, its status in the shape the window reads
(`ComponentStatus` in apps/desktop/src/engine.ts), and install, cancel and uninstall. The steps of
an install are `Step`s run in order by `Installer`; `fetch_archive`, `make_environment` and
`run_check` are the steps every component is made of.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import sys
import tarfile
import zipfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

log = logging.getLogger("wasifyai_api.components")

CHUNK = 1 << 20
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")  # a tool's terminal colours, not for the log
PROVISION_LOG = "provision.log"


class InstallError(Exception):
    """`str(e)` is a sentence safe to show; `step` is the step it failed at."""

    def __init__(self, message: str, step: str | None = None):
        super().__init__(message)
        self.step = step


@dataclass(frozen=True)
class Step:
    id: str
    label: str  # what the window shows while it runs: "Getting the language engine"


@dataclass(frozen=True)
class Archive:
    """A pinned download: an archive (`tar.gz`, `tar.xz`, `zip`) or a single file (`file`)."""

    url: str
    size: int
    sha256: str
    kind: str
    strip: int = 0  # leading folders of the archive to drop


@dataclass
class Progress:
    """Where an install is. `public()` is the window's `InstallProgress`."""

    component: str
    steps: Sequence[Step]
    index: int = 0
    done: int | None = None
    total: int | None = None
    detail: str | None = None

    def public(self) -> dict[str, Any]:
        step = self.steps[min(self.index, len(self.steps) - 1)]
        return {
            "component": self.component, "step": step.id, "label": step.label,
            "index": self.index + 1, "count": len(self.steps),
            "bytes_done": self.done, "bytes_total": self.total, "detail": self.detail,
        }  # fmt: skip


def status_unsupported(reason: str) -> dict[str, Any]:
    return {"state": "unsupported", "reason": reason}


def status_missing(needs_bytes: int) -> dict[str, Any]:
    return {"state": "not_installed", "needs_bytes": needs_bytes}


def status_installed(version: str, accelerator: str = "") -> dict[str, Any]:
    return {"state": "installed", "version": version, "accelerator": accelerator}


def status_failed(message: str, step: str | None) -> dict[str, Any]:
    return {"state": "failed", "message": message, "step": step}


class Component(Protocol):
    """An optional part of the engine (stage F2). `status()` is the window's `ComponentStatus`."""

    id: str
    title: str

    def status(self) -> dict[str, Any]: ...

    def install(self, confirm_bytes: int | None, repair: bool = False) -> None:
        """Start setting it up. `confirm_bytes` is the size the person saw (None for a repair,
        which fetches only what is missing); a different size refuses, so nothing is fetched that
        was not shown."""
        ...

    def cancel(self) -> bool: ...

    def uninstall(self) -> int:
        """Take it off the computer; the bytes that came back."""
        ...

    async def wait(self) -> None: ...


Listener = Callable[[str, dict[str, Any]], None]


class Installer:
    """Runs one component's steps as a task, keeps its progress and its last failure, and tells
    listeners (the window, through /desktop/events) whenever its status changes."""

    def __init__(self, component: str, steps: Sequence[Step], log_dir: Path | None = None):
        self.component = component
        self.steps = steps
        self.log_dir = log_dir
        self.progress: Progress | None = None
        self.failed: tuple[str, str | None] | None = None
        self.listeners: list[Listener] = []
        self._task: asyncio.Task[None] | None = None
        self._status: Callable[[], dict[str, Any]] = lambda: {}

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def current(self) -> dict[str, Any] | None:
        """The status while something is happening (an install, or its failure), else None: the
        component then answers from its files."""
        if self.running and self.progress is not None:
            return {"state": "installing", "progress": self.progress.public()}
        if self.failed is not None:
            return status_failed(*self.failed)
        return None

    def start(
        self, work: Callable[["Installer"], Awaitable[None]], status: Callable[[], dict[str, Any]]
    ) -> None:
        if self.running:
            raise InstallError("It is already being set up.")
        self._status = status
        self.failed = None
        self.progress = Progress(self.component, self.steps)
        self._task = asyncio.create_task(self._run(work))
        self._tell()

    def cancel(self) -> bool:
        if not self.running or self._task is None:
            return False
        self._task.cancel()
        return True

    async def wait(self) -> None:
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    def at(self, step: str, detail: str | None = None) -> None:
        """Move to a step (by id)."""
        assert self.progress is not None
        index = next(i for i, s in enumerate(self.steps) if s.id == step)
        self.progress = Progress(self.component, self.steps, index, detail=detail)
        self.line(f"step {step}")
        self._tell()

    def bytes(self, done: int, total: int) -> None:
        if self.progress is not None:
            self.progress.done, self.progress.total = done, total
            self._tell()

    def line(self, text: str) -> None:
        """A line for provision.log (and the progress's detail), without terminal colours."""
        text = ANSI.sub("", text)
        if self.progress is not None and not text.startswith("step "):
            self.progress.detail = text[-200:]
        if self.log_dir is None:
            return
        with contextlib.suppress(OSError):
            self.log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            with (self.log_dir / PROVISION_LOG).open("a", encoding="utf-8") as f:
                f.write(f"{stamp} {self.component}: {text}\n")

    async def _run(self, work: Callable[["Installer"], Awaitable[None]]) -> None:
        step = None
        try:
            await work(self)
        except asyncio.CancelledError:
            step = self.progress.public()["step"] if self.progress else None
            self.failed = ("Stopped. Starting again continues where it stopped.", step)
            self.line("stopped")
        except InstallError as e:
            step = e.step or (self.progress.public()["step"] if self.progress else None)
            self.failed = (str(e), step)
            self.line(f"failed at {step}: {e}")
        except Exception as e:
            log.exception("%s did not set up", self.component)
            step = self.progress.public()["step"] if self.progress else None
            self.failed = ("Setting it up did not work. Try again.", step)
            self.line(f"failed at {step}: {type(e).__name__}: {e}")
        else:
            self.line("installed")
        finally:
            self._task = None
            self._tell()

    def _tell(self) -> None:
        status = self.current() or self._status()
        for fn in list(self.listeners):
            with contextlib.suppress(Exception):
                fn(self.component, status)


# ---- the steps every component is made of ----------------------------------------------------


def free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def folder_bytes(root: Path) -> int:
    total = 0
    if root.is_dir():
        for p in root.rglob("*"):
            with contextlib.suppress(OSError):
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
    return total


def check_disk(root: Path, needs: int, what: str, step: str) -> None:
    """Room for what is fetched and unpacked; what a half-done install already holds counts."""
    root.mkdir(parents=True, exist_ok=True)
    free = free_bytes(root)
    if free + folder_bytes(root) < needs:
        raise InstallError(
            f"{what} needs about {human(needs)} of free space and this drive has {human(free)}. "
            "Free some space and try again.",
            step,
        )


def human(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f} GB"
    return f"{max(1, round(n / 1_000_000))} MB"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


ClientFactory = Callable[[], httpx.AsyncClient]


def default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60, read=120))


async def download(
    pin: Archive,
    dest: Path,
    inst: Installer,
    step: str,
    client: ClientFactory = default_client,
    allow_http: bool = False,
) -> None:
    """Fetch `pin` to `dest`, continuing a partial file, and check its size and SHA-256. A file
    that does not match is removed, so the next try starts clean."""
    if not pin.url.startswith("https://") and not allow_http:
        raise InstallError("Only secure downloads are allowed.", step)
    if await asyncio.to_thread(_matches, dest, pin):
        return  # already here from a stopped install
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.is_file() else 0
    if have > pin.size:
        part.unlink()
        have = 0
    inst.line(f"downloading {pin.url}")
    headers = {"Range": f"bytes={have}-"} if have else {}
    async with client() as http, http.stream("GET", pin.url, headers=headers) as r:
        if r.status_code == 200 and have:  # the server would not continue: start again
            have = 0
            part.unlink(missing_ok=True)
        elif r.status_code not in (200, 206):
            raise InstallError(f"The download failed (HTTP {r.status_code}). Try again.", step)
        with part.open("ab") as f:
            async for chunk in r.aiter_bytes(CHUNK):
                f.write(chunk)
                have += len(chunk)
                if have > pin.size:
                    break
                inst.bytes(have, pin.size)
    if have != pin.size or sha256_of(part) != pin.sha256:
        part.unlink(missing_ok=True)
        raise InstallError("The download did not match its checksum. Try again.", step)
    part.replace(dest)


def _matches(path: Path, pin: Archive) -> bool:
    return path.is_file() and path.stat().st_size == pin.size and sha256_of(path) == pin.sha256


def _lock_problem(lock: Path, lock_sha256: str | None) -> str | None:
    if not lock.is_file():
        return "The package list for this is not part of this build."
    if lock_sha256 and sha256_of(lock) != lock_sha256:
        return "The package list of this build is damaged."
    return None


def unpack(archive: Path, kind: str, strip: int, target: Path, step: str) -> int:
    """Unpack into `target` (made new), dropping `strip` leading folders. Refuses absolute paths,
    `..` and links that leave the folder; keeps executable bits. Returns the number of files."""
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    root = target.resolve()
    count = 0

    def place(name: str) -> Path | None:
        parts = Path(name).parts[strip:]
        if not parts:
            return None
        if Path(name).is_absolute() or ".." in parts:
            raise InstallError("The download contained an unsafe file path.", step)
        dest = (target / Path(*parts)).resolve()
        if dest != root and root not in dest.parents:
            raise InstallError("The download contained an unsafe file path.", step)
        return dest

    if kind == "zip":
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                dest = place(info.filename)
                if dest is None:
                    continue
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    dest.chmod(mode | stat.S_IRUSR)
                count += 1
        return count
    with tarfile.open(archive) as t:
        members = []
        for m in t.getmembers():
            dest = place(m.name)
            if dest is None:
                continue
            m.name = str(dest.relative_to(root))
            if m.islnk() or m.issym():
                # a link must point inside the folder (llama.cpp's archives link its dylibs)
                link = (dest.parent / m.linkname).resolve() if m.issym() else target / m.linkname
                if root not in link.resolve().parents and link.resolve() != root:
                    raise InstallError("The download contained a link outside its folder.", step)
                if m.islnk():
                    m.linkname = str(Path(*Path(m.linkname).parts[strip:]))
            members.append(m)
            count += 0 if m.isdir() else 1
        t.extractall(target, members=members, filter="tar")
    return count


async def fetch_archive(
    inst: Installer,
    pin: Archive,
    downloads: Path,
    into: Path,
    must_have: str,
    step_download: str,
    step_unpack: str | None = None,
    client: ClientFactory = default_client,
    allow_http: bool = False,
) -> None:
    """Download, check and unpack `pin` into `into` (replaced only once the new one is whole)."""
    inst.at(step_download)
    name = pin.url.rsplit("/", 1)[-1].split("?")[0] or "download"
    archive = downloads / f"{into.name}-{name}"
    await download(pin, archive, inst, step_download, client, allow_http)
    step = step_unpack or step_download
    if step_unpack:
        inst.at(step_unpack)
    part = into.with_name(into.name + ".part")
    if pin.kind == "file":
        shutil.rmtree(part, ignore_errors=True)
        part.mkdir(parents=True)
        shutil.copy2(archive, part / must_have)
        (part / must_have).chmod(0o755)
        files = 1
    else:
        files = await asyncio.to_thread(unpack, archive, pin.kind, pin.strip, part, step)
    inst.line(f"unpacked {files} files")
    if not (part / must_have).exists():
        shutil.rmtree(part, ignore_errors=True)
        raise InstallError(f"The download does not contain {must_have}.", step)
    shutil.rmtree(into, ignore_errors=True)
    part.rename(into)
    archive.unlink(missing_ok=True)


Runner = Callable[[list[str], dict[str, str], Path | None], Awaitable[tuple[int, str]]]


async def run_command(
    args: list[str], env: dict[str, str], cwd: Path | None = None
) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, env=env, cwd=cwd, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    try:
        out, _ = await proc.communicate()
    except asyncio.CancelledError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        raise
    return proc.returncode or 0, out.decode(errors="replace")


def clean_env(cache_dir: Path | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a component's tools run in: not the engine's own virtual environment."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "PYTHONHOME"))}
    if cache_dir is not None:
        env["UV_CACHE_DIR"] = str(cache_dir)
    env.update(extra or {})
    return env


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


async def make_environment(
    inst: Installer,
    uv: str,
    python: str,
    venv: Path,
    lock: Path,
    lock_sha256: str | None,
    step_env: str,
    step_packages: str,
    run: Runner = run_command,
    env: dict[str, str] | None = None,
) -> Path:
    """A Python environment of the component's own, from its hashed lock. Returns its python."""
    if (problem := await asyncio.to_thread(_lock_problem, lock, lock_sha256)) is not None:
        raise InstallError(problem, step_packages)
    env = env or clean_env()
    inst.at(step_env)
    shutil.rmtree(venv, ignore_errors=True)
    code, out = await run([uv, "venv", "--python", python, str(venv)], env, None)
    inst.line(out.strip()[-400:])
    if code != 0:
        shutil.rmtree(venv, ignore_errors=True)
        raise InstallError("Its environment could not be made.", step_env)
    py = venv_python(venv)
    inst.at(step_packages)
    code, out = await run(
        [uv, "pip", "install", "--python", str(py), "--require-hashes", "--no-deps",
         "-r", str(lock)],
        env, None,
    )  # fmt: skip
    inst.line(out.strip()[-800:])
    if code != 0:
        shutil.rmtree(venv, ignore_errors=True)
        raise InstallError("Its packages could not be installed. Are you online?", step_packages)
    return py


def write_state(path: Path, record: dict[str, Any]) -> None:
    """The record that makes a component installed: written whole, and last."""
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(record, indent=2))
    part.replace(path)


def read_state(path: Path) -> dict[str, Any] | None:
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


@dataclass
class Registry:
    """The components this engine offers, by id, and who hears when one's status changes (the
    window, through /desktop/events)."""

    components: dict[str, Component] = field(default_factory=dict)
    listeners: list[Listener] = field(default_factory=list)

    def add(self, component: Component, installer: Installer | None = None) -> None:
        self.components[component.id] = component
        if installer is not None:
            installer.listeners.append(self._tell)

    def _tell(self, component: str, status: dict[str, Any]) -> None:
        for fn in list(self.listeners):
            with contextlib.suppress(Exception):
                fn(component, status)
