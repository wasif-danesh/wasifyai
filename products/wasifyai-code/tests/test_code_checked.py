# ruff: noqa: E501, F811  (test data on one line; `world` is a fixture taken from another file)
"""Sessions whose turns are checked (stage C3), on the pretended place: the project's check runs
after a turn that changed files, a failure goes back to the agent, the words on the feed, the
check's settings, and the questions before a command that deletes or installs. Real files, a real
git, a real store and a real check command; only the agent is pretended."""

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest
from test_code_edits import card, kept, sessions, start, turn_of, world  # noqa: F401
from test_code_sessions import ME
from wasifyai_code import checks, rules
from wasifyai_code import store as rows
from wasifyai_code.loop import failure_message
from wasifyai_code.place import FakeTurn, scripted
from wasifyai_code.runtime import CHECK, STATE, TRY_AGAIN, Refused, how_it_ended

PY = sys.executable
# the check of the review's case: an old bug (`total` of nothing) and a function still to be added
CHECK_FILE = """\
import sys
sys.path.insert(0, "src")
import prices
assert prices.total([]) == 0, "total of nothing must be 0"
assert prices.with_tax(100) == 120, "with_tax is missing or wrong"
print("all good")
"""
OLD = "def total(xs):\n    return sum(xs) if xs else None\n"
ADDED = OLD + "\n\ndef with_tax(x):\n    return x * 120 // 100\n"
FIXED = ADDED.replace("if xs else None", "")


def bakery(world) -> str:
    """The project gets a module with an old bug and a check file; gives the check command."""
    (world.project / "src" / "prices.py").write_text(OLD)
    (world.project / "check.py").write_text(CHECK_FILE)
    return f"{PY} -B check.py"


async def checked(live, world, made) -> None:
    live.set_check(ME, made["id"], bakery(world))


def writes(content: str):
    async def agent(turn: FakeTurn) -> None:
        await turn.edit("src/prices.py", content, command="str_replace")
        turn.say("Done.")

    return agent


async def answers(turn: FakeTurn) -> None:
    turn.step("grep", pattern="total")
    turn.say("It adds the prices up.")


# ---- the loop, from the session --------------------------------------------------------------------


async def test_the_reviews_case_one_refusal_one_fix_one_pass_and_the_check_file_untouched(world):
    live, place = sessions(world, scripted(writes(ADDED), writes(FIXED)))
    made = await start(live, world, mode=rows.OWN)
    await checked(live, world, made)
    was = (world.project / "check.py").read_bytes()
    closed = await turn_of(live, made, "Add with_tax")
    assert (closed["result"], closed["why"], closed["check_why"], closed["rounds"]) == (
        "passed", "finished", "", 2,
    )  # fmt: skip
    found = kept(live, made, CHECK)
    assert [(c["round"], c["result"], c["exit_code"]) for c in found] == [
        (1, "failed", 1),
        (2, "passed", 0),
    ]
    assert "total of nothing must be 0" in found[0]["tail"] and found[0]["rounds"] == 3
    # the failure went back to the agent: the command, the exit code and the end of the output
    sent = place.sent(live.store.get_session(ME, made["id"])["place_session"])
    assert len(sent) == 2 and sent[1].startswith("The project's check did not pass (try 1 of 3)")
    assert "total of nothing must be 0" in sent[1] and "Exit code: 1" in sent[1]
    assert (world.project / "check.py").read_bytes() == was and found[1]["changed_tests"] == []
    # the feed: working, ended, checking, working again, ended, checking, done with the word
    states = [(e["state"], e.get("round")) for e in kept(live, made, STATE)]
    assert states == [
        ("working", None), ("turn_ended", None), ("checking", 1), ("working", 1),
        ("turn_ended", None), ("checking", 2), ("done", 2),
    ]  # fmt: skip
    done = kept(live, made, STATE)[-1]
    assert done["result"] == "passed" and done["changed"] == 1 and "needs_you" not in done
    seen = live.view(ME, made["id"])
    assert (seen["result"], seen["working"], seen["needs_you"]) == ("passed", False, False)
    # the whole turn is one change in the Changes tab, and is undone as one
    (item,) = (await live.changes(ME, made["id"]))["items"]
    assert item["can_undo"] and [f["path"] for f in item["files"]] == ["src/prices.py"]
    await live.undo(ME, made["id"], item["turn_id"])
    assert (world.project / "src" / "prices.py").read_text() == OLD


