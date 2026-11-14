# ruff: noqa: ASYNC110, ASYNC240  (these tests wait on real files and real processes)
"""The implement, check, fix loop (ADR-0103; section 6 of the start plan): every arrow of the turn's
states, against the pretended place, with a real SQLite store, a real git for the checkpoints and
real child processes for the checks.

The project under test is a folder with `value.txt`. Its check passes when the file says "good"."""

import asyncio
import os
import shlex
import sys
import time
from pathlib import Path

import pytest
from wasifyai_code import place as places
from wasifyai_code.checkpoints import CheckpointStore
from wasifyai_code.checks import group_alive
from wasifyai_code.loop import Loop, TurnRunning
from wasifyai_code.place import FakePlace, FakeTurn, PlaceError, scripted

CHECK = 'test "$(cat value.txt)" = good || { echo "value.txt says $(cat value.txt), not good"; exit 1; }'  # noqa: E501


class Rig:
    """A workspace, a store, a pretended place and the loop over them."""

    def __init__(self, tmp: Path, store, me, agent, *, command: str = CHECK, limit_s: int = 600):
        self.tmp, self.store, self.me = tmp, store, me
        self.ws = tmp / "project"
        (self.ws / "tests").mkdir(parents=True)
        (self.ws / "value.txt").write_text("start\n")
        (self.ws / "tests" / "test_a.py").write_text("def test_a(): assert True\n")
        (self.ws / "tests" / "test_b.py").write_text("def test_b(): assert True\n")
        self.workspace = store.add_workspace(
            me,
            str(self.ws),
            name="project",
            check_command=command,
            check_from="person",
            check_limit_s=limit_s,
        )
        self.session = store.add_session(me, self.workspace["id"], title="a session")
        self.place = FakePlace(agent)
        self.events: list[dict] = []
        self.hooks: list = []
        self.loop = Loop(
            self.place,
            store,
            checkpoints=self.checkpoints,
            outputs=tmp / "data" / "check-outputs",
            on_event=self._on_event,
            stop_wait_s=2.0,
        )

    def checkpoints(self, workspace: dict) -> CheckpointStore:
        return CheckpointStore(
            self.tmp / "data" / "checkpoints" / workspace["id"], Path(workspace["path"])
        )

    def _on_event(self, event: dict) -> None:
        self.events.append(event)
        for hook in self.hooks:
            hook(event)

    async def turn(self, request: str = "make it good", **more):
        return await self.loop.run_turn(self.me, self.session["id"], request, **more)

    def stop(self) -> bool:
        return self.loop.stop(self.session["id"])

    # ---- what happened ---------------------------------------------------------------------------

    def states(self, turn_id: str) -> list[str]:
        return [e["state"] for e in self.events if e["kind"] == "turn" and e["turn_id"] == turn_id]

    def turn_row(self, turn_id: str) -> dict:
        return self.store.get_turn(self.me, turn_id)

    def checks(self) -> list[dict]:
        return self.store.list_checks(self.me, session_id=self.session["id"])

    def word(self) -> str:
        return self.store.get_session(self.me, self.session["id"])["result"]

    def sent(self) -> list[str]:
        where = self.store.get_session(self.me, self.session["id"])["place_session"]
        return self.place.sent(where)

    def stops(self) -> int:
        return sum(1 for c in self.place.calls if c[0] == "stop")


@pytest.fixture
def rig(tmp_path, store, me):
    def make(agent, **more) -> Rig:
        return Rig(tmp_path, store, me, agent, **more)

    return make


def writes(value: str):
    async def agent(turn: FakeTurn) -> None:
        turn.write("value.txt", value + "\n")
        turn.say(f"I wrote {value}.")

    return agent


async def answers(turn: FakeTurn) -> None:
    turn.say("It is a file with one word in it.")


async def waits_for_ever(turn: FakeTurn) -> None:
    turn.write("value.txt", "half done\n")
    await asyncio.Event().wait()


# ---- the arrows ----------------------------------------------------------------------------------


