"""A guard for CI: a test run that hangs must end by itself and say where.

A GitHub job that is cancelled loses its log, so a hung `pytest` left nothing to read (the 3D
commit's Python job sat for 45 minutes). Here a thread watches the run. When one test runs over
`WASIFYAI_TEST_TIMEOUT_S` (default 20 minutes), or the whole run over `WASIFYAI_SESSION_TIMEOUT_S`
(default 30), or the process does not exit two minutes after the last test, it writes the test's
name and the stack of every thread to `test-watchdog.txt` in `RUNNER_TEMP` (or
`WASIFYAI_WATCHDOG_FILE`; the workflows print it) and ends the process with status 3.

It is off on a developer's machine: it runs when `CI` is set, or when `WASIFYAI_TEST_WATCHDOG=1`.
"""

import faulthandler
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

PER_TEST_S = int(os.environ.get("WASIFYAI_TEST_TIMEOUT_S", "1200"))
SESSION_S = int(os.environ.get("WASIFYAI_SESSION_TIMEOUT_S", "1800"))
EXIT_S = 120

_state: dict[str, float | str | None] = {
    "test": None,
    "since": 0.0,
    "started": 0.0,
    "finished": None,
}


def _bark(why: str) -> None:
    folder = (
        os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()
    )  # RUNNER_TEMP: a GitHub job's own folder
    path = Path(os.environ.get("WASIFYAI_WATCHDOG_FILE") or Path(folder) / "test-watchdog.txt")
    try:
        with path.open("w") as f:
            f.write(f"WATCHDOG: {why}\n\n")
            f.flush()
            faulthandler.dump_traceback(file=f, all_threads=True)
    except OSError:
        pass
    sys.__stderr__.write(f"\nWATCHDOG: {why}\n")  # type: ignore[union-attr]
    sys.__stderr__.flush()  # type: ignore[union-attr]
    os._exit(3)


def _watch() -> None:
    while True:
        time.sleep(5)
        now = time.monotonic()
        test, since = _state["test"], float(_state["since"] or 0)
        finished = _state["finished"]
        if isinstance(finished, float) and now - finished > EXIT_S:
            _bark(f"the process did not exit {EXIT_S} s after the last test")
        if test and now - since > PER_TEST_S:
            _bark(f"{test} ran for more than {PER_TEST_S} s")
        if now - float(_state["started"] or now) > SESSION_S:
            _bark(f"the run went over {SESSION_S} s (the test running: {test})")


def pytest_configure(config: pytest.Config) -> None:
    if not _enabled():
        return
    _state["started"] = time.monotonic()
    threading.Thread(target=_watch, name="test-watchdog", daemon=True).start()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item):
    _state["test"], _state["since"] = item.nodeid, time.monotonic()
    yield
    _state["test"] = None


def _enabled() -> bool:
    return bool(os.environ.get("CI") or os.environ.get("WASIFYAI_TEST_WATCHDOG"))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _state["finished"] = time.monotonic()
    _state["exitstatus"] = int(exitstatus)


def pytest_unconfigure(config: pytest.Config) -> None:
    """The last hook, after the summary is printed: leave the process now, on CI. Something a test
    leaves behind (a thread nobody joins, a library's exit handler) must not keep a finished run
    from ending."""
    status = _state.get("exitstatus")
    if not _enabled() or status is None:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(int(status))