async def test_a_check_that_cannot_pass_ends_after_three_rounds_with_needs_you(world):
    live, place = sessions(world, writes(ADDED))  # it never fixes the old bug

    async def again(turn: FakeTurn) -> None:
        await turn.edit("src/prices.py", ADDED + f"# try {turn.number}\n", command="str_replace")

    live, place = sessions(world, again)
    made = await start(live, world, mode=rows.OWN)
    await checked(live, world, made)
    closed = await turn_of(live, made, "Add with_tax")
    assert (closed["result"], closed["why"], closed["check_why"], closed["rounds"]) == (
        "failed", "finished", "rounds_used", 3,
    )  # fmt: skip
    assert closed["needs_you"] and [c["result"] for c in kept(live, made, CHECK)] == ["failed"] * 3
    done = kept(live, made, STATE)[-1]
    assert done["needs_you"] is True and done["check_why"] == "rounds_used"
    assert live.view(ME, made["id"])["needs_you"] is True
    # "Try 3 more rounds" is a new turn with a new count
    await live.try_again(ME, made["id"])
    closed = await live.wait(ME, made["id"])
    assert closed["request"] == TRY_AGAIN and closed["rounds"] == 3
    assert len(kept(live, made, CHECK)) == 6


async def test_a_question_in_a_project_whose_check_fails_is_answered_and_nothing_is_checked(world):
    live, _ = sessions(
        world,
        scripted(
            writes(ADDED + "# 1\n"), writes(ADDED + "# 2\n"), writes(ADDED + "# 3\n"), answers
        ),
    )
    made = await start(live, world, mode=rows.OWN)
    await checked(live, world, made)
    assert (await turn_of(live, made, "Add with_tax"))["result"] == "failed"
    files = sorted(p.read_bytes() for p in world.project.rglob("*.py"))
    closed = await turn_of(live, made, "What does total do?")
    assert closed["answer"] == "It adds the prices up." and closed["rounds"] == 0
    assert (closed["why"], closed["check_why"], closed["result"]) == (
        "finished",
        "no_change",
        "failed",
    )
    assert len(kept(live, made, CHECK)) == 3  # no fourth check ran
    assert sorted(p.read_bytes() for p in world.project.rglob("*.py")) == files
    assert live.view(ME, made["id"])["result"] == "failed"  # the last word stands


async def test_a_project_with_no_check_ends_not_checked_and_says_why(world):
    live, _ = sessions(world, writes(ADDED))
    made = await start(live, world, mode=rows.OWN)
    bakery(world)
    closed = await turn_of(live, made, "Add with_tax")
    assert (closed["result"], closed["why"], closed["check_why"]) == (
        "not_checked",
        "finished",
        "no_command",
    )
    assert kept(live, made, CHECK) == []
    assert kept(live, made, STATE)[-1]["check_why"] == "no_command"


async def test_plan_runs_no_check_and_keeps_the_word(world):
    live, _ = sessions(world, answers)
    made = await start(live, world, mode=rows.PLAN)
    live.set_check(ME, made["id"], "exit 1")
    closed = await turn_of(live, made, "What is here?")
    assert (closed["result"], closed["why"], closed["rounds"]) == ("", "finished", 0)
    assert kept(live, made, CHECK) == [] and live.view(ME, made["id"])["result"] == ""


async def test_stop_during_a_check_ends_it_within_a_second_and_leaves_nothing_running(
    world, tmp_path
):
    mark = tmp_path / "pid"
    live, _ = sessions(world, writes(ADDED))
    made = await start(live, world, mode=rows.OWN)
    bakery(world)
    live.set_check(ME, made["id"], f"sleep 300 & echo $! > {mark}; wait")
    await live.send(ME, made["id"], "Add with_tax")
    for _ in range(500):
        if mark.exists() and mark.read_text().strip():
            break
        await asyncio.sleep(0.01)
    assert live.view(ME, made["id"])["checking"] is True
    began = time.monotonic()
    assert await live.stop(ME, made["id"]) is True
    assert time.monotonic() - began < 1.0
    closed = live.turns(ME, made["id"])[-1]
    assert (closed["result"], closed["why"]) == ("not_checked", "stopped")
    await asyncio.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(int(mark.read_text()), 0)
    assert not live.running(made["id"])


