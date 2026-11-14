"""The preview of a project (stage C4; the Preview tab): the project's own "run it" command, started
by the Wasify engine in the project's folder, **inside the same kind of sandbox as the agent's
commands**, and found again by the port it listens on.

    Previews.start     start the command for a session's project; one preview for a session
    Preview.view       where it is: starting, running (with its port), or ended (with why)
    Previews.stop      end it and everything it started

How a running preview is found: we do not ask the program and do not read its words for an
address. We look at which ports the processes under it listen on (`lsof`), from outside the
sandbox. That also says **whether it listens to this computer only** (`127.0.0.1`, `::1`) or to
every address, which other computers on the same network could then reach. The sandbox cannot
forbid the second, so it is said, in words, on the screen.

The program is given `PORT` (a free port chosen here) and `HOST=127.0.0.1`. Most tools follow
them; one that does not is still found by its port.

Nothing it prints is kept on disk. The end of its output is held in memory, for the person and
for the sentence that says why it ended.
"""

import asyncio
import contextlib
import os
import re
import signal
import socket
import subprocess
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

STARTING, RUNNING, ENDED = "starting", "running", "ended"
SHELL = "/bin/sh"
KEPT_LINES = 400
LOOK_EVERY_S = 0.4
FIND_WITHIN_S = 90.0  # after this a preview that listens nowhere says so; it is not stopped
GRACE_S = 0.6
MAX_COMMAND = 2000
LOCAL = ("127.0.0.1", "[::1]", "localhost")

Sandbox = Callable[[Path], Awaitable[tuple[Sequence[str], Mapping[str, str] | None]]]


