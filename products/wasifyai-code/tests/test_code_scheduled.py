# ruff: noqa: E501, F811, ASYNC240  (test data on one line; `world` is a fixture of another file; small files read in tests)
"""Scheduled runs in the app (stage C6) on the pretended place, with a pretended clock: a
schedule comes due, the run works on a copy of the project with nobody to ask, the project is
never touched, and the run's changes are applied or let go. Real files, a real git and a real
store; only the agent and the clock are pretended."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_code_edits import listing, sessions, world  # noqa: F401
from test_code_sessions import ME
from wasifyai_code import store as rows
from wasifyai_code.place import FakeTurn
from wasifyai_code.runtime import scheduled_for
from wasifyai_code.scheduled import Scheduled, ScheduleRefused, rule_words
from wasifyai_code.schedules import PretendClock

START = datetime(2027, 3, 15, 8, 0, tzinfo=UTC)  # a Monday
DAILY = {"kind": "daily", "time": "09:00"}


async def tidies(turn: FakeTurn) -> None:
    """A run that changes one file, adds one, and asks for something only a person may allow."""
    await turn.edit("src/home.html", "<h1>Bakery</h1>\n<p>Open today</p>\n", command="str_replace")
    await turn.edit("notes/run.txt", "done\n")
    asked = await turn.confirm(
        "a picture", tool="terminal", command='wasify-make picture "a loaf" logo.png'
    )
    turn.say("Updated the home page." + ("" if asked else " I could not make the picture."))


def rig(world, agent=tidies) -> tuple[Scheduled, PretendClock, dict]:
    world.state.coding_server = SimpleNamespace(run_dir=world.data / "coding", install=None)
    live, _ = sessions(world, agent)
    clock = PretendClock(START)
    made = Scheduled(live, clock=clock)
    live.scheduled = made
    return made, clock, {"live": live}


async def a_project(world, live) -> dict:
    session = await live.start(ME, folder=str(world.project), mode=rows.ASK)
    (project,) = live.workspaces(ME)
    return project | {"session": session["id"]}


async def until_done(made: Scheduled, schedule_id: str, clock: PretendClock) -> dict:
    for _ in range(400):
        await clock.settle()
        await asyncio.sleep(0.01)
        runs = made.get(ME, schedule_id)["runs"]
        if runs and runs[0]["state"] not in ("waiting", "running"):
            return runs[0]
    raise AssertionError(f"the run never ended: {made.get(ME, schedule_id)['runs']}")


def test_a_rule_is_said_in_plain_words():
    assert rule_words(DAILY) == "Every day at 09:00"
    assert (
        rule_words({"kind": "weekdays", "days": [0, 1, 2, 3, 4], "time": "07:30"})
        == "Every weekday at 07:30"
    )
    assert (
        rule_words({"kind": "weekdays", "days": [0, 5], "time": "07:30"})
        == "Every Monday, Saturday at 07:30"
    )
    assert rule_words({"kind": "every", "minutes": 15, "start": "x"}) == "Every 15 minutes"
    assert rule_words({"kind": "every", "hours": 1, "start": "x"}) == "Every hour"
    assert (
        rule_words({"kind": "monthly", "day": 31, "time": "09:00"})
        == "Every month on day 31 at 09:00 (or the month's last day)"
    )
    assert (
        rule_words({"kind": "once", "date": "2027-03-20", "time": "10:00"})
        == "Once, on 2027-03-20 at 10:00"
    )


async def test_a_schedule_comes_due_and_runs_on_a_copy_the_project_is_not_touched(world):
    made, clock, more = rig(world)
    live = more["live"]
    project = await a_project(world, live)
    live.set_check(ME, project["session"], "test -f notes/run.txt")
    was = listing(world.project)
    schedule = made.add(
        ME,
        workspace_id=project["id"],
        request="Tidy the home page",
        rule=DAILY,
        time_zone="UTC",
        title="Morning tidy",
    )
    assert schedule["rule_words"] == "Every day at 09:00" and schedule["next_due"].startswith(
        "2027-03-15T09:00"
    )
    assert (
        schedule["title"] == "Morning tidy"
        and schedule["project"] == "bakery-site"
        and schedule["last"] is None
    )
    made.start()
    try:
        await clock.advance(59 * 60)  # 08:59: nothing yet
        assert made.get(ME, schedule["id"])["runs"] == []
        await clock.advance(61)
        run = await until_done(made, schedule["id"], clock)
        assert (run["state"], run["result"], run["changed"], run["open"]) == (
            "done",
            "passed",
            2,
            True,
        )
        # nobody was there to ask: the picture was refused and written down, the rest went on
        assert run["note"] == "1 step was refused: nobody was there to ask."
        # the project is byte for byte what it was; the work is in a copy under the engine's own folder
        assert listing(world.project) == was
        copy = Path(live.view(ME, run["session_id"])["folder"])
        assert world.data / "coding" / "copies" in copy.parents and copy.name == "bakery-site"
        assert (copy / "notes" / "run.txt").read_text() == "done\n" and not (
            copy / "logo.png"
        ).exists()
        assert not (copy / ".env").exists()  # what the project ignores is not in the copy
        assert live.view(ME, run["session_id"])["scheduled_run"] is True
        assert [w["id"] for w in live.workspaces(ME)] == [
            project["id"]
        ]  # the copy is not a project
        # what it changed, and that each file can be applied
        found = await made.changes(ME, run["id"])
        assert sorted((f["path"], f["what"], f["conflict"]) for f in found["files"]) == [
            ("notes/run.txt", "added", False), ("src/home.html", "changed", False),
        ]  # fmt: skip
        done = await made.apply(ME, run["id"])
        assert sorted(done["applied"]) == ["notes/run.txt", "src/home.html"] and done["left"] == []
        assert "Open today" in (world.project / "src" / "home.html").read_text()
        assert (world.project / "notes" / "run.txt").read_text() == "done\n"
        assert (
            done["run"]["open"] is False
            and done["run"]["applied_at"]
            and not done["run"]["discarded_at"]
        )
        assert not copy.exists()
        with pytest.raises(ScheduleRefused) as no:
            await made.changes(ME, run["id"])
        assert no.value.code == "no_copy"
        # it is due again tomorrow, and not before
        assert made.get(ME, schedule["id"])["next_due"].startswith("2027-03-16T09:00")
    finally:
        await made.close()


async def test_a_file_the_person_changed_meanwhile_is_left_alone_and_named(world):
    made, clock, more = rig(world)
    live = more["live"]
    project = await a_project(world, live)
    schedule = made.add(ME, workspace_id=project["id"], request="Tidy", rule=DAILY, time_zone="UTC")
    made.start()
    try:
        row = made.run_now(ME, schedule["id"])
        assert row["state"] == "waiting"
        run = await until_done(made, schedule["id"], clock)
        (world.project / "src" / "home.html").write_text("<h1>Mine</h1>\n")  # the person, meanwhile
        found = await made.changes(ME, run["id"])
        assert {f["path"]: f["conflict"] for f in found["files"]} == {
            "notes/run.txt": False,
            "src/home.html": True,
        }
        done = await made.apply(ME, run["id"])
        assert done["applied"] == ["notes/run.txt"] and done["left"] == ["src/home.html"]
        assert (world.project / "src" / "home.html").read_text() == "<h1>Mine</h1>\n"
    finally:
        await made.close()


async def test_letting_a_run_go_removes_its_copy_and_leaves_the_project(world):
    made, clock, more = rig(world)
    live = more["live"]
    project = await a_project(world, live)
    was = listing(world.project)
    schedule = made.add(ME, workspace_id=project["id"], request="Tidy", rule=DAILY, time_zone="UTC")
    made.start()
    try:
        made.run_now(ME, schedule["id"])
        run = await until_done(made, schedule["id"], clock)
        copy = Path(live.view(ME, run["session_id"])["folder"])
        gone = await made.discard(ME, run["id"])
        assert gone["open"] is False and gone["discarded_at"] and not gone["applied_at"]
        assert not copy.exists() and listing(world.project) == was
        # paused: nothing comes due; removed: gone with its history
        paused = made.change(ME, schedule["id"], enabled=False)
        assert paused["enabled"] is False and paused["next_due"] is None
        await clock.advance(3 * 24 * 3600)
        assert len(made.get(ME, schedule["id"])["runs"]) == 1
        assert await made.remove(ME, schedule["id"]) is True
        assert made.list(ME) == []
    finally:
        await made.close()


async def test_only_the_newest_copies_of_a_schedule_are_kept(world):
    made, clock, more = rig(world)
    live = more["live"]
    project = await a_project(world, live)
    schedule = made.add(
        ME,
        workspace_id=project["id"],
        request="Tidy",
        rule={"kind": "every", "minutes": 5, "start": START.isoformat()},
        time_zone="UTC",
    )
    made.start()
    try:
        for n in range(7):
            await clock.advance(5 * 60)
            for _ in range(400):
                await clock.settle()
                await asyncio.sleep(0.01)
                runs = made.get(ME, schedule["id"])["runs"]
                if len(runs) == n + 1 and runs[0]["state"] == "done":
                    break
        runs = made.get(ME, schedule["id"])["runs"]
        assert [r["state"] for r in runs] == ["done"] * 7  # none missed, none doubled
        assert len({r["due_at"] for r in runs}) == 7
        assert [r["open"] for r in runs] == [True] * 5 + [False] * 2  # the newest first
        copies = world.data / "coding" / "copies"
        assert len(list(copies.iterdir())) == 5
    finally:
        await made.close()


async def test_what_cannot_be_scheduled_is_refused_in_words(world):
    made, _clock, more = rig(world)
    live = more["live"]
    project = await a_project(world, live)
    for given, code in (
        ({"request": "  "}, "nothing_to_do"),
        ({"rule": {"kind": "every", "minutes": 1, "start": START.isoformat()}}, "bad_rule"),
        ({"rule": {"kind": "sometimes"}}, "bad_rule"),
        ({"time_zone": "Mars/Olympus"}, "bad_rule"),
        ({"workspace_id": "nothing"}, "not_found"),
    ):
        with pytest.raises(ScheduleRefused) as no:
            made.add(
                ME,
                **{
                    "workspace_id": project["id"],
                    "request": "Tidy",
                    "rule": DAILY,
                    "time_zone": "UTC",
                    **given,
                },
            )
        assert no.value.code == code, given
    with pytest.raises(ScheduleRefused):
        made.get(ME, "nothing")
    assert scheduled_for(world.state) is made  # one for the engine
    await made.close()


async def test_every_so_many_minutes_is_counted_from_when_it_is_saved(world):
    made, clock, more = rig(world)
    project = await a_project(world, more["live"])
    schedule = made.add(
        ME, workspace_id=project["id"], request="Tidy.", rule={"kind": "every", "minutes": 30},
        time_zone="UTC",
    )  # fmt: skip
    assert schedule["rule"]["start"] == "2027-03-15T08:00:00+00:00"
    assert schedule["next_due"] == "2027-03-15T08:30:00+00:00"
    assert schedule["rule_words"] == "Every 30 minutes"
    changed = made.change(ME, schedule["id"], rule={"kind": "every", "hours": 2})
    assert changed["next_due"] == "2027-03-15T10:00:00+00:00"


async def test_a_schedule_with_no_model_named_uses_the_one_of_the_projects_newest_session(world):
    made, _clock, more = rig(world)
    project = await a_project(world, more["live"])
    session = more["live"].store.get_session(ME, project["session"])
    schedule = made.add(
        ME, workspace_id=project["id"], request="Tidy.", rule=DAILY, time_zone="UTC"
    )
    assert schedule["model"] == session["model"] != ""


# ---- a schedule on the person's own agent program (ADR-0107, stage H3) -------------------------


class Accounts:
    """The programs' sign-in, pretended: signed in or not."""

    def __init__(self) -> None:
        self.signed_in = True

    async def status(self, harness: str) -> dict:
        return {"id": harness, "title": "Claude Code", "installed": True,
                "signed_in": self.signed_in, "how": "plan", "plan": "max"}  # fmt: skip