async def test_pass(rig):
    r = rig(writes("good"))
    out = await r.turn()

    assert (out.result, out.why, out.rounds, out.needs_you, out.checked) == (
        "passed",
        "",
        1,
        False,
        True,
    )
    assert r.states(out.turn_id) == ["working", "turn_ended", "checking", "done"]
    row = r.turn_row(out.turn_id)
    assert (row["state"], row["result"], row["rounds"], row["needs_you"]) == (
        "done",
        "passed",
        1,
        False,
    )
    assert row["finished_at"] and row["checkpoint_id"]
    assert r.word() == "passed"
    [check] = r.checks()
    assert (check["result"], check["round"], check["exit_code"], check["command"]) == (
        "passed",
        1,
        0,
        CHECK,
    )
    assert check["turn_id"] == out.turn_id and check["seconds"] >= 0
    assert check["tenant_id"] == "t1" and check["product_id"] == "wasifyai-code"
    assert Path(check["output_file"]).is_file()  # the full output is a file, outside the workspace
    assert r.ws not in Path(check["output_file"]).parents
    kinds = [c["kind"] for c in r.store.list_checkpoints(r.me, r.workspace["id"])]
    assert kinds == ["turn", "pass"]  # one before the turn, one of the state that passed
    last_pass = r.store.get_workspace(r.me, r.workspace["id"])["last_pass"]
    assert r.store.get_checkpoint(r.me, last_pass)["kind"] == "pass"
    assert [e["result"] for e in r.events if e["kind"] == "check"] == [
        "passed"
    ]  # one event a check
    assert sorted(p.name for p in r.ws.iterdir()) == ["tests", "value.txt"]  # nothing of ours


async def test_fail_then_pass_and_the_failure_goes_back_to_the_agent(rig):
    r = rig(scripted(writes("nearly"), writes("good")))
    out = await r.turn()

    assert (out.result, out.rounds, out.needs_you) == ("passed", 2, False)
    assert r.states(out.turn_id) == [
        "working",
        "turn_ended",
        "checking",
        "working",
        "turn_ended",
        "checking",
        "done",
    ]
    assert [(c["round"], c["result"], c["exit_code"]) for c in r.checks()] == [
        (1, "failed", 1),
        (2, "passed", 0),
    ]
    request, back = r.sent()
    assert request == "make it good"
    assert f"Command: {CHECK}" in back and "Exit code: 1" in back  # the command, its exit code
    assert "value.txt says nearly, not good" in back  # and the end of its output
    assert "try 1 of 3" in back
    assert r.word() == "passed"


async def test_three_fails_stop_the_turn_and_say_what_still_fails(rig):
    values = iter(["bad one", "bad two", "bad three", "bad four"])

    async def never_right(turn: FakeTurn) -> None:
        turn.write("value.txt", next(values) + "\n")

    r = rig(never_right)
    out = await r.turn()

    assert (out.result, out.why, out.rounds, out.needs_you) == ("failed", "rounds_used", 3, True)
    assert "value.txt says bad three, not good" in out.says
    assert [c["result"] for c in r.checks()] == ["failed", "failed", "failed"]
    assert len(r.sent()) == 3  # the request and two failures; nothing after the third
    assert not r.place.running(
        r.sent() and r.store.get_session(r.me, r.session["id"])["place_session"]
    )
    row = r.turn_row(out.turn_id)
    assert (row["result"], row["needs_you"], row["rounds"]) == ("failed", True, 3)
    assert r.word() == "failed"
    assert (
        r.store.get_workspace(r.me, r.workspace["id"])["last_pass"] is None
    )  # no pass was written


async def test_the_person_can_ask_for_another_try_which_starts_a_new_count(rig):
    values = iter(["bad one", "bad two", "bad three", "bad four", "good"])

    async def right_on_the_fifth(turn: FakeTurn) -> None:
        turn.write("value.txt", next(values) + "\n")

    r = rig(right_on_the_fifth)
    first = await r.turn()
    second = await r.turn("try again")

    assert (first.result, first.rounds) == ("failed", 3)
    assert (second.result, second.rounds) == ("passed", 2)
    assert [c["round"] for c in r.checks()] == [1, 2, 3, 1, 2]


