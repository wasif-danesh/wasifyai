"""OpenHands' Agent Server as a child of the desktop engine, inside the macOS sandbox (ADR-0101,
ADR-0102; stage C1a of docs/v2-coding-agent-start-plan.md).

The coding engine is an optional part (`wasifyai_api/components/coding.py`): a Python environment
of its own from a hashed lock, and the pinned extensions catalogue, under
`<app data>/engine/coding/`. This module finds it and runs one server:

    CodingServer.ensure_running()   start (or keep) the server, return its address on loopback
    CodingServer.stop()             stop it and everything it started
    CodingServer.request(...)       call it: the only place the session key is put on a call

What holds it (ADR-0102, decisions 2 and 3):

    the sandbox     the whole server runs under `sandbox-exec` with the profile kept in
                    `services/coding-engine/engine.sb.template`, filled in here at every start:
                    writes only to its own state, the workspaces and its terminal folder; the
                    home folder, other disks and the app's own data closed to reading except
                    its own files; the network to this computer only; no signal to, and no
                    start of, a program outside
    a free port     chosen at start on loopback, so a second copy of the app starts beside this one
    a new key       a random session key at every start. It is given to the server in its
                    environment and kept here in memory: not in `state()`, a log, a file or a route
    a clean start   the environment starts empty; its home, its temp folder and its state are
                    under `<app data>/coding/`; its own session, so its own process group
    the stop        the group and every program under it are ended, then its terminal folder
                    in `/tmp` and its temp folder are removed
    the guard       the server holds one end of a pipe from this engine. If the engine goes
                    away without stopping it (a crash, a forced quit), the server ends itself

Without `EXTENSIONS_PATH` the server copies its catalogue from GitHub at run time, which is not
allowed (ADR-0104); it is always set to the pinned copy, and there is no start without one.

The window never talks to this server and never sees its key (ADR-0101, decision 4).
"""

import asyncio
import contextlib
import json
import logging
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

STATE = "state.json"
PROFILE_TEMPLATE = "engine.sb.template"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
LOG_NAME = "coding-server.log"
LOG_KEEP_BYTES = 4 * 1024 * 1024
KEY_HEADER = "X-Session-API-Key"
# The server puts its terminal's sockets in $TMUX_TMPDIR, and a socket's whole path must fit in
# 104 bytes on macOS. No folder under "~/Library/Application Support/<app>" is short enough, so
# this one folder is in /tmp: made here at start, named in the profile, removed at stop.
TERMINAL_ROOT = Path("/tmp")
TERMINAL_PREFIX = "wasify-coding-"
# Where the tools are when they are not in the engine's own environment (git, node, tmux)
TOOL_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
# Closed to reading whatever else is asked: people's folders, other disks, every program's temp
CLOSED = ("/Users", "/Volumes", "/private/var/folders", "/private/tmp")

# What the server is started with in place of `python -m openhands.agent_server`: the same module,
# after a thread that waits for this engine to go away. It is not a change to OpenHands' packages.
GUARD = """\
import os, runpy, shutil, signal, sys, threading, time

fd = int(os.environ.pop("WASIFY_PARENT_FD"))
os.set_inheritable(fd, False)


def watch():
    try:
        while os.read(fd, 1024):
            pass
    except OSError:
        pass
    folder = os.environ.get("TMUX_TMPDIR", "")
    if os.path.basename(folder).startswith("wasify-coding-"):
        shutil.rmtree(folder, ignore_errors=True)
    os.killpg(0, signal.SIGTERM)
    time.sleep(5)
    os.killpg(0, signal.SIGKILL)


threading.Thread(target=watch, daemon=True).start()
runpy.run_module("openhands.agent_server", run_name="__main__", alter_sys=True)
"""


