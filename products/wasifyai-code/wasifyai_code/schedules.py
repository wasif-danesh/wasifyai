"""Scheduled runs: plain rules, one pure next-due function and one timer (ADR-0105).

**A rule is plain, not cron text** (decision 3). As the store keeps it:

    {"kind": "once", "date": "2027-03-14", "time": "09:00"}
    {"kind": "every", "minutes": 15, "start": "2027-03-14T08:00:00+00:00"}   five at least
    {"kind": "every", "hours": 2, "start": "2027-03-14T08:00:00+00:00"}
    {"kind": "daily", "time": "09:00"}
    {"kind": "weekdays", "days": [0, 2, 4], "time": "09:00"}                 0 is Monday
    {"kind": "monthly", "day": 31, "time": "09:00"}                          or the last day

Dates and times are the person's wall-clock times in the schedule's time zone. An "every" rule is
the exception: it counts real time from its `start` and a clock change does not move it.

`next_due(rule, zone, after)` is the one place that knows when a rule comes due. It is pure: no
clock, no store. The two clock-change rules (decision 4) are in `wall_clock`:

- a time that does not exist on the day the clocks go forward runs at the first moment after the
  gap;
- a time that comes twice when they go back runs the first time only.

`Timer` is the one timer for every schedule (decisions 5 to 9). It holds each schedule's next due
time in memory, sleeps until the earliest and never longer than a minute, and reads the store only
at start, when told a schedule changed, and when one comes due. A due time is claimed by writing
its row (`CodeStore.come_due`), so two timers on one store give one run. After an absence the
latest missed time runs once if it is less than a day old and the schedule says so; the rest are
written down as missed. A time that comes while the schedule's earlier run is still going is
written down as skipped.

What a run *does* is not here. The timer is given a `runner`; the stage that wires this in gives
it one that makes the copy of the workspace and calls `Loop.run_turn(..., unattended=True)`.

`zoneinfo` reads the computer's own time zone data. Windows has none, and would need the `tzdata`
package: a dependency to ask for when Windows comes (it is not in v1).
"""

import asyncio
import calendar
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wasifyai_code.store import (
    LEFT_WORKING,
    RUN_DONE,
    RUN_FAILED,
    RUN_WAITING,
    CodeStore,
    Missed,
    Owner,
    from_text,
    utc_text,
)

LEAST_MINUTES = 5
MAX_SLEEP_S = 60.0  # decision 6
CATCH_UP = timedelta(days=1)  # decision 8: a missed time older than this is not run
ON_TIME = timedelta(seconds=90)  # later than this, the time was missed (the app was away)
MISSED_ROWS = 20  # after a long absence: this many missed times get a row each, one row the rest

NOT_OPEN = "the app was not open"
CAUGHT_UP = "run late: the app was not open at its time"
RUN_NOW = "run now"


class BadRule(ValueError):
    """The rule cannot be used. The message is for the person."""


# ---- the rules -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Once:
    date: date
    time: time


@dataclass(frozen=True)
class Every:
    every: int
    unit: str  # "minutes" | "hours"
    start: datetime  # the first time it is due; then every so often after it, in real time

    @property
    def step(self) -> timedelta:
        return timedelta(**{self.unit: self.every})


@dataclass(frozen=True)
class Daily:
    time: time


@dataclass(frozen=True)
class Weekdays:
    days: tuple[int, ...]  # 0 is Monday
    time: time


@dataclass(frozen=True)
class Monthly:
    day: int  # 1 to 31; a month without that day means its last day
    time: time


Rule = Once | Every | Daily | Weekdays | Monthly


def _time(value: Any) -> time:
    try:
        hour, minute = str(value).split(":")
        return time(int(hour), int(minute))
    except ValueError:
        raise BadRule("The time must be hours and minutes, like 09:00.") from None