async def test_a_time_limit_is_could_not_check_never_passed(rig):
    r = rig(writes("good"), command=f"echo $$ > {os.devnull}; sleep 300", limit_s=1)
    started = time.monotonic()
    out = await r.turn()

    assert time.monotonic() - started < 6
    assert (out.result, out.why, out.needs_you, out.rounds) == (
        "could_not_check",
        "time_limit",
        True,
        1,
    )
    [check] = r.checks()
    assert (check["result"], check["why"], check["exit_code"]) == (
        "could_not_check",
        "time_limit",
        None,
    )
    assert r.word() == "could_not_check"
    assert len(r.sent()) == 1  # a check that could not run sends nothing back to the agent


async def test_a_missing_command_is_could_not_check(rig):
    r = rig(writes("good"), command="no-such-test-runner-wasify --all")
    out = await r.turn()

    assert (out.result, out.why, out.needs_you) == ("could_not_check", "missing_command", True)
    assert "not found" in out.says
    assert r.word() == "could_not_check" and len(r.sent()) == 1


async def test_no_command_is_not_checked_and_says_so(rig):
    r = rig(writes("good"), command="")
    out = await r.turn()

    assert (out.result, out.why, out.rounds, out.needs_you) == (
        "not_checked",
        "no_command",
        0,
        False,
    )
    assert r.checks() == [] and r.word() == "not_checked"
    assert r.states(out.turn_id) == ["working", "turn_ended", "done"]


async def test_the_step_limit_is_not_checked_whatever_was_changed(rig):
    async def too_many_steps(turn: FakeTurn) -> None:
        turn.write("value.txt", "good\n")
        for n in range(100):
            turn.step("terminal", command=f"echo {n}")

    r = rig(too_many_steps)
    out = await r.turn()

    assert (out.result, out.why, out.rounds) == ("not_checked", "step_limit", 0)
    assert (r.ws / "value.txt").read_text() == "good\n"  # it would have passed; it was not run
    assert r.checks() == [] and r.word() == "not_checked"
    assert r.states(out.turn_id) == ["working", "turn_ended", "done"]


# ---- when the check runs: only when the turn changed files (decision 4) --------------------------


async def test_a_question_in_a_workspace_whose_check_fails_is_answered_and_nothing_runs(rig):
    r = rig(answers)
    before = (r.ws / "value.txt").read_text()
    out = await r.turn("what is value.txt?")

    assert (out.result, out.why, out.rounds, out.checked) == ("", "no_change", 0, False)
    assert r.checks() == [] and r.word() == ""  # no word yet: nothing was ever checked
    assert (r.ws / "value.txt").read_text() == before and len(r.sent()) == 1
    assert r.states(out.turn_id) == ["working", "turn_ended", "done"]


async def test_no_change_since_the_last_pass_the_last_result_stands(rig):
    r = rig(scripted(writes("good"), answers))
    first = await r.turn()
    second = await r.turn("and what does it say now?")

    assert first.result == "passed"
    assert (second.result, second.why, second.rounds) == ("passed", "no_change", 0)
    assert len(r.checks()) == 1 and r.word() == "passed"
    assert r.turn_row(second.turn_id)["result"] == "passed"


async def test_a_question_after_a_failed_turn_does_not_run_the_check_again(rig):
    async def wrong(turn: FakeTurn) -> None:
        turn.write("value.txt", f"bad {turn.number}\n")

    r = rig(scripted(wrong, wrong, wrong, answers))
    first = await r.turn()
    second = await r.turn("why does it fail?")

    assert (first.result, first.rounds) == ("failed", 3)
    assert (second.result, second.why, second.rounds) == ("failed", "no_change", 0)
    assert len(r.checks()) == 3 and r.word() == "failed" and len(r.sent()) == 4


