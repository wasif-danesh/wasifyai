"""The one timer (ADR-0105, decisions 5 to 10) on a pretended clock and a real store."""

import asyncio
import threading
from datetime import UTC, datetime, timedelta

import pytest
from wasifyai_code.schedules import (
    CAUGHT_UP,
    MISSED_ROWS,
    NOT_OPEN,
    PretendClock,
    RunResult,
    Timer,
    add_schedule,
    change_schedule,
)
from wasifyai_code.store import STILL_RUNNING, CodeStore, Missed, Owner, utc_text

ME = Owner("t1", "u1")

START = datetime(2027, 6, 1, 8, 0, tzinfo=UTC)  # a Tuesday; 10:00 in Berlin
ZONE = "Europe/Berlin"
MIN = 60.0


def every(minutes: int, start: datetime = START) -> dict:
    return {"kind": "every", "minutes": minutes, "start": utc_text(start)}


class Rig:
    """A store with one workspace, a pretended clock, and timers whose runs are written down."""

    def __init__(self, store: CodeStore):
        self.store = store
        self.clock = PretendClock(START)
        self.workspace = store.add_workspace(ME, "/projects/one", name="one")
        self.ran: list[tuple[str, str]] = []  # (schedule id, the due time it ran for)
        self.hold: asyncio.Event | None = None  # set to make runs wait
        self.at_once = 0  # runs going now, and the most that ever were
        self.most_at_once = 0
        self.tasks: list[asyncio.Task] = []

    def schedule(self, rule: dict, **more) -> dict:
        return add_schedule(
            self.store,
            ME,
            workspace_id=self.workspace["id"],
            request="tidy the project",
            rule=rule,
            time_zone=ZONE,
            now=self.clock.now(),
            **more,
        )

    async def runner(self, schedule: dict, run: dict) -> RunResult:
        self.ran.append((schedule["id"], run["due_at"]))
        self.at_once += 1
        self.most_at_once = max(self.most_at_once, self.at_once)
        try:
            if self.hold is not None:
                await self.hold.wait()
            return RunResult("passed", session_id="s-" + run["id"][:6])
        finally:
            self.at_once -= 1

    async def timer(self, store: CodeStore | None = None, runner=None) -> Timer:
        timer = Timer(store or self.store, runner or self.runner, clock=self.clock)
        self.tasks.append(asyncio.ensure_future(timer.serve()))
        await self.clock.settle()
        return timer

    async def close(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def runs(self, schedule: dict) -> list[dict]:
        return self.store.list_runs(ME, schedule["id"])

    def states(self, schedule: dict) -> list[tuple[str, str]]:
        return [(r["due_at"][11:16], r["state"]) for r in self.runs(schedule)]


@pytest.fixture
async def rig(store):
    r = Rig(store)
    yield r
    await r.close()


async def test_it_fires_at_its_time_and_once(rig):
    s = rig.schedule({"kind": "daily", "time": "10:30"})  # 08:30 UTC, half an hour from now
    assert s["next_due"] == "2027-06-01T08:30:00+00:00"
    timer = await rig.timer()

    await rig.clock.advance(29 * MIN + 59)
    assert rig.ran == []
    await rig.clock.advance(1)

    assert rig.ran == [(s["id"], "2027-06-01T08:30:00+00:00")]
    [run] = rig.runs(s)
    assert (run["state"], run["result"], run["note"], run["stands_for"]) == (
        "done",
        "passed",
        "",
        1,
    )
    assert run["session_id"].startswith("s-") and run["started_at"] and run["finished_at"]
    assert (run["tenant_id"], run["product_id"], run["user_id"]) == ("t1", "wasifyai-code", "u1")
    assert rig.store.get_schedule(ME, s["id"])["next_due"] == "2027-06-02T08:30:00+00:00"
    assert timer.holding() == {s["id"]: datetime(2027, 6, 2, 8, 30, tzinfo=UTC)}

    await rig.clock.advance(24 * 60 * MIN)
    assert len(rig.ran) == 2 and len(rig.runs(s)) == 2  # the next day, once again


async def test_it_never_sleeps_longer_than_a_minute_and_a_wake_with_nothing_due_reads_nothing(rig):
    rig.schedule({"kind": "daily", "time": "13:00"})  # three hours away
    timer = await rig.timer()
    assert timer.reads == 1  # the one read at start

    await rig.clock.advance(170 * MIN)

    assert timer.wakes >= 170 and max(rig.clock.sleeps) <= 60.0
    assert timer.reads == 1 and rig.ran == []  # it woke 170 times and read the store not once
    await rig.clock.advance(10 * MIN)
    assert len(rig.ran) == 1 and timer.reads == 2  # one more read: the schedule that came due


async def test_with_no_schedule_at_all_it_still_wakes_every_minute_and_reads_nothing(rig):
    timer = await rig.timer()
    await rig.clock.advance(10 * MIN)
    assert set(rig.clock.sleeps) == {60.0} and timer.reads == 1


async def test_after_an_absence_the_latest_time_runs_once_and_the_rest_are_missed(rig):
    s = rig.schedule(every(30))  # due at 08:30, 09:00, ...
    rig.clock.jump(seconds=190 * MIN)  # the app was closed until 11:10
    await rig.timer()

    assert rig.ran == [(s["id"], "2027-06-01T11:00:00+00:00")]  # one catch-up run, for the latest
    assert rig.states(s) == [
        ("08:30", "missed"),
        ("09:00", "missed"),
        ("09:30", "missed"),
        ("10:00", "missed"),
        ("10:30", "missed"),
        ("11:00", "done"),
    ]
    runs = rig.runs(s)
    assert {r["note"] for r in runs[:-1]} == {NOT_OPEN} and runs[-1]["note"] == CAUGHT_UP
    assert rig.store.get_schedule(ME, s["id"])["next_due"] == "2027-06-01T11:30:00+00:00"

    await rig.clock.advance(20 * MIN)  # and then on time again, no doubled run
    assert [due[11:16] for _, due in rig.ran] == ["11:00", "11:30"]


async def test_a_missed_time_older_than_a_day_is_not_run(rig):
    once = rig.schedule({"kind": "once", "date": "2027-06-01", "time": "12:00"})
    daily = rig.schedule({"kind": "daily", "time": "12:00"})
    rig.clock.jump(to=datetime(2027, 6, 4, 9, 0, tzinfo=UTC))  # three days later, 11:00 in Berlin
    timer = await rig.timer()

    assert rig.states(once) == [("10:00", "missed")]  # its one time is three days old
    assert rig.states(daily) == [("10:00", "missed"), ("10:00", "missed"), ("10:00", "done")]
    assert [r["due_at"][:10] for r in rig.runs(daily)] == ["2027-06-01", "2027-06-02", "2027-06-03"]
    assert rig.ran == [(daily["id"], "2027-06-03T10:00:00+00:00")]  # 23 hours old: caught up
    assert rig.store.get_schedule(ME, once["id"])["next_due"] is None
    assert list(timer.holding()) == [daily["id"]]  # a "once" that has passed is not held any more


async def test_a_schedule_that_says_not_to_run_when_missed_records_them_all(rig):
    s = rig.schedule(every(30), run_when_missed=False)
    rig.clock.jump(seconds=70 * MIN)
    await rig.timer()

    assert rig.ran == [] and rig.states(s) == [("08:30", "missed"), ("09:00", "missed")]
    await rig.clock.advance(20 * MIN)
    assert [due[11:16] for _, due in rig.ran] == ["09:30"]  # on time, it runs as ever


async def test_a_very_long_absence_does_not_write_a_row_for_every_missed_time(rig):
    s = rig.schedule(every(5))
    rig.clock.jump(seconds=14 * 24 * 60 * MIN + 1)  # two weeks: 4,032 times
    await rig.timer()

    runs = rig.runs(s)
    missed = [r for r in runs if r["state"] == "missed"]
    assert len(missed) == MISSED_ROWS + 1 and len(runs) == MISSED_ROWS + 2
    assert sum(r["stands_for"] for r in runs) == 14 * 24 * 12  # every due time is accounted for
    assert (missed[0]["due_at"], missed[0]["stands_for"]) == (
        "2027-06-01T08:05:00+00:00",
        4032 - 1 - MISSED_ROWS,
    )
    assert len(rig.ran) == 1 and runs[-1]["state"] == "done"


async def test_a_time_is_skipped_while_the_earlier_run_is_still_going(rig):
    s = rig.schedule(every(5))
    rig.hold = asyncio.Event()
    await rig.timer()

    await rig.clock.advance(5 * MIN)  # 08:05 starts, and does not end
    assert rig.states(s) == [("08:05", "running")]
    await rig.clock.advance(10 * MIN)  # 08:10 and 08:15 come while it runs

    assert rig.states(s) == [("08:05", "running"), ("08:10", "skipped"), ("08:15", "skipped")]
    assert {r["note"] for r in rig.runs(s)[1:]} == {STILL_RUNNING}
    assert len(rig.ran) == 1 and rig.most_at_once == 1

    rig.hold.set()
    await rig.clock.advance(5 * MIN)
    assert rig.states(s)[0] == ("08:05", "done") and rig.states(s)[-1] == ("08:20", "done")


async def test_runs_of_different_schedules_wait_in_line(rig):
    a, b = rig.schedule(every(5)), rig.schedule(every(5))
    rig.hold = asyncio.Event()
    await rig.timer()

    await rig.clock.advance(5 * MIN)
    assert sorted(r["state"] for s in (a, b) for r in rig.runs(s)) == ["running", "waiting"]
    rig.hold.set()
    await rig.clock.settle()

    assert [r["state"] for s in (a, b) for r in rig.runs(s)] == ["done", "done"]
    assert rig.most_at_once == 1 and len(rig.ran) == 2


async def test_a_run_that_fails_is_written_down_and_the_timer_goes_on(rig):
    s = rig.schedule(every(5))
    calls = []

    async def breaks_once(schedule: dict, run: dict) -> RunResult:
        calls.append(run["due_at"])
        if len(calls) == 1:
            raise RuntimeError("the workspace folder is gone")
        return RunResult("failed")

    await rig.timer(runner=breaks_once)
    await rig.clock.advance(10 * MIN)

    first, second = rig.runs(s)
    assert (first["state"], first["note"], first["result"]) == (
        "failed",
        "the workspace folder is gone",
        "",
    )
    assert (second["state"], second["result"]) == ("done", "failed")  # a run that ended "failed"


async def test_a_schedule_made_changed_switched_off_or_removed_is_noticed_when_the_timer_is_told(
    rig,
):
    timer = await rig.timer()
    s = rig.schedule(every(5))
    await rig.clock.advance(6 * MIN)
    assert rig.ran == []  # nobody told the timer

    s = change_schedule(rig.store, ME, s["id"], now=rig.clock.now())
    timer.changed()
    await rig.clock.settle()
    assert timer.reads == 2 and list(timer.holding()) == [s["id"]]
    await rig.clock.advance(4 * MIN)
    assert [due[11:16] for _, due in rig.ran] == [
        "08:10"
    ]  # 08:05 passed before it was known: not missed

    change_schedule(rig.store, ME, s["id"], now=rig.clock.now(), enabled=False)
    timer.changed()
    await rig.clock.advance(20 * MIN)
    assert len(rig.ran) == 1 and timer.holding() == {}

    change_schedule(
        rig.store, ME, s["id"], now=rig.clock.now(), enabled=True, rule=every(10, rig.clock.now())
    )
    timer.changed()
    await rig.clock.advance(10 * MIN)
    assert len(rig.ran) == 2 and rig.states(s) == [("08:10", "done"), ("08:40", "done")]

    rig.store.delete_schedule(ME, s["id"])
    timer.changed()
    await rig.clock.advance(30 * MIN)
    assert len(rig.ran) == 2


async def test_a_schedule_switched_off_behind_the_timers_back_does_not_run(rig):
    s = rig.schedule(every(5))
    await rig.timer()
    change_schedule(
        rig.store, ME, s["id"], now=rig.clock.now(), enabled=False
    )  # the timer is not told
    await rig.clock.advance(10 * MIN)
    assert rig.ran == [] and rig.runs(s) == []


async def test_a_clock_that_was_set_or_a_computer_that_slept_is_noticed_within_a_minute(rig):
    s = rig.schedule({"kind": "daily", "time": "16:00"})  # six hours away
    await rig.timer()
    await rig.clock.advance(10 * MIN)

    rig.clock.jump(seconds=7 * 60 * MIN)  # the lid was closed for seven hours
    assert rig.ran == []
    await rig.clock.advance(60)

    assert rig.ran == [(s["id"], "2027-06-01T14:00:00+00:00")]
    assert rig.runs(s)[0]["note"] == CAUGHT_UP  # an hour and ten minutes late


async def test_run_now_is_the_same_run_with_the_present_moment_as_its_due_time(rig):
    s = rig.schedule({"kind": "daily", "time": "16:00"})
    timer = await rig.timer()
    rig.hold = asyncio.Event()
    await rig.clock.advance(90)

    row = timer.run_now(ME, s["id"])
    await rig.clock.settle()
    assert row is not None and (row["state"], row["due_at"], row["note"]) == (
        "waiting",
        "2027-06-01T08:01:30+00:00",
        "run now",
    )
    assert rig.ran == [(s["id"], "2027-06-01T08:01:30+00:00")]
    assert timer.run_now(ME, s["id"]) is None  # the same second, pressed twice: one row

    await rig.clock.advance(30)
    again = timer.run_now(ME, s["id"])  # pressed while the first still runs
    assert again is not None and (again["state"], again["note"]) == ("skipped", STILL_RUNNING)

    rig.hold.set()
    await rig.clock.settle()
    assert rig.states(s) == [("08:01", "done"), ("08:02", "skipped")] and len(rig.ran) == 1
    assert (
        rig.store.get_schedule(ME, s["id"])["next_due"] == s["next_due"]
    )  # its own times are not moved


async def test_a_run_left_running_by_an_app_that_closed_does_not_block_the_schedule(rig, tmp_path):
    s = rig.schedule(every(5))
    rig.hold = asyncio.Event()
    await rig.timer()
    await rig.clock.advance(5 * MIN)
    assert rig.states(s) == [("08:05", "running")]
    rig.tasks[0].cancel()  # the engine closes in the middle of the run
    await asyncio.gather(rig.tasks.pop(), return_exceptions=True)
    assert rig.states(s) == [("08:05", "failed")]

    # and if it had been killed outright, the next opening of the store closes what was left
    rig.store.db.exec("UPDATE schedule_runs SET state = 'running', finished_at = NULL")
    rig.store.close_left_working()
    assert rig.states(s) == [("08:05", "failed")]
    rig.hold = None
    await rig.timer()
    await rig.clock.advance(5 * MIN)
    assert rig.states(s)[-1] == ("08:10", "done")


# ---- two timers on one store ---------------------------------------------------------------------


async def test_two_timers_on_one_store_give_one_run(two_stores):
    first, second = two_stores
    rig = Rig(first)
    try:
        a, b = rig.schedule(every(5)), rig.schedule({"kind": "daily", "time": "10:10"})
        one, two = await rig.timer(first), await rig.timer(second)

        await rig.clock.advance(31 * MIN)

        assert [due[11:16] for sid, due in rig.ran if sid == a["id"]] == [
            "08:05",
            "08:10",
            "08:15",
            "08:20",
            "08:25",
            "08:30",
        ]
        assert [due[11:16] for sid, due in rig.ran if sid == b["id"]] == ["08:10"]
        assert rig.states(a) == [
            (t, "done") for t in ("08:05", "08:10", "08:15", "08:20", "08:25", "08:30")
        ]
        assert rig.states(b) == [("08:10", "done")]
        assert (
            one.holding() == two.holding()
        )  # the one that lost learned the next time from the store

        # after an absence: one catch-up run between them, and each missed time written once
        rig.clock.jump(seconds=62 * MIN)
        await rig.clock.advance(60)
        # 08:35 to 09:30 passed: twelve times, of which the last runs and eleven are missed
        assert [s for _, s in rig.states(a)].count("missed") == 11 and len(rig.runs(a)) == 6 + 12
        assert len(rig.ran) == 7 + 1
    finally:
        await rig.close()


def test_a_due_time_is_claimed_once_however_many_try_at_the_same_moment(two_stores):
    first, second = two_stores
    workspace = first.add_workspace(ME, "/projects/one")
    schedule = add_schedule(
        first,
        ME,
        workspace_id=workspace["id"],
        request="r",
        rule=every(5),
        time_zone=ZONE,
        now=START,
    )
    due, following = schedule["next_due"], utc_text(START + timedelta(minutes=10))
    got: list = []
    barrier = threading.Barrier(8)

    def claim(store: CodeStore) -> None:
        barrier.wait()
        got.append(
            store.come_due(
                schedule,
                next_due=following,
                latest=due,
                run_latest=True,
                missed=[Missed(utc_text(START - timedelta(minutes=5)), 3, "earlier")],
            )
        )

    threads = [threading.Thread(target=claim, args=(first if n % 2 else second,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    won = [g for g in got if g is not None]
    assert len(got) == 8 and len(won) == 1  # one claimed it; seven were told no
    assert [(r["state"], r["stands_for"]) for r in won[0]] == [("missed", 3), ("waiting", 1)]
    assert len(first.list_runs(ME, schedule["id"])) == 2
    assert first.get_schedule(ME, schedule["id"])["next_due"] == following
