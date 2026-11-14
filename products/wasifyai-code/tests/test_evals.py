"""The evaluation set and its runner (ADR-0101; C0 spike 3): the 36 tasks, each hidden check shown
to fail on the starting files with a real Python, and the runner against the pretended place."""

import asyncio
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest
from wasifyai_code.place import FakePlace, FakeTurn

EVALS = Path(__file__).resolve().parents[1] / "evals"
SPIKE_FILE = Path(__file__).resolve().parents[3] / "docs" / "spikes" / "coding-eval-tasks.json"

spec = importlib.util.spec_from_file_location("run_eval", EVALS / "run_eval.py")
assert spec is not None and spec.loader is not None
run_eval = importlib.util.module_from_spec(spec)
sys.modules["run_eval"] = run_eval
spec.loader.exec_module(run_eval)

TASKS = run_eval.load_tasks()
BY_ID = {t["id"]: t for t in TASKS}
FIXED_PAGING = (
    "def paginate(items, page, size):\n"
    "    start = (page - 1) * size\n"
    "    return items[start:start + size]\n"
)


def test_there_are_36_tasks_of_the_kinds_the_spike_ran():
    assert len(TASKS) == 36 and len(BY_ID) == 36
    assert Counter(t["kind"] for t in TASKS) == {
        "bug": 8,
        "feature": 8,
        "refactor": 3,
        "multi": 4,
        "question": 4,
        "tests": 2,
        "data": 1,
        "hard": 6,
    }
    for t in TASKS:
        assert set(t) == {"id", "kind", "prompt", "files", "hidden", "readonly"}, t["id"]
        assert t["prompt"].strip() and t["files"] and t["hidden"].strip(), t["id"]
        assert t["readonly"] == (t["kind"] == "question"), t["id"]


def test_the_products_tasks_are_the_spikes_tasks():
    """The set moved into the product; the spike's file stays as the record of what was run. Until
    one of them goes, they must not drift apart."""
    if not SPIKE_FILE.is_file():
        pytest.skip("the spike's file is not here")
    assert json.loads(SPIKE_FILE.read_text()) == json.loads((EVALS / "tasks.json").read_text())


async def test_every_hidden_check_fails_on_the_starting_files(tmp_path):
    results = await run_eval.check_start(TASKS, tmp_path)
    assert len(results) == 36
    assert [r["id"] for r in results if r["passed"]] == []  # not one passes untouched
    for r in results:
        assert r["why"], r["id"]  # and each says why
        assert "could not check" not in r["why"], r  # it failed by running, not by not running
    # nothing of the check is left in the workspace the agent would get
    assert not list(tmp_path.glob("*/workspace/_hidden_check.py"))


async def test_a_task_solved_passes_and_a_task_left_alone_fails(tmp_path):
    async def fixes(turn: FakeTurn) -> None:
        turn.write("paging.py", FIXED_PAGING)
        turn.say("Pages are numbered from 1, so the start is (page - 1) * size.")

    task = BY_ID["bug-paginate"]
    solved = await run_eval.run_task(FakePlace(fixes), task, tmp_path / "a")
    assert (solved["passed"], solved["why"], solved["status"]) == (True, "", "finished")
    assert (solved["steps"], solved["tools"], solved["changed"]) == (
        1,
        ["file_editor"],
        ["paging.py"],
    )

    idle = await run_eval.run_task(FakePlace(), task, tmp_path / "b")
    assert idle["passed"] is False and "AssertionError" in idle["why"] and idle["changed"] == []


async def test_a_question_is_judged_on_the_final_answer_and_no_file_may_change(tmp_path):
    task = BY_ID["ask-what-does"]

    async def right(turn: FakeTurn) -> None:
        turn.say("Let me read the file.")
        turn.step("file_editor", path="mystery.py")
        turn.say("chk is the Luhn checksum, used to validate card numbers.")

    async def wrong(turn: FakeTurn) -> None:
        turn.say("It is the Luhn checksum.")
        turn.say("On second thought, it sorts a list.")  # the last message is the answer

    async def right_but_edits(turn: FakeTurn) -> None:
        turn.write("mystery.py", "# tidied\n")
        turn.write("notes.txt", "x")
        turn.say("chk is the Luhn checksum.")

    good = await run_eval.run_task(FakePlace(right), task, tmp_path / "a")
    bad = await run_eval.run_task(FakePlace(wrong), task, tmp_path / "b")
    edits = await run_eval.run_task(FakePlace(right_but_edits), task, tmp_path / "c")

    assert good["passed"] is True and good["changed"] == []
    assert bad["passed"] is False
    assert edits["passed"] is False
    assert edits["why"] == "files changed in a read-only task: mystery.py, notes.txt"


async def test_a_task_that_runs_past_its_limit_is_stopped_and_scored(tmp_path):
    async def hangs(turn: FakeTurn) -> None:
        await asyncio.Event().wait()

    place = FakePlace(hangs)
    r = await run_eval.run_task(place, BY_ID["bug-paginate"], tmp_path, limit_s=0.2)
    assert (r["passed"], r["status"]) == (False, "timeout")
    assert [c[0] for c in place.calls] == ["start", "send", "stop"]
    assert not place.running(place.calls[0][1])


async def test_a_session_is_started_for_a_run_with_nobody_there(tmp_path):
    async def asks(turn: FakeTurn) -> None:
        if not await turn.confirm("pip install requests"):
            turn.write("paging.py", FIXED_PAGING)

    place = FakePlace(asks)
    r = await run_eval.run_task(
        place, BY_ID["bug-paginate"], tmp_path, model="some-model", step_limit=12
    )
    spec = place.calls[0][2]
    assert (spec.unattended, spec.model, spec.step_limit) == (True, "some-model", 12)
    assert spec.workspace == tmp_path / "bug-paginate" / "workspace"
    assert r["passed"] is True  # the question was refused, and the work went on


async def test_a_run_of_several_tasks_is_summed_up_by_kind(tmp_path):
    async def agent(turn: FakeTurn) -> None:
        if (turn.workspace / "paging.py").exists():
            turn.write("paging.py", FIXED_PAGING)
        turn.say("chk computes the Luhn checksum of a card number.")

    seen = []
    tasks = [BY_ID[i] for i in ("bug-paginate", "bug-slug", "ask-what-does")]
    out = await run_eval.run_all(FakePlace(agent), tasks, tmp_path, on_result=seen.append)

    assert (out["passed"], out["of"]) == (2, 3)
    assert out["kinds"] == {"bug": {"passed": 1, "of": 2}, "question": {"passed": 1, "of": 1}}
    assert [r["id"] for r in seen] == ["bug-paginate", "bug-slug", "ask-what-does"]


def test_the_script_proves_the_checks_without_a_model_and_says_what_it_cannot_do_yet(
    tmp_path, capsys
):
    out = tmp_path / "start.json"
    assert run_eval.main(["--start", "--out", str(out), "bug-paginate", "ask-where"]) == 0
    assert "2 of 2 hidden checks fail on the starting files" in capsys.readouterr().out
    assert [r["passed"] for r in json.loads(out.read_text())["results"]] == [False, False]

    assert run_eval.main([]) == 2
    assert "needs a real place" in capsys.readouterr().err
    with pytest.raises(ValueError, match="no such task: nope"):
        run_eval.main(["--start", "nope"])