async def test_files_brought_back_to_what_passed_need_no_check(rig):
    r = rig(scripted(writes("good"), writes("good")))
    await r.turn()
    (r.ws / "value.txt").write_text("the person broke it\n")  # between turns, by hand
    out = await r.turn("put it back")

    assert (out.result, out.why, out.rounds) == ("passed", "same_as_last_pass", 0)
    assert len(r.checks()) == 1


async def test_an_agent_that_changes_nothing_after_a_failure_ends_the_turn_as_failed(rig):
    r = rig(scripted(writes("bad"), answers))
    out = await r.turn()

    assert (out.result, out.why, out.rounds, out.needs_you) == (
        "failed",
        "no_change_after_failure",
        1,
        True,
    )
    assert "value.txt says bad, not good" in out.says and len(r.checks()) == 1


# ---- Stop, in each state -------------------------------------------------------------------------


async def test_stop_while_the_agent_works(rig):
    r = rig(waits_for_ever)
    running = asyncio.ensure_future(r.turn())
    while not r.place.calls or not any(c[0] == "send" for c in r.place.calls):
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)

    started = time.monotonic()
    assert r.stop() is True
    out = await running

    assert time.monotonic() - started < 1.0
    assert (out.result, out.why, out.rounds) == ("not_checked", "stopped", 0)
    assert r.stops() == 1 and r.checks() == [] and r.word() == "not_checked"
    assert r.states(out.turn_id) == ["working", "turn_ended", "done"]
    assert r.stop() is False  # nothing is running any more


async def test_stop_when_the_turn_has_just_ended(rig):
    r = rig(writes("good"))
    r.hooks.append(lambda e: e.get("state") == "turn_ended" and r.stop())
    out = await r.turn()

    assert (out.result, out.why, out.rounds) == ("not_checked", "stopped", 0)
    assert r.checks() == [] and r.stops() == 1
    assert r.states(out.turn_id) == ["working", "turn_ended", "done"]


async def test_stop_while_the_check_runs_ends_it_within_a_second_with_nothing_left(rig, tmp_path):
    marker = tmp_path / "check-started"
    r = rig(writes("good"), command=f"sleep 300 & echo $! > {marker}; wait")
    running = asyncio.ensure_future(r.turn())
    while not (marker.is_file() and marker.read_text().strip()):
        await asyncio.sleep(0.01)
    child = int(marker.read_text())
    assert r.events[-1]["state"] == "checking"

    started = time.monotonic()
    assert r.stop() is True
    out = await running

    assert time.monotonic() - started < 1.0
    assert (out.result, out.why, out.rounds) == ("not_checked", "stopped", 1)
    [check] = r.checks()
    assert (check["result"], check["why"]) == ("not_checked", "stopped")
    assert r.stops() == 1  # Stop also interrupts the place
    until = time.monotonic() + 3
    while time.monotonic() < until and group_alive(child):
        await asyncio.sleep(0.02)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
    assert r.word() == "not_checked"


async def test_stop_while_the_agent_fixes_after_a_failure(rig):
    r = rig(scripted(writes("bad"), waits_for_ever))
    r.hooks.append(
        lambda e: (
            e.get("state") == "working"
            and e.get("round") == 1
            and asyncio.get_running_loop().call_later(0.1, r.stop)
        )
    )
    out = await r.turn()

    assert (out.result, out.why, out.rounds) == ("not_checked", "stopped", 1)
    assert [c["result"] for c in r.checks()] == ["failed"]


async def test_a_second_turn_while_one_runs_is_refused(rig):
    r = rig(waits_for_ever)
    running = asyncio.ensure_future(r.turn())
    await asyncio.sleep(0.2)
    with pytest.raises(TurnRunning):
        await r.turn("another")
    r.stop()
    await running


# ---- the rest of the rules -----------------------------------------------------------------------