class CodingError(Exception):
    """A failure to start the coding engine. `message` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CodingInstall:
    version: str
    root: Path  # <app data>/engine/coding
    python: Path  # its environment's Python
    extensions: Path  # the pinned catalogue (`EXTENSIONS_PATH`)
    extensions_version: str


def find_install(data_dir: Path) -> CodingInstall | None:
    """The installed coding engine, from the state file its component writes last; None when it
    is absent, damaged or points outside its own folder."""
    root = data_dir / "engine" / "coding"
    try:
        state = json.loads((root / STATE).read_text())
        python = root / str(state["python_path"])
        extensions = (root / str(state["extensions"]["dir"])).resolve()
        # the folder the Python is in: the file itself is a link to the Python it was made with
        inside = (
            root.resolve() in extensions.parents
            and root.resolve() in python.parent.resolve().parents
        )
        if not inside or not python.is_file() or not extensions.is_dir():
            return None
        return CodingInstall(
            str(state["version"]), root, python, extensions, str(state["extensions"]["version"])
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def supported() -> bool:
    """Whether this computer has the sandbox the coding engine must run in (ADR-0102, decision
    10: the Mac only, until the isolation on Windows and Linux is decided)."""
    return sys.platform == "darwin" and Path(SANDBOX_EXEC).is_file()


def developer_bin() -> str | None:
    """Apple's developer tools folder (git, make), when there is one. Their names in /usr/bin
    are stand-ins that look the real program up through a cache in the per-user temp folder,
    which the sandbox closes: each call then takes half a second and prints four errors. With
    the real folder on the path they are never used."""
    found: list[Path] = []
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        out = subprocess.run(
            ["/usr/bin/xcode-select", "-p"], capture_output=True, text=True, timeout=5, check=False
        )
        if out.returncode == 0 and out.stdout.strip():
            found.append(Path(out.stdout.strip()) / "usr" / "bin")
    found.append(Path("/Library/Developer/CommandLineTools/usr/bin"))
    return next((str(f) for f in found if (f / "git").is_file()), None)


# ---- the profile ---------------------------------------------------------------------------------


def _quoted(path: Path) -> str:
    text = str(path)
    if any(c in text for c in '"\\\n\r\0'):
        raise CodingError(
            "bad_path", "A folder name the coding engine would use has a character it cannot hold."
        )
    return f'"{text}"'


def _rules(kind: str, paths: Sequence[Path]) -> str:
    return "\n".join(f"  ({kind} {_quoted(p)})" for p in paths)


def _on_the_way(paths: Sequence[Path]) -> list[Path]:
    """Every folder above `paths`, once: their names must be readable to reach what is open."""
    found: dict[Path, None] = {}
    for path in paths:
        for parent in reversed(path.parents):
            if parent != Path("/"):
                found[parent] = None
    return list(found)


def fill_profile(
    template: str, *, write: Sequence[Path], read_only: Sequence[Path], closed: Sequence[Path]
) -> str:
    """The profile for one start. `write` may be written and read; `read_only` may be read;
    `closed` is closed to reading except for those. Every path must already be resolved (the
    sandbox compares real paths: `/private/tmp`, never `/tmp`)."""
    opened = [*write, *read_only]
    filled = (
        template.replace("{{WRITE}}", _rules("subpath", write))
        .replace("{{CLOSED}}", _rules("subpath", closed))
        .replace("{{OPEN}}", _rules("subpath", opened))
        .replace("{{WAY}}", _rules("literal", _on_the_way(opened)))
    )
    if "{{" in filled:
        raise CodingError("bad_profile", "The coding engine's sandbox profile is damaged.")
    return filled


# ---- the processes -------------------------------------------------------------------------------


async def _tree(root_pid: int) -> list[int]:
    """`root_pid` and every process under it. The server runs each command in a session of its
    own, so the process group alone does not reach them."""
    proc = await asyncio.create_subprocess_exec(
        "ps", "-A", "-o", "pid=,ppid=",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    out, _ = await proc.communicate()
    return _under(root_pid, out.decode())


def _under(root_pid: int, rows: str) -> list[int]:
    """From `ps -A -o pid=,ppid=`: `root_pid` and everything below it."""
    children: dict[int, list[int]] = {}
    for row in rows.splitlines():
        parts = row.split()
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    pids, stack = [], [root_pid]
    while stack:
        pid = stack.pop()
        pids.append(pid)
        stack.extend(children.get(pid, ()))
    return pids


def _signal_all(pgid: int, pids: Sequence[int], sig: int) -> None:
    with contextlib.suppress(OSError):
        os.killpg(pgid, sig)
    for pid in pids:
        with contextlib.suppress(OSError):
            os.kill(pid, sig)


def _alive(pids: Sequence[int]) -> list[int]:
    found = []
    for pid in pids:
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        found.append(pid)
    return found


def process_rss_bytes(pids: Sequence[int]) -> int:
    """The resident memory of `pids` together, 0 when unknown."""
    if not pids:
        return 0
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", ",".join(str(p) for p in pids)],
            capture_output=True, text=True, timeout=3, check=False,
        )  # fmt: skip
        return sum(int(x) for x in out.stdout.split() if x.isdigit()) * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def _resolved(paths: Sequence[Path]) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(Path(os.path.realpath(p)) for p in paths))


class CodingServer:
    def __init__(
        self,
        data_dir: Path,
        files: Path | None,
        startup_timeout_s: float = 90.0,
        *,
        sandbox_exec: str | None = SANDBOX_EXEC,
    ) -> None:
        """`files` is the build's `services/coding-engine` folder (the sandbox profile).
        `sandbox_exec` is None only in unit tests that run the fake server, which starts no
        command; the engine never passes it."""
        self._data_dir = data_dir
        self._files = files
        self._timeout = startup_timeout_s
        self._sandbox_exec = sandbox_exec
        self._proc: asyncio.subprocess.Process | None = None
        self._url: str | None = None
        self._key: str | None = None
        self._guard: int | None = None  # our end of the pipe the server watches
        self._terminal: Path | None = None
        self._workspaces: tuple[Path, ...] = ()
        self._started: float | None = None
        self._start_seconds: float | None = None
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(timeout=5)

    # ---- state -----------------------------------------------------------------------------

    @property
    def run_dir(self) -> Path:
        """What the server may write: its home, its state, its temp folder, the default
        workspace. It is the person's coding work, so removing the part leaves it."""
        return self._data_dir / "coding"

    @property
    def install(self) -> CodingInstall | None:
        return find_install(self._data_dir)

    @property
    def supported(self) -> bool:
        return self._sandbox_exec is None or supported()

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self.running and self._proc is not None else None

    @property
    def url(self) -> str | None:
        return self._url if self.running else None

    @property
    def session_key(self) -> str | None:
        """For code of the Wasify engine that opens the server's live socket (stage C1b). It
        must never be put in an answer, a log or a file."""
        return self._key if self.running else None

    def state(self) -> dict[str, Any]:
        found = self.install
        return {
            "supported": self.supported,
            "installed": found is not None,
            "version": found.version if found else None,
            "extensions": found.extensions_version if found else None,
            "running": self.running,
            "pid": self.pid,
            "port": int(self._url.rsplit(":", 1)[1]) if self.running and self._url else None,
            "workspaces": [str(w) for w in self._workspaces] if self.running else [],
            "start_seconds": self._start_seconds if self.running else None,
        }

    async def memory_bytes(self) -> int:
        """What the server and everything under it hold in memory now."""
        if (pid := self.pid) is None:
            return 0
        return await asyncio.to_thread(process_rss_bytes, await _tree(pid))

    # ---- calling it --------------------------------------------------------------------------

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """One call to the running server, with the session key on it."""
        if self.url is None or self._key is None:
            raise CodingError("not_running", "The coding engine is not running.")
        headers = {**(kwargs.pop("headers", None) or {}), KEY_HEADER: self._key}
        return await self._http.request(method, f"{self.url}{path}", headers=headers, **kwargs)

    async def _healthy(self, url: str) -> bool:
        try:
            r = await self._http.get(f"{url}/ready")
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    # ---- starting ----------------------------------------------------------------------------

    async def ensure_running(self, workspaces: Sequence[Path] = ()) -> str:
        """The address of a running server that may write to `workspaces` (and to its own
        default workspace), starting it, or starting it again when the folders differ."""
        want = await asyncio.to_thread(_resolved, workspaces)
        async with self._lock:
            if self.running and self._url and want == self._workspaces:
                if await self._healthy(self._url):
                    return self._url
            await self._terminate()
            found = self.install
            if found is None:
                raise CodingError(
                    "not_installed",
                    "The coding engine is not set up yet. Set it up in Settings first.",
                )
            return await self._start(found, want)

    async def check(self, found: CodingInstall) -> dict[str, Any]:
        """Start `found` in the sandbox, ask it what it is, stop it: the last step of its setup,
        before the record that makes it installed is written."""
        async with self._lock:
            await self._terminate()
            try:
                await self._start(found, ())
                seconds = self._start_seconds
                r = await self.request("GET", "/server_info")
                if r.status_code != 200:
                    raise CodingError("start_failed", "The coding engine did not answer.")
                return {"version": str(r.json().get("version", "")), "start_seconds": seconds}
            except httpx.HTTPError:
                raise CodingError("start_failed", "The coding engine did not answer.") from None
            finally:
                await self._terminate()

    def _template(self) -> str:
        path = self._files / PROFILE_TEMPLATE if self._files is not None else None
        if path is None or not path.is_file():
            raise CodingError(
                "no_profile",
                "This build carries no sandbox profile for the coding engine, so it will not "
                "be started.",
            )
        return path.read_text()

    def _prepare(self, found: CodingInstall, workspaces: tuple[Path, ...]) -> dict[str, Any]:
        """The folders, the profile and the environment of one start (file work, off the loop)."""
        template = self._template()
        run = Path(os.path.realpath(self.run_dir))
        home, state, tmp, workspace = (run / n for n in ("home", "state", "tmp", "workspace"))
        shutil.rmtree(tmp, ignore_errors=True)  # what an earlier run left
        for folder in (home, state, tmp, workspace):
            folder.mkdir(parents=True, exist_ok=True)
        self._sweep_terminal(run)
        terminal = Path(
            os.path.realpath(tempfile.mkdtemp(prefix=TERMINAL_PREFIX, dir=TERMINAL_ROOT))
        )
        (run / "terminal").write_text(str(terminal))
        root = Path(os.path.realpath(found.root))
        python_home = Path(os.path.realpath(found.python)).parents[1]  # the Python it was made with
        data = Path(os.path.realpath(self._data_dir))
        profile = run / "engine.sb"
        try:
            profile.write_text(
                fill_profile(
                    template,
                    write=[run, *workspaces, terminal],
                    read_only=[root, python_home],
                    closed=[*(Path(c) for c in CLOSED), data],
                )
            )
            profile.chmod(0o600)
        except BaseException:
            self._clean(terminal)
            raise
        # Real paths only: a link inside a closed folder (a data folder that is itself a link to
        # another disk) cannot be followed from inside the sandbox. The Python file is the
        # exception: it is the link that makes the folder an environment.
        venv_bin = Path(os.path.realpath(found.python.parent))
        env = {
            "HOME": str(home),
            "USER": os.environ.get("USER", "user"),
            "LOGNAME": os.environ.get("USER", "user"),
            "LANG": "en_US.UTF-8",
            "TERM": "xterm-256color",
            "SHELL": "/bin/zsh",
            "TMPDIR": str(tmp),
            "TMUX_TMPDIR": str(terminal),
            "PATH": os.pathsep.join(
                [
                    str(venv_bin),
                    *filter(None, [developer_bin()]),
                    *(d for d in TOOL_DIRS if Path(d).is_dir()),
                ]
            ),  # fmt: skip
            # for the programs it starts; its own Python is started isolated (-I) and reads none
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            # nothing is fetched or sent at run time
            "EXTENSIONS_PATH": os.path.realpath(found.extensions),
            "DO_NOT_TRACK": "1",
            "OH_TELEMETRY_CONSENT": "false",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "OPENHANDS_SUPPRESS_BANNER": "1",
            "LOG_JSON": "true",  # one line per record in logs/coding-server.log
            # everything it keeps is under its own state
            "OH_PERSISTENCE_DIR": str(state / "persistence"),
            "OH_CONVERSATIONS_PATH": str(state / "conversations"),
            "OH_BASH_EVENTS_DIR": str(state / "bash-events"),
            "OH_CONVERSATION_WORKTREE_ROOT": str(state / "worktrees"),
            "OPENHANDS_AGENT_SERVER_CONFIG_PATH": str(state / "config.json"),
            "OH_WORKSPACE_PATH": str(workspace),
            "OH_ENABLE_BROWSER": "false",
            "OH_ENABLE_VSCODE": "false",
        }
        return {
            "env": env, "profile": profile, "terminal": terminal, "cwd": state,
            "python": venv_bin / found.python.name,
        }  # fmt: skip

    def _sweep_terminal(self, run: Path) -> None:
        """Remove the terminal folder a run that was not stopped left in /tmp."""
        note = run / "terminal"
        try:
            left = Path(note.read_text().strip())
        except OSError:
            return
        if left.parent == Path(os.path.realpath(TERMINAL_ROOT)) and left.name.startswith(
            TERMINAL_PREFIX
        ):
            shutil.rmtree(left, ignore_errors=True)
        note.unlink(missing_ok=True)

    def _log_path(self) -> Path:
        return self._data_dir / "logs" / LOG_NAME

    def _open_log(self) -> Any:
        path = self._log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            if path.stat().st_size > LOG_KEEP_BYTES:  # one earlier file is kept
                path.replace(path.with_name(LOG_NAME + ".1"))
        return path.open("ab")

    async def _start(self, found: CodingInstall, workspaces: tuple[Path, ...]) -> str:
        if not self.supported:
            raise CodingError(
                "unsupported", "The coding engine is not available for this computer yet."
            )
        began = time.monotonic()
        prepared = await asyncio.to_thread(self._prepare, found, workspaces)
        with socket.socket() as s:  # a free port on loopback
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        key = secrets.token_urlsafe(32)
        read_end, write_end = os.pipe()
        env = {
            **prepared["env"],
            "OH_SESSION_API_KEYS_0": key,
            "OH_SECRET_KEY": secrets.token_urlsafe(32),
            "WASIFY_PARENT_FD": str(read_end),
        }
        sandbox = [self._sandbox_exec, "-f", str(prepared["profile"])] if self._sandbox_exec else []
        args = [
            *sandbox,
            # isolated: no folder of its own state is on its import path, no PYTHON* is read
            str(prepared["python"]), "-I", "-B", "-X", "utf8", "-c", GUARD,
            "--host", "127.0.0.1", "--port", str(port),
        ]  # fmt: skip
        out = await asyncio.to_thread(self._open_log)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args, cwd=str(prepared["cwd"]), env=env, stdin=asyncio.subprocess.DEVNULL,
                stdout=out, stderr=asyncio.subprocess.STDOUT, start_new_session=True,
                pass_fds=(read_end,),
            )  # fmt: skip
        except OSError:
            os.close(write_end)
            shutil.rmtree(prepared["terminal"], ignore_errors=True)
            raise CodingError("start_failed", "The coding engine could not be started.") from None
        finally:
            out.close()
            os.close(read_end)
        self._guard, self._key, self._terminal = write_end, key, prepared["terminal"]
        self._workspaces = workspaces
        log.info("started the coding engine (pid %s) on %s", self._proc.pid, url)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        while loop.time() < deadline:
            if self._proc.returncode is not None:
                break
            if await self._healthy(url):
                self._url, self._started = url, time.time()
                self._start_seconds = round(time.monotonic() - began, 2)
                return url
            await asyncio.sleep(0.25)
        code = self._proc.returncode
        await self._terminate()
        log.error("the coding engine did not start (exit %s); see logs/%s", code, LOG_NAME)
        raise CodingError(
            "start_failed",
            "The coding engine did not start. Repair it in Settings, under Optional parts.",
        )

    # ---- stopping ----------------------------------------------------------------------------

    async def _terminate(self) -> None:
        proc, guard, terminal = self._proc, self._guard, self._terminal
        self._proc = self._url = self._key = self._guard = self._terminal = None
        self._workspaces, self._started, self._start_seconds = (), None, None
        try:
            if proc is not None and proc.returncode is None:
                pids = await _tree(proc.pid)
                # the group first: the server ends its own commands when it is asked to stop
                with contextlib.suppress(OSError):
                    os.killpg(proc.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except TimeoutError:
                    pass
                pids = list(dict.fromkeys([*pids, *await _tree(proc.pid)]))
                _signal_all(proc.pid, pids, signal.SIGKILL)
                await proc.wait()
                for _ in range(20):  # a killed process is gone a moment later
                    if not _alive(pids):
                        break
                    await asyncio.sleep(0.05)
        finally:
            if guard is not None:
                with contextlib.suppress(OSError):
                    os.close(guard)
            await asyncio.to_thread(self._clean, terminal)

    def _clean(self, terminal: Path | None) -> None:
        if terminal is not None:
            shutil.rmtree(terminal, ignore_errors=True)
            (self.run_dir / "terminal").unlink(missing_ok=True)
        shutil.rmtree(self.run_dir / "tmp", ignore_errors=True)

    async def stop(self) -> bool:
        """Stop the server and everything it started. Returns whether one was running."""
        async with self._lock:
            was = self.running
            await self._terminate()
            return was

    def stop_now(self) -> bool:
        """End it at once, without waiting (for code that cannot wait: removing the part)."""
        proc, guard, terminal = self._proc, self._guard, self._terminal
        self._proc = self._url = self._key = self._guard = self._terminal = None
        self._workspaces, self._started, self._start_seconds = (), None, None
        was = proc is not None and proc.returncode is None
        if was and proc is not None:
            rows = subprocess.run(
                ["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, check=False
            ).stdout
            _signal_all(proc.pid, _under(proc.pid, rows), signal.SIGKILL)
        if guard is not None:
            with contextlib.suppress(OSError):
                os.close(guard)
        self._clean(terminal)
        return was

    async def close(self) -> None:
        await self.stop()
        await self._http.aclose()