def _whole(value: Any, least: int, most: int, words: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not least <= value <= most:
        raise BadRule(words)
    return value


def parse_rule(data: dict[str, Any]) -> Rule:
    """A rule from what the store keeps. Anything else is refused in plain words."""
    kind = data.get("kind")
    if kind == "once":
        try:
            day = date.fromisoformat(str(data.get("date")))
        except ValueError:
            raise BadRule("The date must be a year, a month and a day, like 2027-03-14.") from None
        return Once(day, _time(data.get("time")))
    if kind == "every":
        if ("minutes" in data) == ("hours" in data):
            raise BadRule("Say every so many minutes, or every so many hours.")
        try:
            start = datetime.fromisoformat(str(data.get("start")))
        except ValueError:
            raise BadRule("The rule needs the moment it starts from.") from None
        if start.tzinfo is None:
            raise BadRule("The rule needs the moment it starts from.")
        if "minutes" in data:
            n = _whole(
                data["minutes"], LEAST_MINUTES, 10**6, f"At least every {LEAST_MINUTES} minutes."
            )
            return Every(n, "minutes", start.astimezone(UTC))
        return Every(
            _whole(data["hours"], 1, 10**5, "At least every hour."), "hours", start.astimezone(UTC)
        )
    if kind == "daily":
        return Daily(_time(data.get("time")))
    if kind == "weekdays":
        days = data.get("days")
        if not isinstance(days, list) or not days:
            raise BadRule("Choose at least one day of the week.")
        chosen = {
            _whole(d, 0, 6, "A day of the week is a number from 0 (Monday) to 6.") for d in days
        }
        return Weekdays(tuple(sorted(chosen)), _time(data.get("time")))
    if kind == "monthly":
        day = _whole(data.get("day"), 1, 31, "The day of the month is a number from 1 to 31.")
        return Monthly(day, _time(data.get("time")))
    raise BadRule("The rule is none of: once, every, daily, weekdays, monthly.")


def rule_data(rule: Rule) -> dict[str, Any]:
    """A rule as the store keeps it."""
    at = lambda t: f"{t.hour:02d}:{t.minute:02d}"  # noqa: E731
    if isinstance(rule, Once):
        return {"kind": "once", "date": rule.date.isoformat(), "time": at(rule.time)}
    if isinstance(rule, Every):
        return {"kind": "every", rule.unit: rule.every, "start": utc_text(rule.start)}
    if isinstance(rule, Daily):
        return {"kind": "daily", "time": at(rule.time)}
    if isinstance(rule, Weekdays):
        return {"kind": "weekdays", "days": list(rule.days), "time": at(rule.time)}
    return {"kind": "monthly", "day": rule.day, "time": at(rule.time)}


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise BadRule(f"{name} is not a time zone this computer knows.") from None


# ---- when a rule comes due -----------------------------------------------------------------------


def wall_clock(day: date, at: time, tz: ZoneInfo) -> datetime:
    """The moment (UTC) a wall-clock date and time stands for in a zone.

    Most times exist once. A time that comes twice (the clocks went back) is its first time. A
    time that does not exist (the clocks went forward over it) is the first moment after the gap."""
    naive = datetime.combine(day, at)
    first = naive.replace(tzinfo=tz, fold=0).astimezone(UTC)
    if first.astimezone(tz).replace(tzinfo=None) == naive:
        return first  # it exists; if twice, `fold=0` is the first of the two
    # In a gap. Read with the offset from before the change, `first` lies after it; read with the
    # one from after, `second` lies before it. The change itself is between the two.
    second = naive.replace(tzinfo=tz, fold=1).astimezone(UTC)
    after_change = first.astimezone(tz).utcoffset()
    low, high = int(second.timestamp()), int(first.timestamp())
    while high - low > 1:  # the first second at which the new offset holds
        middle = (low + high) // 2
        if datetime.fromtimestamp(middle, UTC).astimezone(tz).utcoffset() == after_change:
            high = middle
        else:
            low = middle
    return datetime.fromtimestamp(high, UTC)


def _on(rule: Daily | Weekdays | Monthly, day: date) -> bool:
    if isinstance(rule, Weekdays):
        return day.weekday() in rule.days
    if isinstance(rule, Monthly):
        return day.day == min(rule.day, calendar.monthrange(day.year, day.month)[1])
    return True


def next_due(rule: Rule, tz: ZoneInfo, after: datetime) -> datetime | None:
    """The first moment (UTC) the rule is due strictly after `after`. `None` when there is none (a
    "once" whose time has passed). Pure: the same answer for the same three things, always."""
    if after.tzinfo is None:
        raise ValueError("a time without a zone")
    after = after.astimezone(UTC)
    if isinstance(rule, Every):
        if after < rule.start:
            return rule.start
        return rule.start + ((after - rule.start) // rule.step + 1) * rule.step
    if isinstance(rule, Once):
        due = wall_clock(rule.date, rule.time, tz)
        return due if due > after else None
    day = after.astimezone(tz).date() - timedelta(days=1)
    for _ in range(64):  # a month at most lies between two due days; the rest is room
        if _on(rule, day):
            due = wall_clock(day, rule.time, tz)
            if due > after:
                return due
        day += timedelta(days=1)
    return None


def due_times(
    rule: Rule, tz: ZoneInfo, first: datetime, until: datetime, keep: int = MISSED_ROWS + 1
) -> tuple[int, list[datetime]]:
    """The times the rule was due from `first` (a due time itself) to `until`: how many there are,
    and the last `keep` of them."""
    if first > until:
        return 0, []
    if isinstance(rule, Every):  # there can be very many: counted, not walked
        count = (until - first) // rule.step + 1
        return count, [first + n * rule.step for n in range(max(0, count - keep), count)]
    count, last, at = 0, deque[datetime](maxlen=keep), first
    while at is not None and at <= until:
        count += 1
        last.append(at)
        at = next_due(rule, tz, at)
    return count, list(last)


# ---- making and changing a schedule --------------------------------------------------------------


def add_schedule(
    store: CodeStore,
    owner: Owner,
    *,
    workspace_id: str,
    request: str,
    rule: dict[str, Any],
    time_zone: str,
    now: datetime,
    run_when_missed: bool = True,
    enabled: bool = True,
) -> dict[str, Any]:
    """Check the rule and the zone, work out the first due time and write the row. Tell the timer
    afterwards (`Timer.changed`)."""
    parsed, tz = parse_rule(rule), zone(time_zone)
    due = next_due(parsed, tz, now)
    return store.add_schedule(
        owner,
        workspace_id=workspace_id,
        request=request,
        rule=rule_data(parsed),
        time_zone=time_zone,
        next_due=utc_text(due) if due else None,
        enabled=enabled,
        run_when_missed=run_when_missed,
    )


def change_schedule(
    store: CodeStore,
    owner: Owner,
    schedule_id: str,
    *,
    now: datetime,
    request: str | None = None,
    rule: dict[str, Any] | None = None,
    time_zone: str | None = None,
    enabled: bool | None = None,
    run_when_missed: bool | None = None,
) -> dict[str, Any]:
    """Change a schedule; its next due time is worked out again from now, so nothing that passed
    while it was off, or under the old rule, counts as missed."""
    have = store.get_schedule(owner, schedule_id)
    parsed = parse_rule(rule if rule is not None else have["rule"])
    tz = zone(time_zone if time_zone is not None else have["time_zone"])
    due = next_due(parsed, tz, now)
    return store.update_schedule(
        owner,
        schedule_id,
        next_due=utc_text(due) if due else None,
        request=request,
        rule=rule_data(parsed) if rule is not None else None,
        time_zone=time_zone,
        enabled=enabled,
        run_when_missed=run_when_missed,
    )


# ---- the clock -----------------------------------------------------------------------------------


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class PretendClock:
    """A clock for tests. Time passes only when the test says so: `advance` lets it pass, waking
    each sleeper when its time comes; `jump` moves the clock without anyone noticing, as when the
    computer slept or the clock was set (a sleeper still has to finish its sleep)."""

    def __init__(self, start: datetime):
        self._now = start.astimezone(UTC)
        self._sleepers: list[list[Any]] = []  # [seconds left, future]
        self.sleeps: list[float] = []  # every sleep that was asked for

    def now(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        entry = [max(0.0, seconds), asyncio.get_running_loop().create_future()]
        self._sleepers.append(entry)
        try:
            await entry[1]
        finally:
            self._sleepers.remove(entry)

    def jump(self, *, seconds: float = 0, to: datetime | None = None) -> None:
        self._now = to.astimezone(UTC) if to is not None else self._now + timedelta(seconds=seconds)

    async def advance(self, seconds: float = 0, *, to: datetime | None = None) -> None:
        left = (to.astimezone(UTC) - self._now).total_seconds() if to is not None else seconds
        await self.settle()
        while True:
            live = [s for s in self._sleepers if not s[1].done()]
            soon = min((s[0] for s in live), default=None)
            if soon is None or soon > left:
                break
            for s in live:
                s[0] -= soon
            self._now += timedelta(seconds=soon)
            left -= soon
            for s in live:
                if s[0] <= 0:
                    s[1].set_result(None)
            await self.settle()
        for s in self._sleepers:
            s[0] -= left
        self._now += timedelta(seconds=left)
        await self.settle()

    @staticmethod
    async def settle() -> None:
        """Let everything that can run without time passing, run."""
        for _ in range(200):
            await asyncio.sleep(0)


# ---- the timer -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    """What a run came to: one of the four result words, and the session that ran."""

    result: str = ""
    session_id: str | None = None
    note: str = ""


Runner = Callable[[dict[str, Any], dict[str, Any]], Awaitable[RunResult]]
"""Does one run: given the schedule row and the run row. Raising means the run failed."""


class Timer:
    """The one timer. `serve()` runs until it is cancelled."""

    def __init__(self, store: CodeStore, runner: Runner, *, clock: Clock | None = None):
        self.store, self.runner, self.clock = store, runner, clock or SystemClock()
        self._due: dict[str, datetime] = {}
        self._earliest: datetime | None = None
        self._changed = asyncio.Event()
        self._line: asyncio.Queue[tuple[dict[str, Any], dict[str, Any]]] = asyncio.Queue()
        self.reads = 0  # how many times the store was read
        self.wakes = 0  # how many times the timer looked at the clock

    def changed(self) -> None:
        """A schedule was made, changed or removed: read the store again."""
        self._changed.set()

    def holding(self) -> dict[str, datetime]:
        """The next due time of each schedule the timer holds."""
        return dict(self._due)

    async def serve(self) -> None:
        worker = asyncio.ensure_future(self._work())
        try:
            self._load()
            while True:
                self.wakes += 1
                now = self.clock.now()
                if self._earliest is not None and now >= self._earliest:  # the one comparison
                    self._come_due(now)
                    continue
                left = (
                    MAX_SLEEP_S
                    if self._earliest is None
                    else (self._earliest - now).total_seconds()
                )
                if await self._sleep(min(MAX_SLEEP_S, left)):
                    self._load()
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    def run_now(self, owner: Owner, schedule_id: str) -> dict[str, Any] | None:
        """ "Run now": the same run, with the present moment as its due time (decision 10). Gives
        the run's row: `waiting` when it will run, `skipped` when the schedule's earlier run is
        still going. `None` when this very second was already claimed."""
        schedule = self.store.get_schedule(owner, schedule_id)
        row = self.store.claim_run(schedule, utc_text(self.clock.now()), RUN_NOW)
        if row is not None and row["state"] == RUN_WAITING:
            self._line.put_nowait((schedule, row))
        return row

    # ---- inside ----------------------------------------------------------------------------------

    def _load(self) -> None:
        self.reads += 1
        self._due = {s["id"]: from_text(s["next_due"]) for s in self.store.schedules_on()}
        self._earliest = min(self._due.values(), default=None)

    def _hold(self, schedule_id: str, due: datetime | None) -> None:
        if due is None:
            self._due.pop(schedule_id, None)
        else:
            self._due[schedule_id] = due
        self._earliest = min(self._due.values(), default=None)

    async def _sleep(self, seconds: float) -> bool:
        """Sleep, or wake early because a schedule changed. True when one changed."""
        if not self._changed.is_set():
            sleeping = asyncio.ensure_future(self.clock.sleep(seconds))
            changed = asyncio.ensure_future(self._changed.wait())
            try:
                await asyncio.wait({sleeping, changed}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in (sleeping, changed):
                    task.cancel()
                await asyncio.gather(sleeping, changed, return_exceptions=True)
        if self._changed.is_set():
            self._changed.clear()
            return True
        return False

    def _come_due(self, now: datetime) -> None:
        for schedule_id in sorted(
            (s for s, at in self._due.items() if at <= now), key=self._due.__getitem__
        ):
            self.reads += 1
            schedule = self.store.schedule_for_timer(
                schedule_id
            )  # as it is now, not as we remember
            if schedule is None or not schedule["enabled"] or not schedule["next_due"]:
                self._hold(schedule_id, None)
                continue
            first = from_text(schedule["next_due"])
            if first > now:  # another timer has dealt with it
                self._hold(schedule_id, first)
                continue
            try:
                rule, tz = parse_rule(schedule["rule"]), zone(schedule["time_zone"])
            except BadRule:
                self._hold(schedule_id, None)  # a row we cannot read is not run and not spun on
                continue
            count, times = due_times(rule, tz, first, now)
            latest, earlier = times[-1], times[:-1]
            late = now - latest
            if late <= ON_TIME:
                run, note = True, ""
            elif late < CATCH_UP and schedule["run_when_missed"]:
                run, note = True, CAUGHT_UP
            else:
                run, note = False, NOT_OPEN
            missed = [Missed(utc_text(t), 1, NOT_OPEN) for t in earlier]
            if count - 1 > len(earlier):  # too many to list: one row stands for the oldest of them
                missed.insert(0, Missed(utc_text(first), count - 1 - len(earlier), NOT_OPEN))
            following = next_due(rule, tz, now)
            written = self.store.come_due(
                schedule,
                next_due=utc_text(following) if following else None,
                latest=utc_text(latest),
                run_latest=run,
                latest_note=note,
                missed=missed,
            )
            if written is None:  # another timer claimed it between our read and our write
                self.reads += 1
                again = self.store.schedule_for_timer(schedule_id)
                on = again is not None and again["enabled"] and again["next_due"]
                self._hold(schedule_id, from_text(again["next_due"]) if again and on else None)
                continue
            self._hold(schedule_id, following)
            for row in written:
                if row["state"] == RUN_WAITING:
                    self._line.put_nowait((schedule, row))

    async def _work(self) -> None:
        """Runs wait in line and go one at a time (decision 9, on the desktop)."""
        while True:
            schedule, run = await self._line.get()
            if not self.store.start_run(run):
                continue
            try:
                outcome = await self.runner(schedule, run)
            except asyncio.CancelledError:
                self.store.finish_run(run, state=RUN_FAILED, note=LEFT_WORKING)
                raise
            except Exception as e:  # noqa: BLE001  (a run that fails is written down, the timer goes on)
                self.store.finish_run(run, state=RUN_FAILED, note=str(e)[:500] or type(e).__name__)
            else:
                self.store.finish_run(
                    run,
                    state=RUN_DONE,
                    result=outcome.result,
                    note=outcome.note or run["note"],
                    session_id=outcome.session_id,
                )
