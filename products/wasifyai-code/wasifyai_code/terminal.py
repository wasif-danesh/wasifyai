"""The person's own terminal in a project (stage C3; the Terminal tab).

A real terminal: a shell on a pseudo-terminal, started by the Wasify engine in the project's
folder, **inside the same kind of sandbox as the agent's commands** (the profile template of
`services/coding-engine/`, filled for this one project). So what the person types here can
change only this project, cannot read their other folders, and reaches the network only through
the install proxy, to the package indexes on its list. It is not the agent's terminal: the agent
does not see it, and it is not part of a turn.

    Terminals.open     start a shell for a session's project; gives a `Terminal`
    Terminal.write     what the person typed
    Terminal.resize    the window's size changed
    Terminal.follow    what the shell printed, in order: the kept end first, then as it comes
    Terminal.close     end the shell and everything it started

The shell is started through a few lines of Python (`_LAUNCH`) that make it the leader of a new
session with the pseudo-terminal as its controlling terminal, and then become the command. That
is done in a child of its own and not with a fork of this engine, which has threads.

Nothing typed or printed is kept on disk. The last `KEPT_BYTES` of output are held in memory so
that the tab can be closed and opened again.
"""

import asyncio
import base64
import contextlib
import os
import signal
import struct
import subprocess
import sys
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

KEPT_BYTES = 512 * 1024
MAX_PER_SESSION = 4
MAX_INPUT = 65_536
SHELL = ("/bin/zsh", "-f", "-i")  # -f: no start-up files (its home is the sandbox's, and empty)
PROMPT = "%1~ %# "
OUTPUT, ENDED = "terminal_output", "terminal_ended"
GRACE_S = 0.5

_LAUNCH = """\
import fcntl, os, sys, termios
os.setsid()
fd = os.open(sys.argv[1], os.O_RDWR)
fcntl.ioctl(fd, termios.TIOCSCTTY, 0)
for n in (0, 1, 2):
    os.dup2(fd, n)
if fd > 2:
    os.close(fd)
os.execvp(sys.argv[2], sys.argv[2:])
"""

Sandbox = Callable[[Path], Awaitable[tuple[Sequence[str], Mapping[str, str] | None]]]


