"""The check: the project's own command, run by the Wasify engine (ADR-0103, decisions 1, 5 to 9).

The check is never run by the Agent Server and never inside a hook. It is a child program of ours,
in **its own process group**, with a time limit. At the limit, on Stop, and when the command itself
has ended, the whole group is stopped, so nothing a test started is left running.

    check = Check("python -m pytest", workspace, output=folder / "check.txt", time_limit_s=600)
    result = await check.run()        # from another task: check.stop()

The result is one of four words, and the rule that matters most is in `_judge`: a check that could
not run is **never** "passed".

- `passed`: the command ended with 0.
- `failed`: it ended with another number. The command, the number and the end of the output are
  what goes back to the agent.
- `could_not_check`: the command is not there or cannot be run, it ran into the time limit, or it
  crashed. `why` says which.
- `not_checked`: it was stopped, or there is no command.

`wrapper` is put in front of the command. It is how the check is run under the sandbox profile
later (`sandbox-exec -f <profile>`); nothing here knows about a sandbox.
"""

import asyncio
import os
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

PASSED, FAILED, NOT_CHECKED, COULD_NOT_CHECK = "passed", "failed", "not_checked", "could_not_check"

# why a check has no verdict
NO_COMMAND = "no_command"  # nothing is set for the workspace
MISSING_COMMAND = "missing_command"  # the shell did not find it, or could not run it
TIME_LIMIT = "time_limit"
CRASHED = "crashed"  # the check was killed by a signal
COULD_NOT_START = "could_not_start"  # the shell or the wrapper itself could not be started
STOPPED = "stopped"

TIME_LIMIT_S = 600.0  # ten minutes (ADR-0103, decision 6)
TAIL_CHARS = 4000  # the end of the output that goes back to the agent
KEEP_HEAD, KEEP_TAIL = 8_000_000, 2_000_000  # of an output longer than both, the middle is dropped
GRACE_S = 0.5  # between asking a group to end and ending it
SHELL = "/bin/sh"
# what a check is given of our own environment unless the caller says otherwise: enough to find
# programs, nothing that could be a key
PASS_ON = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TERM",
)


@dataclass(frozen=True)
class CheckResult:
    result: str  # one of the four words
    command: str
    why: str = ""  # for could_not_check and not_checked
    exit_code: int | None = None
    seconds: float = 0.0
    output_file: Path | None = None  # the full output
    tail: str = ""  # its end

    @property
    def passed(self) -> bool:
        return self.result == PASSED


def plain_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """A cleaned environment for a check."""
    env = {k: os.environ[k] for k in PASS_ON if k in os.environ}
    env.update(extra or {})
    return env


def _judge(code: int) -> tuple[str, str]:
    """An exit code as a result and a reason. Only 0 is a pass."""
    if code == 0:
        return PASSED, ""
    if code in (126, 127):  # the shell's own two numbers: cannot be run, not found
        return COULD_NOT_CHECK, MISSING_COMMAND
    if (
        code < 0 or 128 < code <= 128 + signal.NSIG
    ):  # killed by a signal, seen directly or by the shell
        return COULD_NOT_CHECK, CRASHED
    return FAILED, ""


class Check:
    """One run of a check command. `run` once; `stop` from anywhere, at any time."""

    def __init__(
        self,
        command: str,
        cwd: Path,
        *,
        output: Path,
        time_limit_s: float = TIME_LIMIT_S,
        wrapper: Sequence[str] = (),
        env: Mapping[str, str] | None = None,
    ):
        self.command, self.cwd, self.output = command.strip(), Path(cwd), Path(output)
        self.time_limit_s, self.wrapper = time_limit_s, tuple(wrapper)
        self.env = dict(env) if env is not None else plain_environment()
        self._stop = asyncio.Event()
        self.pgid: int | None = None  # the check's process group, once it has started

    def stop(self) -> None:
        """End the check now. Its result will be "not checked"."""
        self._stop.set()

    async def run(self) -> CheckResult:
        if not self.command:
            return CheckResult(NOT_CHECKED, "", NO_COMMAND)
        if self._stop.is_set():
            return CheckResult(NOT_CHECKED, self.command, STOPPED)
        started = time.monotonic()
        self.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            # A plain child, not asyncio's: asyncio's `wait()` does not return while anything the
            # command started still holds its output open, which is the very case we must end.
            proc = subprocess.Popen(  # noqa: S603, ASYNC220  (the person's own check command)
                [*self.wrapper, SHELL, "-c", self.command],
                cwd=self.cwd,
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # a session and a process group of its own
            )
        except OSError as e:
            self.output.write_text(f"The check could not be started: {e}\n")
            return self._result(COULD_NOT_CHECK, COULD_NOT_START, None, started)
        self.pgid = proc.pid
        assert proc.stdout is not None
        reader = asyncio.StreamReader()
        pipe, _ = await asyncio.get_running_loop().connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), proc.stdout
        )
        keeper = asyncio.ensure_future(_keep(reader, self.output))
        ended = asyncio.ensure_future(asyncio.to_thread(proc.wait))  # ends: we end the group below
        stopped = asyncio.ensure_future(self._stop.wait())
        why = ""
        try:
            done, _ = await asyncio.wait(
                {ended, stopped}, timeout=self.time_limit_s, return_when=asyncio.FIRST_COMPLETED
            )
            if ended not in done:
                why = STOPPED if stopped in done else TIME_LIMIT
        finally:
            # always, also when this task is cancelled: nothing of the check outlives it
            stopped.cancel()
            await asyncio.shield(_end_group(self.pgid, ask_first=not ended.done()))
            try:
                await asyncio.shield(asyncio.wait_for(ended, 5))
                await asyncio.shield(asyncio.wait_for(keeper, 2))
            except (TimeoutError, asyncio.CancelledError):
                keeper.cancel()  # something outside the group still holds the output open
            pipe.close()
        if why == STOPPED:
            return self._result(NOT_CHECKED, STOPPED, None, started)
        if why == TIME_LIMIT:
            return self._result(COULD_NOT_CHECK, TIME_LIMIT, None, started)
        code = proc.returncode if proc.returncode is not None else -1
        result, why = _judge(code)
        return self._result(result, why, code, started)

    def _result(self, result: str, why: str, code: int | None, started: float) -> CheckResult:
        return CheckResult(
            result,
            self.command,
            why,
            code,
            round(time.monotonic() - started, 3),
            self.output,
            _tail(self.output),
        )


