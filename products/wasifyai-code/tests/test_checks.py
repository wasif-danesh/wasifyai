# ruff: noqa: ASYNC110, ASYNC240  (these tests wait on real files and real processes)
"""The check as a job of ours (ADR-0103, decisions 1, 6, 7), with real child processes."""

import asyncio
import os
import shlex
import sys
import time
from pathlib import Path

import pytest
from wasifyai_code import checks
from wasifyai_code.checks import Check, group_alive, is_test_file, run_check

PY = shlex.quote(sys.executable)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def gone(pid: int, within: float = 3.0) -> bool:
    until = time.monotonic() + within
    while time.monotonic() < until:
        if not alive(pid):
            return True
        await asyncio.sleep(0.02)
    return False


async def read_pid(path: Path, within: float = 5.0) -> int:
    until = time.monotonic() + within
    while time.monotonic() < until:
        if path.is_file() and path.read_text().strip():
            return int(path.read_text())
        await asyncio.sleep(0.02)
    raise AssertionError(f"{path} was never written")


async def test_a_command_that_ends_with_zero_passed_and_its_output_is_kept(tmp_path):
    r = await run_check("echo checking; echo fine", tmp_path, output=tmp_path / "out" / "c.txt")
    assert (r.result, r.why, r.exit_code) == ("passed", "", 0)
    assert r.passed and r.output_file is not None and r.output_file == tmp_path / "out" / "c.txt"
    assert r.output_file.read_text() == "checking\nfine\n" and r.tail == "checking\nfine\n"
    assert r.seconds < 5


async def test_a_command_that_ends_with_another_number_failed_with_the_end_of_its_output(tmp_path):
    script = "import sys; print('x' * 9000); print('AssertionError: 2 != 3'); sys.exit(3)"
    command = f'{PY} -c "{script}"'
    r = await run_check(command, tmp_path, output=tmp_path / "c.txt")
    assert (r.result, r.why, r.exit_code) == ("failed", "", 3)
    assert len(r.tail) == checks.TAIL_CHARS and r.tail.endswith("AssertionError: 2 != 3\n")
    assert r.output_file is not None and r.output_file.stat().st_size > 9000  # the whole of it


async def test_it_runs_in_the_workspace(tmp_path):
    (tmp_path / "here.txt").write_text("x")
    r = await run_check("test -f here.txt && pwd", tmp_path, output=tmp_path.parent / "c.txt")
    assert r.passed and r.tail.strip().endswith(tmp_path.name)


@pytest.mark.parametrize(
    "command",
    ["no-such-program-wasify --version", "./not-there.sh", "cd sub && no-such-program-wasify"],
)
async def test_a_command_that_is_not_there_could_not_check(tmp_path, command):
    (tmp_path / "sub").mkdir()
    r = await run_check(command, tmp_path, output=tmp_path / "c.txt")
    assert (r.result, r.why) == ("could_not_check", "missing_command")
    assert not r.passed


async def test_a_file_that_cannot_be_run_could_not_check(tmp_path):
    (tmp_path / "check.sh").write_text("#!/bin/sh\nexit 0\n")  # not marked as a program
    r = await run_check("./check.sh", tmp_path, output=tmp_path / "c.txt")
    assert (r.result, r.why, r.exit_code) == ("could_not_check", "missing_command", 126)


async def test_no_command_is_not_checked_and_starts_nothing(tmp_path):
    r = await run_check("   ", tmp_path, output=tmp_path / "c.txt")
    assert (r.result, r.why) == ("not_checked", "no_command")
    assert not (tmp_path / "c.txt").exists()


async def test_a_check_that_crashes_could_not_check(tmp_path):
    for command in ("kill -SEGV $$", "sh -c 'kill -KILL $$'; exit $?"):
        r = await run_check(command, tmp_path, output=tmp_path / "c.txt")
        assert (r.result, r.why) == ("could_not_check", "crashed"), command


@pytest.mark.parametrize(
    ("code", "result"),
    [
        (0, "passed"),
        (1, "failed"),
        (2, "failed"),
        (101, "failed"),
        (255, "failed"),
        (126, "could_not_check"),
        (127, "could_not_check"),
        (-9, "could_not_check"),
        (137, "could_not_check"),
        (139, "could_not_check"),
    ],
)
def test_only_zero_is_a_pass(code, result):
    assert checks._judge(code)[0] == result


async def test_at_the_time_limit_the_whole_group_is_stopped(tmp_path):
    """The command starts a child that does not listen to TERM, and a grandchild."""
    script = tmp_path / "slow.sh"
    script.write_text(
        "trap '' TERM\n"
        f"(trap '' TERM; sleep 300 & echo $! > {tmp_path}/grandchild; wait) &\n"
        f"echo $! > {tmp_path}/child\n"
        "echo started\n"
        "wait\n"
    )
    check = Check(f"sh {script}", tmp_path, output=tmp_path / "c.txt", time_limit_s=1.0)
    started = time.monotonic()
    r = await check.run()
    took = time.monotonic() - started

    assert (r.result, r.why, r.exit_code) == ("could_not_check", "time_limit", None)
    assert 1.0 <= took < 1.0 + checks.GRACE_S + 1.5
    assert "started" in r.tail
    assert check.pgid is not None and not group_alive(check.pgid)
    for name in ("child", "grandchild"):
        assert await gone(int((tmp_path / name).read_text())), name