async def test_a_check_that_leaves_children_behind(rig, tmp_path):
    marker = tmp_path / "left-behind"
    r = rig(writes("good"), command=f"sleep 300 & echo $! > {marker}; {CHECK}")
    out = await r.turn()

    assert out.result == "passed"
    child = int(marker.read_text())
    until = time.monotonic() + 3
    while time.monotonic() < until:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.02)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


async def test_changed_and_deleted_test_files_are_listed_and_new_ones_are_not(rig):
    async def bends_the_tests(turn: FakeTurn) -> None:
        turn.write("value.txt", "good\n")
        turn.write("tests/test_a.py", "def test_a(): assert True  # was stricter\n")
        turn.delete("tests/test_b.py")
        turn.write("tests/test_new.py", "def test_new(): assert True\n")
        turn.write("notes.md", "not a test\n")

    r = rig(bends_the_tests)
    out = await r.turn()

    assert out.result == "passed"  # we do not forbid it; we show it
    assert out.changed_tests == ("tests/test_a.py", "tests/test_b.py")
    assert r.checks()[0]["changed_tests"] == ["tests/test_a.py", "tests/test_b.py"]


async def test_an_error_or_a_refusal_is_not_checked(rig):
    async def breaks(turn: FakeTurn) -> None:
        turn.write("value.txt", "good\n")
        raise RuntimeError("the model did not answer")

    async def refuses(turn: FakeTurn) -> str:
        return places.REFUSED

    r = rig(scripted(breaks, refuses))
    first = await r.turn()
    second = await r.turn("something it will not do")

    assert (first.result, first.why, first.says) == (
        "not_checked",
        "error",
        "the model did not answer",
    )
    assert (second.result, second.why) == ("not_checked", "refused")
    assert r.checks() == []


async def test_a_place_that_fails_ends_the_turn_as_not_checked(rig):
    class Broken(FakePlace):
        async def send(self, session: str, text: str, *, run: bool = True) -> None:
            raise PlaceError("the engine is not running")

    r = rig(answers)
    r.loop.place = r.place = Broken()
    out = await r.turn()

    assert (out.result, out.why, out.says) == ("not_checked", "error", "the engine is not running")
    assert r.turn_row(out.turn_id)["state"] == "done" and not r.loop.running(r.session["id"])


async def test_a_scheduled_run_has_nobody_to_ask_a_question_is_refused_and_written_down(rig):
    async def asks_first(turn: FakeTurn) -> None:
        allowed = await turn.confirm("rm -rf build")
        turn.write("value.txt", "good\n" if not allowed else "it was allowed\n")

    r = rig(asks_first)
    out = await r.turn("the nightly tidy", unattended=True)

    assert out.result == "passed"  # the same function, the same rows
    [answer] = [c for c in r.place.calls if c[0] == "answer"]
    assert answer[3] is False and "scheduled run" in answer[4]
    assert r.turn_row(out.turn_id)["notes"] == ["Refused, nobody to ask: rm -rf build"]
    [start] = [c for c in r.place.calls if c[0] == "start"]
    assert start[2].unattended is True and start[2].workspace == r.ws
    assert [c["kind"] for c in r.store.list_checkpoints(r.me, r.workspace["id"])] == [
        "turn",
        "pass",
    ]


async def test_in_a_chat_a_question_waits_for_the_person(rig):
    async def asks_first(turn: FakeTurn) -> None:
        if await turn.confirm("rm -rf build"):
            turn.write("value.txt", "good\n")

    r = rig(asks_first)
    running = asyncio.ensure_future(r.turn())
    where = None
    while where is None or not r.place.events(where, places.CONFIRM):
        await asyncio.sleep(0.01)
        where = r.store.get_session(r.me, r.session["id"])["place_session"]
    assert not running.done()
    [ask] = r.place.events(where, places.CONFIRM)
    await r.place.answer(where, ask.data["id"], True)
    out = await running

    assert out.result == "passed" and r.turn_row(out.turn_id)["notes"] == []


