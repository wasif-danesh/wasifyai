"""The person's terminal (stage C3), without a sandbox: a real shell on a real pseudo-terminal,
with `env` standing where the sandbox would be. What the sandbox holds is checked on the real one
(`services/api/tests/integration/test_coding_session_real.py`)."""

import asyncio
import base64
import os
from pathlib import Path

import pytest
from wasifyai_code.terminal import ENDED, OUTPUT, Terminal, TerminalError, Terminals


async def stands_in(folder: Path):
    return ["/usr/bin/env"], {"PATH": "/usr/bin:/bin", "HOME": str(folder), "MARK": "inside"}


async def printed(terminal: Terminal, until: str, after: int = 0, wait_s: float = 10) -> str:
    """Read what the terminal prints until `until` is in it."""
    seen = ""

    async def read() -> str:
        nonlocal seen
        async for event in terminal.follow(after):
            if event["event"] == OUTPUT:
                seen += base64.b64decode(event["data"]).decode(errors="replace")
                if until in seen:
                    return seen
            if event["event"] == ENDED:
                return seen
        return seen

    try:
        return await asyncio.wait_for(read(), wait_s)
    except TimeoutError:
        raise AssertionError(f"never printed {until!r}; printed {seen!r}") from None


@pytest.fixture
async def terminals():
    made = Terminals(stands_in)
    yield made
    await made.close_all()


async def test_a_shell_runs_what_is_typed_in_the_projects_folder(terminals, tmp_path):
    t = await terminals.open("s1", tmp_path, 100, 30)
    t.write("echo $MARK-$PWD; stty size\n")
    seen = await printed(t, "30 100")
    assert f"inside-{tmp_path}" in seen or f"inside-/private{tmp_path}" in seen
    t.resize(90, 20)
    t.write("stty size\n")
    assert "20 90" in await printed(t, "20 90")
    assert t.view()["ended"] is False and terminals.get("s1", t.id) is t


async def test_ctrl_c_stops_what_runs_and_the_kept_output_is_read_again_from_the_start(
    terminals, tmp_path
):
    t = await terminals.open("s1", tmp_path)
    t.write("sleep 300\n")
    await asyncio.sleep(0.5)
    t.write("\x03")
    t.write("echo after-$((6*7))\n")
    assert "after-42" in await printed(t, "after-42")
    assert "after-42" in await printed(t, "after-42")  # a tab that is opened again


async def test_closing_ends_the_shell_and_what_it_started(terminals, tmp_path):
    t = await terminals.open("s1", tmp_path)
    t.write("sleep 300 &\necho $! > child.pid; echo wrote-$((1+1))\n")
    await printed(t, "wrote-2")
    child = int((tmp_path / "child.pid").read_text())
    assert await terminals.close("s1", t.id) is True
    await asyncio.sleep(0.3)
    assert t.ended
    with pytest.raises(ProcessLookupError):
        os.kill(t.pid, 0)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
    with pytest.raises(TerminalError):
        t.write("x")
    with pytest.raises(TerminalError):
        terminals.get("s1", t.id)


async def test_a_shell_that_exits_says_so_and_a_session_has_a_limit(terminals, tmp_path):
    t = await terminals.open("s1", tmp_path)
    t.write("exit 3\n")
    events = [e async for e in t.follow()]
    assert events[-1]["event"] == ENDED and events[-1]["exit_code"] == 3
    for _ in range(4):  # the ended one is cleared away, four more fit
        await terminals.open("s1", tmp_path)
    with pytest.raises(TerminalError) as no:
        await terminals.open("s1", tmp_path)
    assert no.value.code == "too_many"
    with pytest.raises(TerminalError):
        terminals.get("another-session", terminals.of("s1")[0].id)
    await terminals.close_session("s1")
    assert terminals.of("s1") == []


async def test_no_terminal_without_a_sandbox(tmp_path):
    with pytest.raises(TerminalError):
        await Terminals(None).open("s1", tmp_path)

    async def nothing(folder: Path):
        return [], {}

    with pytest.raises(TerminalError):
        await Terminals(nothing).open("s1", tmp_path)