async def test_stop_ends_a_running_check_within_a_second_and_leaves_nothing(tmp_path):
    check = Check(
        f"sleep 300 & echo $! > {tmp_path}/child; echo started; wait",
        tmp_path,
        output=tmp_path / "c.txt",
    )
    running = asyncio.ensure_future(check.run())
    child = await read_pid(tmp_path / "child")
    assert alive(child)

    started = time.monotonic()
    check.stop()
    r = await running

    assert time.monotonic() - started < 1.0
    assert (r.result, r.why) == ("not_checked", "stopped")
    assert await gone(child) and check.pgid is not None and not group_alive(check.pgid)


async def test_a_check_stopped_before_it_starts_runs_nothing(tmp_path):
    check = Check(f"touch {tmp_path}/ran", tmp_path, output=tmp_path / "c.txt")
    check.stop()
    r = await check.run()
    assert (r.result, r.why) == ("not_checked", "stopped") and not (tmp_path / "ran").exists()


async def test_children_a_check_leaves_behind_are_ended_and_do_not_hold_it_up(tmp_path):
    """The command ends with 0 at once, but started something that goes on and keeps the output
    open. The result is the command's; the leftover is gone."""
    command = f"sleep 300 & echo $! > {tmp_path}/child; echo done"
    started = time.monotonic()
    r = await run_check(command, tmp_path, output=tmp_path / "c.txt")
    assert time.monotonic() - started < 3
    assert (r.result, r.exit_code) == ("passed", 0) and r.tail == "done\n"
    assert await gone(int((tmp_path / "child").read_text()))


async def test_cancelling_the_task_also_ends_the_group(tmp_path):
    check = Check(
        f"sleep 300 & echo $! > {tmp_path}/child; wait", tmp_path, output=tmp_path / "c.txt"
    )
    running = asyncio.ensure_future(check.run())
    child = await read_pid(tmp_path / "child")
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert await gone(child)


async def test_a_wrapper_goes_in_front_of_the_command(tmp_path):
    """Where the sandbox goes later: here a stand-in that marks what it starts."""
    r = await run_check(
        'echo "wrapped=$WRAPPED"',
        tmp_path,
        output=tmp_path / "c.txt",
        wrapper=["/usr/bin/env", "WRAPPED=yes"],
    )
    assert r.passed and r.tail == "wrapped=yes\n"


async def test_a_wrapper_that_cannot_start_could_not_check(tmp_path):
    r = await run_check("true", tmp_path, output=tmp_path / "c.txt", wrapper=["/no/such/sandbox"])
    assert (r.result, r.why) == ("could_not_check", "could_not_start")
    assert "could not be started" in r.tail


async def test_the_check_gets_a_cleaned_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-for-the-check")
    r = await run_check('echo "[$ANTHROPIC_API_KEY] [$HOME]"', tmp_path, output=tmp_path / "c.txt")
    assert r.tail == f"[] [{os.environ['HOME']}]\n"
    r = await run_check(
        'echo "$EXTRA"', tmp_path, output=tmp_path / "c.txt", env={"EXTRA": "given"}
    )
    assert r.tail == "given\n"


async def test_a_very_long_output_keeps_its_beginning_and_its_end(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "KEEP_HEAD", 1000)
    monkeypatch.setattr(checks, "KEEP_TAIL", 500)
    command = f"{PY} -c \"print('first line'); print('m' * 200000); print('the last line')\""
    r = await run_check(command, tmp_path, output=tmp_path / "c.txt")
    assert r.output_file is not None
    text = r.output_file.read_text()
    assert text.startswith("first line\n") and text.endswith("the last line\n")
    assert "bytes of output are not kept" in text and len(text) < 1700
    assert r.passed and r.tail.endswith("the last line\n")


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_app.py",
        "test_app.py",
        "pkg/app_test.go",
        "src/app.test.tsx",
        "src/app.spec.ts",
        "src/__tests__/app.js",
        "spec/models/user_spec.rb",
        "src/test/java/AppTest.java",
        "App.Tests/UserTests.cs",
        "conftest.py",
        "tests/data/case.json",
        "e2e/login.ts",
    ],
)
def test_what_counts_as_a_test_file(path):
    assert is_test_file(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/app.py",
        "contest.py",
        "latest.py",
        "src/attest.ts",
        "docs/testing.md",
        "Test.java",
        "protest/app.py",
        "src/inspect.rb",
    ],
)
def test_what_does_not(path):
    assert not is_test_file(path)