async def test_a_check_runs_while_every_other_call_still_answers(world):
    live, _ = sessions(world, writes(ADDED))
    made = await start(live, world, mode=rows.OWN)
    bakery(world)
    live.set_check(ME, made["id"], "sleep 2; exit 0")
    await live.send(ME, made["id"], "Add with_tax")
    slowest = 0.0
    while live.running(made["id"]):
        began = time.monotonic()
        live.view(ME, made["id"])
        await live.changes(ME, made["id"])
        live.check(ME, made["id"])
        slowest = max(slowest, time.monotonic() - began)
        await asyncio.sleep(0.05)
    assert slowest < 1.0
    assert live.turns(ME, made["id"])[-1]["result"] == "passed"


# ---- the check's settings ----------------------------------------------------------------------------


async def test_the_check_is_suggested_from_the_projects_files_set_run_by_hand_and_read(world):
    live, _ = sessions(world, answers)
    made = await start(live, world)
    (world.project / "package.json").write_text(
        '{"scripts": {"test": "node --test", "build": "vite build", "lint": "eslint ."}}'
    )
    (world.project / "pnpm-lock.yaml").write_text("")
    seen = live.check(ME, made["id"])
    assert seen["command"] == "" and seen["limit_s"] == 600 and seen["rounds"] == 3
    assert [s["command"] for s in seen["suggested"]] == [
        "pnpm test",
        "pnpm run build",
        "pnpm run lint",
    ]
    assert "package.json" in seen["suggested"][0]["why"]
    with pytest.raises(Refused) as no:
        await live.check_now(ME, made["id"])
    assert no.value.code == "no_check"
    assert live.set_check(ME, made["id"], "pnpm test")["source"] == "suggested"
    seen = live.set_check(ME, made["id"], "echo line one; echo line two; exit 3", limit_s=30)
    assert (seen["source"], seen["limit_s"]) == ("person", 30)
    row = await live.check_now(ME, made["id"])
    assert (row["result"], row["exit_code"], row["round"]) == ("failed", 3, 0)
    assert "output_file" not in row
    assert live.view(ME, made["id"])["result"] == "failed"
    assert [e["state"] for e in kept(live, made, STATE)] == ["checking", "done"]
    out = live.check_output(ME, made["id"], row["id"])
    assert out["output"] == "line one\nline two\n" and out["cut"] is False
    assert live.check(ME, made["id"])["checks"][0]["id"] == row["id"]
    # no check at all
    assert live.set_check(ME, made["id"], "")["command"] == ""
    with pytest.raises(Refused):
        live.set_check(ME, made["id"], "x" * 3000)
    with pytest.raises(Refused):
        live.set_check(ME, made["id"], "true", limit_s=1)


def test_which_check_is_suggested(tmp_path: Path):
    def of(files: dict[str, str]) -> list[str]:
        folder = tmp_path / str(len(list(tmp_path.iterdir())))
        for name, text in files.items():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_text(text)
        folder.mkdir(exist_ok=True)
        return [s.command for s in checks.suggest(folder)]

    assert of({}) == []
    assert (
        of(
            {
                "package.json": '{"scripts": {"test": "echo \\"Error: no test specified\\" && exit 1"}}'
            }
        )
        == []
    )
    assert of({"package.json": '{"scripts": {"test": "jest"}}', "yarn.lock": ""}) == ["yarn test"]
    assert of({"package.json": "not json"}) == []
    assert of({"Cargo.toml": "[package]"}) == ["cargo test"]
    assert of({"go.mod": "module x"}) == ["go test ./..."]
    assert of({"pyproject.toml": "[tool.pytest.ini_options]"}) == ["python3 -m pytest"]
    assert of({"pyproject.toml": "[tool.pytest]", ".venv/bin/python": ""}) == [
        ".venv/bin/python -m pytest"
    ]
    assert of({"tests/test_a.py": ""}) == ["python3 -m unittest"]
    assert of({"Makefile": "build:\n\ttrue\ntest:\n\ttrue\n", "go.mod": ""}) == [
        "go test ./...",
        "make test",
    ]