async def run_check(
    command: str,
    cwd: Path,
    *,
    output: Path,
    time_limit_s: float = TIME_LIMIT_S,
    wrapper: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
) -> CheckResult:
    """Run a check to its end."""
    check = Check(command, cwd, output=output, time_limit_s=time_limit_s, wrapper=wrapper, env=env)
    return await check.run()


def group_alive(pgid: int) -> bool:
    """Is any process of the group still there?"""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # there, and not ours to signal: it counts as there
    return True


async def _end_group(pgid: int, *, ask_first: bool) -> None:
    """Stop every process of the group: ask (TERM), wait a moment, then end (KILL). When the
    command itself has already ended, what it left behind is ended without asking."""
    if ask_first:
        _signal_group(pgid, signal.SIGTERM)
        until = time.monotonic() + GRACE_S
        while time.monotonic() < until and group_alive(pgid):  # noqa: ASYNC110  (no event to wait on)
            await asyncio.sleep(0.02)
    _signal_group(pgid, signal.SIGKILL)


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass  # nothing left in the group


async def _keep(stream: asyncio.StreamReader, path: Path) -> None:
    """Write the check's output to its file as it comes. An output longer than `KEEP_HEAD` and
    `KEEP_TAIL` together keeps its beginning and its end, with a line between that says so: a
    check that prints for ten minutes must not fill the disk."""
    kept, dropped, tail = 0, 0, bytearray()
    with path.open("wb") as f:
        while chunk := await stream.read(65536):
            if kept < KEEP_HEAD:
                now, chunk = chunk[: KEEP_HEAD - kept], chunk[KEEP_HEAD - kept :]
                f.write(now)
                f.flush()
                kept += len(now)
            if chunk:
                tail += chunk
                if len(tail) > KEEP_TAIL:
                    dropped += len(tail) - KEEP_TAIL
                    del tail[: len(tail) - KEEP_TAIL]
        if dropped:
            f.write(f"\n[... {dropped} bytes of output are not kept ...]\n".encode())
        f.write(tail)


def _tail(path: Path, chars: int = TAIL_CHARS) -> str:
    """The end of an output file, as text."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - chars * 4))  # a character is four bytes at most
            return f.read().decode("utf-8", errors="replace")[-chars:]
    except OSError:
        return ""


# ---- which changed files are tests (decision 9) --------------------------------------------------

TEST_FOLDERS = ("test", "tests", "__tests__", "spec", "specs", "e2e")
TEST_ENDINGS = ("_test", ".test", "-test", "_spec", ".spec", "-spec", "_tests")


def is_test_file(path: str) -> bool:
    """Does this path look like a test, in the way most projects name them? Used only to show the
    person which tests the agent changed; nothing is forbidden by it."""
    p = PurePosixPath(path)
    if any(part.lower() in TEST_FOLDERS for part in p.parts[:-1]):
        return True
    name = p.name.lower()
    stem = name.rsplit(".", 1)[0]
    if name == "conftest.py" or stem.startswith("test_") or stem.endswith(TEST_ENDINGS):
        return True
    # FooTest.java, FooTests.cs, FooSpec.scala: a capital letter starts the last word
    original = p.name.rsplit(".", 1)[0]
    return any(original.endswith(word) and original != word for word in ("Test", "Tests", "Spec"))