def on_harness(world) -> tuple[Scheduled, PretendClock, dict]:
    made, clock, more = rig(world)
    world.state.coding_server.harness_ids = ("claude-code", "codex")
    world.state.coding_harnesses = Accounts()
    return made, clock, more


async def test_a_schedule_runs_on_the_persons_own_program_on_a_copy(world):
    made, clock, more = on_harness(world)
    live = more["live"]
    await live.start(ME, folder=str(world.project), model="claude-code:haiku", mode=rows.PLAN)
    (project,) = live.workspaces(ME)
    was = listing(world.project)
    schedule = made.add(
        ME, workspace_id=project["id"], request="Tidy.", rule=DAILY, time_zone="UTC"
    )
    # with no model named, the project's newest session's: the program's
    assert schedule["model"] == "claude-code:haiku"
    made.start()
    try:
        await clock.advance(61 * 60)  # 09:01
        run = await until_done(made, schedule["id"], clock)
    finally:
        await made.close()
    assert run["state"] == "done", run
    assert run["changed"] >= 1 and run["open"]
    session = live.store.get_session(ME, run["session_id"])
    assert session["model"] == "claude-code:haiku" and session["mode"] == rows.OWN
    assert live.view(ME, run["session_id"])["counted_in"] == "plan"
    assert listing(world.project) == was  # the project itself is not touched


async def test_a_schedule_on_a_program_that_is_signed_out_fails_in_words(world):
    made, clock, more = on_harness(world)
    live = more["live"]
    await live.start(ME, folder=str(world.project), model="codex:gpt-5.6-terra", mode=rows.PLAN)
    (project,) = live.workspaces(ME)
    schedule = made.add(
        ME, workspace_id=project["id"], request="Tidy.", rule=DAILY, time_zone="UTC"
    )
    world.state.coding_harnesses.signed_in = False
    made.start()
    try:
        await clock.advance(61 * 60)  # 09:01
        run = await until_done(made, schedule["id"], clock)
    finally:
        await made.close()
    assert run["state"] == "failed", run
    assert "Sign in to Claude Code first" in run["note"]
    assert not run["open"]