class TerminalError(Exception):
    """A terminal could not be opened or used. `message` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _size(fd: int, cols: int, rows: int) -> None:
    # taken here and not at the top: neither module is there on Windows, where this file is still
    # read (the product's routes name it) and no terminal is ever opened
    import fcntl
    import termios

    cols, rows = max(2, min(cols, 500)), max(2, min(rows, 300))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


class Terminal:
    def __init__(
        self, session_id: str, folder: Path, proc: "subprocess.Popen[bytes]", fd: int, slave: int
    ):
        """`slave` is our own hold on the shell's side of the pseudo-terminal. It is kept open
        for as long as the terminal lives: the shell opens that side a moment after it starts,
        and until something holds it open our side reads as closed."""
        self.id = uuid.uuid4().hex
        self.session_id, self.folder = session_id, folder
        self.pid = proc.pid
        self.started = time.time()
        self.exit_code: int | None = None
        self._proc, self._fd, self._slave = proc, fd, slave
        self._kept: deque[tuple[int, bytes]] = deque()
        self._kept_bytes = 0
        self._seq = 0
        self._news = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(fd, self._read)
        self._waiting = asyncio.ensure_future(self._wait())

    # ---- from the shell --------------------------------------------------------------------------

    def _read(self) -> None:
        try:
            data = os.read(self._fd, 65536)
        except OSError:
            data = b""  # the shell is gone
        if not data:
            self._loop.remove_reader(self._fd)
            return
        self._seq += 1
        self._kept.append((self._seq, data))
        self._kept_bytes += len(data)
        while self._kept_bytes > KEPT_BYTES and len(self._kept) > 1:
            self._kept_bytes -= len(self._kept.popleft()[1])
        self._wake()

    def _wake(self) -> None:
        self._news.set()
        self._news = asyncio.Event()

    async def _wait(self) -> None:
        code = await asyncio.to_thread(self._proc.wait)
        await asyncio.sleep(0.05)  # what it printed last is still on its way
        self.exit_code = code
        self._seq += 1
        self._wake()

    @property
    def ended(self) -> bool:
        return self.exit_code is not None

    # ---- from the person -------------------------------------------------------------------------

    def write(self, text: str) -> None:
        if self.ended:
            raise TerminalError("ended", "This terminal has ended.")
        data = text.encode()[:MAX_INPUT]
        try:
            while data:
                data = data[os.write(self._fd, data) :]
        except OSError:
            raise TerminalError("ended", "This terminal has ended.") from None

    def resize(self, cols: int, rows: int) -> None:
        with contextlib.suppress(OSError):
            _size(self._fd, cols, rows)

    async def follow(self, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        """What the shell printed after `after`, as events for the stream; then its end."""
        last = after
        while True:
            news = self._news
            for seq, data in list(self._kept):
                if seq > last:
                    last = seq
                    yield {"event": OUTPUT, "seq": seq, "data": base64.b64encode(data).decode()}
            if self.ended:
                yield {"event": ENDED, "seq": max(last, self._seq), "exit_code": self.exit_code}
                return
            await news.wait()

    def view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "folder": str(self.folder),
            "started_at": self.started,
            "ended": self.ended,
            "exit_code": self.exit_code,
        }

    async def close(self) -> None:
        """End the shell and everything it started. A shell with job control gives every job a
        process group of its own, so the shell's group alone does not reach them: everything
        under the shell is found first, and ended with it."""
        under = await asyncio.to_thread(_under, self.pid)
        if not self.ended:
            with contextlib.suppress(OSError):
                os.killpg(self.pid, signal.SIGHUP)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(self._waiting), GRACE_S)
        for pid in under:  # what is still there, the shell included
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._waiting, 2)
        with contextlib.suppress(OSError, ValueError):
            self._loop.remove_reader(self._fd)
        for fd in (self._fd, self._slave):
            with contextlib.suppress(OSError):
                os.close(fd)


def _under(root: int) -> list[int]:
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


class Terminals:
    """Every open terminal of the app. `sandbox` gives, for a project's folder, what to put in
    front of the shell and its environment; without one no terminal is opened."""

    def __init__(self, sandbox: Sandbox | None):
        self._sandbox = sandbox
        self._open: dict[str, Terminal] = {}

    def of(self, session_id: str) -> list[Terminal]:
        return [t for t in self._open.values() if t.session_id == session_id]

    def get(self, session_id: str, terminal_id: str) -> Terminal:
        found = self._open.get(terminal_id)
        if found is None or found.session_id != session_id:
            raise TerminalError("not_found", "There is no such terminal in this session.")
        return found

    async def open(self, session_id: str, folder: Path, cols: int = 80, rows: int = 24) -> Terminal:
        if self._sandbox is None or sys.platform == "win32":
            raise TerminalError("no_sandbox", "A terminal is not available here.")
        for old in [t for t in self.of(session_id) if t.ended]:
            await self.close(session_id, old.id)
        if len(self.of(session_id)) >= MAX_PER_SESSION:
            raise TerminalError(
                "too_many", f"This session has {MAX_PER_SESSION} terminals open. Close one first."
            )
        wrapper, env = await self._sandbox(folder)
        if not wrapper:
            # never a shell outside a sandbox
            raise TerminalError("no_sandbox", "A terminal is not available here.")
        master, slave = os.openpty()
        try:
            _size(master, cols, rows)
            os.set_blocking(master, False)
            proc = subprocess.Popen(  # noqa: S603, ASYNC220  (the person's own shell, sandboxed)
                [sys.executable, "-I", "-c", _LAUNCH, os.ttyname(slave), *wrapper, *SHELL],
                cwd=folder,
                env={**(env or {}), "PROMPT": PROMPT, "PS1": PROMPT, "TERM": "xterm-256color"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError:
            os.close(master)
            os.close(slave)
            raise TerminalError("could_not_start", "The terminal could not be started.") from None
        made = Terminal(session_id, folder, proc, master, slave)
        self._open[made.id] = made
        return made

    async def close(self, session_id: str, terminal_id: str) -> bool:
        found = self._open.get(terminal_id)
        if found is None or found.session_id != session_id:
            return False
        del self._open[terminal_id]
        await found.close()
        return True

    async def close_session(self, session_id: str) -> None:
        for one in self.of(session_id):
            await self.close(session_id, one.id)

    async def close_all(self) -> None:
        for one in list(self._open.values()):
            await self.close(one.session_id, one.id)