async def test_a_turn_can_be_undone_from_its_checkpoint_row(rig):
    r = rig(writes("good"))
    out = await r.turn()
    row = r.store.get_checkpoint(r.me, r.turn_row(out.turn_id)["checkpoint_id"])

    r.checkpoints(r.workspace).undo(row["commit_id"])

    assert (r.ws / "value.txt").read_text() == "start\n"


async def test_when_no_checkpoint_can_be_taken_the_turn_goes_on_says_so_and_is_still_checked(rig):
    r = rig(writes("good"))
    r.loop._checkpoints = lambda w: CheckpointStore(
        r.tmp / "cp", Path(w["path"]), git="no-such-git"
    )
    out = await r.turn()

    assert (out.result, out.rounds) == ("passed", 1)
    notes = r.turn_row(out.turn_id)["notes"]
    assert [n.split(":")[0] for n in notes] == [
        "No checkpoint could be taken (turn)",  # so the turn cannot be undone, and it says so
        "No checkpoint could be taken (pass)",
    ]
    assert r.turn_row(out.turn_id)["checkpoint_id"] is None


async def test_the_check_can_be_run_outside_a_turn(rig):
    r = rig(answers)
    row = await r.loop.check_now(r.me, r.session["id"])
    assert (row["result"], row["turn_id"], row["round"]) == (
        "failed",
        None,
        0,
    ) and r.word() == "failed"

    (r.ws / "value.txt").write_text("good\n")
    row = await r.loop.check_now(r.me, r.session["id"])
    assert row["result"] == "passed" and r.word() == "passed"
    assert r.store.get_workspace(r.me, r.workspace["id"])["last_pass"]


async def test_a_wrapper_and_an_environment_reach_every_check(rig):
    r = rig(writes("anything"), command='test "$WRAPPED" = yes && test "$GIVEN" = here')
    r.loop.wrapper, r.loop.env = (
        ("/usr/bin/env", "WRAPPED=yes"),
        {"GIVEN": "here", "PATH": os.environ["PATH"]},
    )
    assert (await r.turn()).result == "passed"


async def test_the_reviews_case_with_a_real_test_runner(rig):
    """The case the review of the test app ran (ADR-0103, context): a project with an old bug, a
    request that adds a function, a check that covers both. One failure goes back, one fix, one
    pass, and the test file is not touched. The agent is pretended; pytest and its failure are
    real."""
    command = f"{shlex.quote(sys.executable)} -B -m pytest -q -p no:cacheprovider"

    async def adds_the_function(turn: FakeTurn) -> None:
        source = (turn.workspace / "calc.py").read_text()
        turn.write("calc.py", source + "\n\ndef mul(a, b):\n    return a * b\n")

    async def fixes_the_old_bug(turn: FakeTurn) -> None:
        assert "test_sub" in turn.text and "assert 5 == 1" in turn.text  # it was told what failed
        source = (turn.workspace / "calc.py").read_text()
        turn.write("calc.py", source.replace("return a + b  # sub", "return a - b"))

    r = rig(scripted(adds_the_function, fixes_the_old_bug), command=command)
    (r.ws / "value.txt").unlink()
    (r.ws / "calc.py").write_text("def sub(a, b):\n    return a + b  # sub\n")
    (r.ws / "tests" / "test_a.py").write_text(
        "import sys\nsys.path.insert(0, '.')\nfrom calc import mul, sub\n\n\n"
        "def test_sub():\n    assert sub(3, 2) == 1\n\n\n"
        "def test_mul():\n    assert mul(3, 2) == 6\n"
    )
    tests_before = (r.ws / "tests" / "test_a.py").read_text()

    out = await r.turn("add mul(a, b) to calc.py")

    assert (out.result, out.rounds, out.needs_you) == ("passed", 2, False)
    assert [(c["result"], c["exit_code"]) for c in r.checks()] == [("failed", 1), ("passed", 0)]
    assert out.changed_tests == () and (r.ws / "tests" / "test_a.py").read_text() == tests_before
    assert "1 failed, 2 passed" in Path(r.checks()[0]["output_file"]).read_text()
    assert "3 passed" in Path(r.checks()[1]["output_file"]).read_text()