class PreviewError(Exception):
    """A preview could not be started. `message` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def under(root: int) -> list[int]:
    """`root` and every process below it, from `ps`."""
    try:
        out = subprocess.run(  # noqa: S603
            ["/bin/ps", "-A", "-o", "pid=,ppid="],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return [root]
    children: dict[int, list[int]] = {}
    for row in out.splitlines():
        parts = row.split()
        if len(parts) == 2 and all(x.isdigit() for x in parts):
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, stack = [], [root]
    while stack:
        pid = stack.pop()
        found.append(pid)
        stack.extend(children.get(pid, ()))
    return found


_LISTEN = re.compile(r"TCP (\S+):(\d+) \(LISTEN\)")


def read_listening(lsof: str) -> list[tuple[str, int]]:
    """From `lsof -nP -iTCP -sTCP:LISTEN`: each (address, port) something listens on. The
    address is `*` when it listens on every address."""
    found: dict[tuple[str, int], None] = {}
    for line in lsof.splitlines():
        if m := _LISTEN.search(line):
            found[(m.group(1), int(m.group(2)))] = None
    return list(found)


def listening(pids: Sequence[int]) -> list[tuple[str, int]]:
    """Where the given processes listen, asked of the system from outside the sandbox."""
    if not pids:
        return []
    try:
        out = subprocess.run(  # noqa: S603
            ["/usr/sbin/lsof", "-nP", "-a", "-p", ",".join(str(p) for p in pids),
             "-iTCP", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return []
    return read_listening(out)


def choose(found: Sequence[tuple[str, int]], wanted: int) -> tuple[int, bool] | None:
    """The port to show and whether it is open to other computers: the port we asked for when
    the program took it, else the lowest it listens on."""
    if not found:
        return None
    ports = sorted({port for _, port in found})
    port = wanted if wanted in ports else ports[0]
    wide = any(p == port and address not in LOCAL for address, p in found)
    return port, wide


class Preview:
    def __init__(
        self,
        session_id: str,
        folder: Path,
        command: str,
        proc: "subprocess.Popen[bytes]",
        port: int,
    ):
        self.session_id, self.folder, self.command = session_id, folder, command
        self.pid = proc.pid
        self.wanted = port
        self.port: int | None = None
        self.open_to_network = False
        self.started = time.time()
        self.exit_code: int | None = None
        self.stopped = False
        self.looked_long = False  # it has listened nowhere for `FIND_WITHIN_S`
        self._proc = proc
        self._lines: deque[str] = deque(maxlen=KEPT_LINES)
        self._reading = asyncio.ensure_future(asyncio.to_thread(self._read))
        self._waiting = asyncio.ensure_future(self._wait())
        self._looking = asyncio.ensure_future(self._look())

    def _read(self) -> None:
        out = self._proc.stdout
        if out is None:
            return
        for raw in iter(out.readline, b""):
            self._lines.append(raw.decode("utf-8", "replace").rstrip("\n")[:2000])

    async def _wait(self) -> None:
        code = await asyncio.to_thread(self._proc.wait)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(asyncio.shield(self._reading), 1)
        self.exit_code = code
        self.port = None

    async def _look(self) -> None:
        """Find the port, and go on looking: a tool may move to another port when it starts
        again, and it may begin to listen on every address."""
        began = time.monotonic()
        while self.exit_code is None:
            pids = await asyncio.to_thread(under, self.pid)
            chosen = choose(await asyncio.to_thread(listening, pids), self.wanted)
            if self.exit_code is not None:
                return
            if chosen is not None:
                self.port, self.open_to_network = chosen
            else:
                self.port = None
                self.looked_long = time.monotonic() - began > FIND_WITHIN_S
            await asyncio.sleep(LOOK_EVERY_S if self.port is None else LOOK_EVERY_S * 5)

    @property
    def state(self) -> str:
        if self.exit_code is not None:
            return ENDED
        return RUNNING if self.port is not None else STARTING

    def output(self, lines: int = 60) -> str:
        return "\n".join(list(self._lines)[-lines:])

    def view(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "command": self.command,
            "port": self.port,
            "url": f"http://localhost:{self.port}/" if self.port else "",
            "open_to_network": bool(self.port) and self.open_to_network,
            "listens_nowhere": self.state == STARTING and self.looked_long,
            "started_at": self.started,
            "exit_code": self.exit_code,
            "stopped": self.stopped,
            "output": self.output(),
        }

    async def stop(self) -> None:
        """End the command and everything under it (a tool may start a child in a group of its
        own, so the tree is found first)."""
        self.stopped = self.exit_code is None
        pids = await asyncio.to_thread(under, self.pid)
        if self.exit_code is None:
            with contextlib.suppress(OSError):
                os.killpg(self.pid, signal.SIGTERM)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(self._waiting), GRACE_S)
        for pid in pids:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
        with contextlib.suppress(OSError):
            os.killpg(self.pid, signal.SIGKILL)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._waiting, 3)
        self._looking.cancel()
        await asyncio.gather(self._looking, return_exceptions=True)
        out = self._proc.stdout
        if out is not None:
            with contextlib.suppress(OSError):
                out.close()


class Previews:
    """Every running preview of the app, one for a session. `sandbox` gives, for a project's
    folder, what to put in front of the command and its environment; without one nothing is run."""

    def __init__(self, sandbox: Sandbox | None):
        self._sandbox = sandbox
        self._of: dict[str, Preview] = {}

    def get(self, session_id: str) -> Preview | None:
        return self._of.get(session_id)

    def running(self) -> list[Preview]:
        return [p for p in self._of.values() if p.state != ENDED]

    async def start(self, session_id: str, folder: Path, command: str) -> Preview:
        command = command.strip()
        if not command:
            raise PreviewError("no_command", "Say which command starts this project.")
        if len(command) > MAX_COMMAND or "\0" in command:
            raise PreviewError("bad_command", "That command is too long.")
        if self._sandbox is None:
            raise PreviewError("no_sandbox", "A preview is not available here.")
        await self.stop(session_id)
        wrapper, env = await self._sandbox(folder)
        if not wrapper:
            raise PreviewError("no_sandbox", "A preview is not available here.")  # never outside
        port = await asyncio.to_thread(free_port)
        given = {
            **(env or {}),
            "PORT": str(port),
            "HOST": "127.0.0.1",
            "BROWSER": "none",  # a tool must not try to open a browser of its own
            "FORCE_COLOR": "0",
            "NO_COLOR": "1",
            "CI": "",
        }
        try:
            proc = subprocess.Popen(  # noqa: S603, ASYNC220  (the person's own command, sandboxed)
                [*wrapper, SHELL, "-c", command],
                cwd=folder,
                env=given,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError:
            raise PreviewError("could_not_start", "The preview could not be started.") from None
        made = self._of[session_id] = Preview(session_id, folder, command, proc, port)
        return made

    async def stop(self, session_id: str) -> bool:
        found = self._of.pop(session_id, None)
        if found is None:
            return False
        await found.stop()
        return True

    async def close_all(self) -> None:
        for session_id in list(self._of):
            await self.stop(session_id)


# ---- which command could start a project ---------------------------------------------------------

SCRIPTS = ("dev", "start", "serve", "preview")


def suggest(folder: Path) -> list[dict[str, str]]:
    """The commands that could start this project, the likeliest first, read from its own files.
    Nothing is run and nothing is stored."""
    import json

    found: list[dict[str, str]] = []

    def text(name: str) -> str:
        try:
            return (folder / name).read_text(errors="replace")[:200_000]
        except OSError:
            return ""

    package = text("package.json")
    if package:
        try:
            scripts = json.loads(package).get("scripts") or {}
        except (ValueError, AttributeError):
            scripts = {}
        runner = (
            "pnpm" if (folder / "pnpm-lock.yaml").exists()
            else "yarn" if (folder / "yarn.lock").exists()
            else "npm"
        )  # fmt: skip
        if isinstance(scripts, dict):
            for name in SCRIPTS:
                if scripts.get(name):
                    run = f"{runner} {name}" if name == "start" else f"{runner} run {name}"
                    found.append({"command": run, "why": f'`package.json` has a "{name}" script'})
    if (folder / "manage.py").exists():
        found.append(
            {"command": "python3 manage.py runserver $PORT", "why": "`manage.py` is there"}
        )
    if not found and (folder / "index.html").exists():
        found.append(
            {
                "command": "python3 -m http.server $PORT --bind 127.0.0.1",
                "why": "the folder has an `index.html` and no start script",
            }
        )
    return found