# ---- the questions before a command ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("ls -la", None), ("pytest -q", None), ("npm test", None), ("npm run build", None),
        ("git status", None), ("git init", None), ("git checkout main", None), ("echo rm", None),
        ("grep -r rm .", None), ("mkdir a; touch a/b", None), ("cargo test", None), ("yarn test", None),
        ("rm -rf build", "delete"), ("cd x && rm a.txt", "delete"), ("git clean -fd", "delete"),
        ("git reset --hard HEAD~1", "delete"), ("git checkout -- .", "delete"),
        ("find . -name '*.pyc' -delete", "delete"), ("sudo rm x", "delete"),
        ("pip install requests && rm -rf build", "delete"),
        ("pip install requests", "install"), ("python -m pip install -e .", "install"),
        ("FOO=1 pip install x", "install"), ("npm install", "install"), ("npm i left-pad", "install"),
        ("pnpm add zod", "install"), ("yarn", "install"), ("npx create-vite app", "install"),
        ("uv add httpx", "install"), ("cargo add serde", "install"), ("go get example.com/x", "install"),
        ("brew install jq", "install"), ("ls; npm ci", "install"),
    ],
)  # fmt: skip
def test_what_kind_of_request_a_command_is(command, kind):
    assert rules.command_kind(command) == kind


def runs(command: str, said: list[bool]):
    async def agent(turn: FakeTurn) -> None:
        turn.step("terminal", id="c1", command=command)
        said.append(await turn.confirm(command, tool="terminal", command=command))
        turn.say("Done.")

    return agent


async def test_ask_me_asks_before_a_command_that_deletes_and_a_no_is_a_no(world):
    said: list[bool] = []
    live, _ = sessions(world, runs("rm -rf build", said))
    made = await start(live, world, mode=rows.ASK)
    await live.send(ME, made["id"], "Clean up")
    asked = await card(live, made)
    assert asked["payload"]["ask"] == "delete" and asked["payload"]["command"] == "rm -rf build"
    assert asked["payload"]["tool"] == "terminal" and asked["payload"]["undo"] is True
    await live.answer(ME, made["id"], asked["interrupt_id"], rules.NO)
    await live.wait(ME, made["id"])
    assert said == [False]


async def test_an_install_asks_once_and_allow_for_this_project_stops_the_question(world):
    said: list[bool] = []
    live, _ = sessions(world, runs("npm install", said))
    made = await start(live, world, mode=rows.ASK)
    await live.send(ME, made["id"], "Set it up")
    asked = await card(live, made)
    assert asked["payload"]["ask"] == "install"
    await live.answer(ME, made["id"], asked["interrupt_id"], rules.ALLOW)
    await live.wait(ME, made["id"])
    await turn_of(live, made, "Again")  # no card: it would wait for ever
    assert said == [True, True]
    assert [k["id"] for k in live.project(ME, made["id"])["kinds"] if k["allowed"]] == ["install"]


async def test_a_plain_command_and_work_on_its_own_ask_nothing(world):
    said: list[bool] = []
    live, _ = sessions(world, runs("npm test", said))
    made = await start(live, world, mode=rows.ASK)
    await turn_of(live, made, "Test it")
    live2, _ = sessions(world, runs("rm -rf build", said))
    other = await start(live2, world, mode=rows.OWN)
    await turn_of(live2, other, "Clean up")
    assert said == [True, True]


def test_how_a_turn_ended_is_said_in_two_words():
    assert how_it_ended("finished") == ("finished", "")
    assert how_it_ended("stopped") == ("stopped", "")
    assert how_it_ended("rounds_used") == ("finished", "rounds_used")
    assert how_it_ended("no_command") == ("finished", "no_command")
    assert how_it_ended("cut_off") == ("error", "")
    assert how_it_ended("") == ("", "")
    assert "try 2 of 3" in failure_message(checks.CheckResult("failed", "x", exit_code=1), 2, 3)
