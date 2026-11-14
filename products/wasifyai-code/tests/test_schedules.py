"""The plain rules and the one next-due function (ADR-0105, decisions 3 and 4): every kind of rule,
in three time zones with clock changes (north, north, south) and two without the usual hour, across
both clock-change days and the ends of short months. The zone data is the computer's own."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from wasifyai_code.schedules import (
    BadRule,
    Daily,
    Every,
    Monthly,
    Once,
    Weekdays,
    due_times,
    next_due,
    parse_rule,
    rule_data,
    wall_clock,
    zone,
)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@dataclass(frozen=True)
class Zone:
    """A zone and its two clock-change days of 2027, with what each rule of ADR-0105 must give."""

    name: str
    forward: date  # the clocks go forward on this day
    lost: time  # a time that does not exist on it
    after_gap: datetime  # the first moment after the gap (UTC)
    back: date  # the clocks go back on this day
    twice: time  # a time that comes twice on it
    first_time: datetime  # the first of the two (UTC)
    hour_shift: timedelta = timedelta(hours=1)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.name)


NEW_YORK = Zone(
    "America/New_York",
    forward=date(2027, 3, 14),
    lost=time(2, 30),
    after_gap=utc("2027-03-14T07:00"),  # 03:00 EDT
    back=date(2027, 11, 7),
    twice=time(1, 30),
    first_time=utc("2027-11-07T05:30"),  # 01:30 EDT
)
BERLIN = Zone(
    "Europe/Berlin",
    forward=date(2027, 3, 28),
    lost=time(2, 30),
    after_gap=utc("2027-03-28T01:00"),  # 03:00 CEST
    back=date(2027, 10, 31),
    twice=time(2, 30),
    first_time=utc("2027-10-31T00:30"),  # 02:30 CEST
)
SYDNEY = Zone(  # the south: forward in October, back in April
    "Australia/Sydney",
    forward=date(2027, 10, 3),
    lost=time(2, 30),
    after_gap=utc("2027-10-02T16:00"),  # 03:00 AEDT
    back=date(2027, 4, 4),
    twice=time(2, 30),
    first_time=utc("2027-04-03T15:30"),  # 02:30 AEDT
)
LORD_HOWE = Zone(  # its clocks move by half an hour
    "Australia/Lord_Howe",
    forward=date(2027, 10, 3),
    lost=time(2, 15),
    after_gap=utc("2027-10-02T15:30"),  # 02:30 +11
    back=date(2027, 4, 4),
    twice=time(1, 45),
    first_time=utc("2027-04-03T14:45"),  # 01:45 +11
    hour_shift=timedelta(minutes=30),
)
CHANGING = [NEW_YORK, BERLIN, SYDNEY, LORD_HOWE]
KOLKATA = ZoneInfo("Asia/Kolkata")  # no clock changes, and half an hour off the hour


def local(moment: datetime, tz: ZoneInfo) -> datetime:
    return moment.astimezone(tz).replace(tzinfo=None)


def due(rule, tz, after: datetime) -> datetime:
    nxt = next_due(rule, tz, after)
    assert nxt is not None
    return nxt


def run_of(rule, tz, after: datetime, n: int) -> list[datetime]:
    out, at = [], after
    for _ in range(n):
        nxt = next_due(rule, tz, at)
        assert nxt is not None and nxt > at
        out.append(nxt)
        at = nxt
    return out


# ---- the two clock-change rules (decision 4) -----------------------------------------------------


@pytest.mark.parametrize("z", CHANGING, ids=lambda z: z.name)
def test_a_time_that_does_not_exist_runs_at_the_first_moment_after_the_gap(z):
    assert wall_clock(z.forward, z.lost, z.tz) == z.after_gap
    # the second before that moment is still the old offset; the moment itself is the new one
    before, at = z.after_gap - timedelta(seconds=1), z.after_gap
    assert at.astimezone(z.tz).utcoffset() - before.astimezone(z.tz).utcoffset() == z.hour_shift
    for rule in (
        Daily(z.lost),
        Weekdays((z.forward.weekday(),), z.lost),
        Monthly(z.forward.day, z.lost),
        Once(z.forward, z.lost),
    ):
        day_before = wall_clock(z.forward - timedelta(days=1), time(12, 0), z.tz)
        assert next_due(rule, z.tz, day_before) == z.after_gap, rule
        # and once only: the next one is on a later day
        following = next_due(rule, z.tz, z.after_gap)
        assert following is None or local(following, z.tz).date() > z.forward, rule


@pytest.mark.parametrize("z", CHANGING, ids=lambda z: z.name)
def test_a_time_that_comes_twice_runs_the_first_time_only(z):
    assert wall_clock(z.back, z.twice, z.tz) == z.first_time
    second_time = z.first_time + z.hour_shift
    assert local(second_time, z.tz) == local(z.first_time, z.tz)  # the same wall-clock time, twice
    for rule in (
        Daily(z.twice),
        Weekdays((z.back.weekday(),), z.twice),
        Monthly(z.back.day, z.twice),
        Once(z.back, z.twice),
    ):
        day_before = wall_clock(z.back - timedelta(days=1), time(12, 0), z.tz)
        assert next_due(rule, z.tz, day_before) == z.first_time, rule
        following = next_due(rule, z.tz, z.first_time)  # asked between the two: not the second
        assert following is None or local(following, z.tz).date() > z.back, rule
        assert following != second_time


@pytest.mark.parametrize("z", CHANGING, ids=lambda z: z.name)
def test_a_daily_rule_runs_once_on_every_day_of_the_year_at_its_wall_clock_time(z):
    for at in (z.lost, z.twice, time(9, 0), time(0, 0), time(23, 59)):
        start = wall_clock(date(2026, 12, 31), time(23, 59), z.tz)
        dues = run_of(Daily(at), z.tz, start - timedelta(days=1), 366)
        days = [local(d, z.tz).date() for d in dues]
        assert days == [date(2026, 12, 31) + timedelta(days=n) for n in range(366)]  # one a day
        odd = [d for d in dues if local(d, z.tz).time() != at]
        assert odd == ([z.after_gap] if at == z.lost else [])  # the one time that did not exist


@pytest.mark.parametrize("z", CHANGING, ids=lambda z: z.name)
def test_every_so_many_hours_counts_real_time_across_both_clock_changes(z):
    for day in (z.forward, z.back):
        start = wall_clock(day - timedelta(days=1), time(22, 0), z.tz)
        rule = Every(2, "hours", start)
        dues = run_of(rule, z.tz, start - timedelta(seconds=1), 12)
        assert dues[0] == start
        assert {b - a for a, b in zip(dues, dues[1:], strict=False)} == {timedelta(hours=2)}
        walls = [local(d, z.tz) for d in dues]
        gaps = {b - a for a, b in zip(walls, walls[1:], strict=False)}
        assert len(gaps) == 2  # on the wall clock, one of the steps is longer or shorter


@pytest.mark.parametrize("z", CHANGING, ids=lambda z: z.name)
def test_every_so_many_minutes(z):
    start = wall_clock(z.back, time(0, 0), z.tz)
    rule = Every(15, "minutes", start)
    assert next_due(rule, z.tz, start - timedelta(hours=3)) == start  # not before it starts
    assert next_due(rule, z.tz, start) == start + timedelta(minutes=15)  # strictly after
    assert next_due(rule, z.tz, start + timedelta(minutes=44, seconds=59)) == start + timedelta(
        minutes=45
    )
    dues = run_of(rule, z.tz, start, 24 * 4)
    assert dues[-1] - dues[0] == timedelta(hours=24) - timedelta(minutes=15)


# ---- weekdays ------------------------------------------------------------------------------------


@pytest.mark.parametrize("z", CHANGING, ids=lambda z: z.name)
def test_chosen_weekdays_across_a_year(z):
    rule = Weekdays((0, 2, 4), time(8, 15))  # Monday, Wednesday, Friday
    dues = run_of(rule, z.tz, wall_clock(date(2027, 1, 1), time(0, 0), z.tz), 157)
    walls = [local(d, z.tz) for d in dues]
    assert {w.weekday() for w in walls} == {0, 2, 4} and {w.time() for w in walls} == {time(8, 15)}
    assert [w.date() for w in walls[:4]] == [
        date(2027, 1, 1),
        date(2027, 1, 4),
        date(2027, 1, 6),
        date(2027, 1, 8),
    ]
    assert walls[-1].date() == date(2027, 12, 31) and len(set(walls)) == 157  # 52 weeks and a day


def test_the_weekend_only_and_the_same_day_later():
    tz = BERLIN.tz
    rule = Weekdays((5, 6), time(10, 0))
    friday_night = wall_clock(date(2027, 2, 26), time(23, 0), tz)
    assert local(due(rule, tz, friday_night), tz) == datetime(2027, 2, 27, 10, 0)
    saturday_early = wall_clock(date(2027, 2, 27), time(9, 59), tz)
    assert local(due(rule, tz, saturday_early), tz) == datetime(2027, 2, 27, 10, 0)
    saturday_at_ten = wall_clock(date(2027, 2, 27), time(10, 0), tz)
    assert local(due(rule, tz, saturday_at_ten), tz) == datetime(2027, 2, 28, 10, 0)


# ---- the ends of short months --------------------------------------------------------------------


@pytest.mark.parametrize("tz", [z.tz for z in CHANGING] + [KOLKATA], ids=str)
def test_a_day_the_month_does_not_have_means_its_last_day(tz):
    at = time(9, 0)
    start = wall_clock(date(2027, 1, 1), time(0, 0), tz)
    days = lambda rule, n: [local(d, tz).date() for d in run_of(rule, tz, start, n)]  # noqa: E731

    assert days(Monthly(31, at), 14) == [
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
        date(2027, 4, 30),
        date(2027, 5, 31),
        date(2027, 6, 30),
        date(2027, 7, 31),
        date(2027, 8, 31),
        date(2027, 9, 30),
        date(2027, 10, 31),
        date(2027, 11, 30),
        date(2027, 12, 31),
        date(2028, 1, 31),
        date(2028, 2, 29),
    ]
    assert days(Monthly(30, at), 3) == [date(2027, 1, 30), date(2027, 2, 28), date(2027, 3, 30)]
    assert days(Monthly(29, at), 3) == [date(2027, 1, 29), date(2027, 2, 28), date(2027, 3, 29)]
    assert days(Monthly(28, at), 3) == [date(2027, 1, 28), date(2027, 2, 28), date(2027, 3, 28)]
    assert days(Monthly(1, at), 3) == [date(2027, 1, 1), date(2027, 2, 1), date(2027, 3, 1)]
    leap = wall_clock(date(2028, 2, 1), time(0, 0), tz)
    assert local(due(Monthly(30, at), tz, leap), tz) == datetime(2028, 2, 29, 9, 0)
    for d in run_of(Monthly(31, at), tz, start, 14):
        assert local(d, tz).time() == at


def test_the_last_day_rule_on_the_day_itself():
    tz = NEW_YORK.tz
    rule = Monthly(31, time(18, 0))
    before = wall_clock(date(2027, 2, 28), time(17, 59), tz)
    assert local(due(rule, tz, before), tz) == datetime(2027, 2, 28, 18, 0)
    at = wall_clock(date(2027, 2, 28), time(18, 0), tz)
    assert local(due(rule, tz, at), tz) == datetime(2027, 3, 31, 18, 0)


# ---- once, and zones without clock changes -------------------------------------------------------


@pytest.mark.parametrize("tz", [NEW_YORK.tz, BERLIN.tz, SYDNEY.tz, KOLKATA], ids=str)
def test_once_is_due_once(tz):
    rule = Once(date(2027, 6, 15), time(14, 30))
    due = wall_clock(date(2027, 6, 15), time(14, 30), tz)
    assert local(due, tz) == datetime(2027, 6, 15, 14, 30)
    assert next_due(rule, tz, due - timedelta(days=400)) == due
    assert next_due(rule, tz, due - timedelta(seconds=1)) == due
    assert next_due(rule, tz, due) is None and next_due(rule, tz, due + timedelta(days=1)) is None


def test_a_zone_that_is_half_an_hour_off_and_never_changes():
    dues = run_of(Daily(time(9, 0)), KOLKATA, utc("2027-01-01T00:00"), 365)
    assert dues[0] == utc("2027-01-01T03:30")
    assert {b - a for a, b in zip(dues, dues[1:], strict=False)} == {timedelta(days=1)}


def test_the_same_rule_is_a_different_moment_in_each_zone():
    after = utc("2027-06-01T00:00")
    moments = {z.name: next_due(Daily(time(9, 0)), z.tz, after) for z in (NEW_YORK, BERLIN, SYDNEY)}
    assert moments == {
        "America/New_York": utc("2027-06-01T13:00"),
        "Europe/Berlin": utc("2027-06-01T07:00"),
        "Australia/Sydney": utc("2027-06-01T23:00"),
    }


def test_next_due_is_pure_and_strictly_after():
    rule, tz, after = Daily(time(9, 0)), BERLIN.tz, utc("2027-06-01T07:00")  # exactly a due time
    assert next_due(rule, tz, after) == next_due(rule, tz, after) == utc("2027-06-02T07:00")
    with pytest.raises(ValueError, match="without a zone"):
        next_due(rule, tz, datetime(2027, 6, 1, 7, 0))


# ---- the times that passed -----------------------------------------------------------------------


def test_the_times_due_between_two_moments_are_counted_and_the_last_kept():
    tz = NEW_YORK.tz
    first = utc("2027-05-01T13:00")  # 09:00 in New York
    count, times = due_times(Daily(time(9, 0)), tz, first, first + timedelta(days=3, hours=1))
    assert count == 4 and times == [first + timedelta(days=n) for n in range(4)]

    step = Every(5, "minutes", first)
    count, times = due_times(step, tz, first, first + timedelta(days=14), keep=3)
    assert count == 14 * 24 * 12 + 1  # two weeks of five minutes: counted, not walked
    assert times == [first + timedelta(days=14) - timedelta(minutes=m) for m in (10, 5, 0)]
    assert due_times(step, tz, first, first - timedelta(seconds=1)) == (0, [])
    assert due_times(Once(date(2027, 5, 1), time(9, 0)), tz, first, first + timedelta(days=9)) == (
        1,
        [first],
    )


# ---- rules as the store keeps them ---------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "once", "date": "2027-03-14", "time": "09:00"},
        {"kind": "every", "minutes": 5, "start": "2027-03-14T08:00:00+00:00"},
        {"kind": "every", "hours": 2, "start": "2027-03-14T08:00:00+00:00"},
        {"kind": "daily", "time": "23:59"},
        {"kind": "weekdays", "days": [0, 2, 4], "time": "09:00"},
        {"kind": "monthly", "day": 31, "time": "00:00"},
    ],
)
def test_a_rule_reads_and_writes_the_same(data):
    assert rule_data(parse_rule(data)) == data


@pytest.mark.parametrize(
    ("data", "words"),
    [
        (
            {"kind": "every", "minutes": 4, "start": "2027-03-14T08:00:00+00:00"},
            "At least every 5 minutes",
        ),
        (
            {"kind": "every", "hours": 0, "start": "2027-03-14T08:00:00+00:00"},
            "At least every hour",
        ),
        (
            {"kind": "every", "minutes": 5.5, "start": "2027-03-14T08:00:00+00:00"},
            "At least every 5",
        ),
        (
            {"kind": "every", "minutes": 5, "hours": 1, "start": "2027-03-14T08:00:00+00:00"},
            "minutes, or",
        ),
        ({"kind": "every", "minutes": 5}, "starts from"),
        ({"kind": "every", "minutes": 5, "start": "2027-03-14T08:00:00"}, "starts from"),
        ({"kind": "daily", "time": "25:00"}, "hours and minutes"),
        ({"kind": "daily", "time": "nine"}, "hours and minutes"),
        ({"kind": "daily"}, "hours and minutes"),
        ({"kind": "weekdays", "days": [], "time": "09:00"}, "at least one day"),
        ({"kind": "weekdays", "days": [7], "time": "09:00"}, "0 (Monday) to 6"),
        ({"kind": "monthly", "day": 0, "time": "09:00"}, "1 to 31"),
        ({"kind": "monthly", "day": 32, "time": "09:00"}, "1 to 31"),
        ({"kind": "once", "date": "2027-02-30", "time": "09:00"}, "a year, a month and a day"),
        ({"kind": "cron", "text": "*/5 * * * *"}, "none of"),
        ({}, "none of"),
    ],
)
def test_a_rule_that_cannot_be_used_is_refused_in_words(data, words):
    with pytest.raises(BadRule, match=words.replace("(", r"\(").replace(")", r"\)")):
        parse_rule(data)


def test_weekdays_are_kept_once_each_and_in_order():
    assert parse_rule({"kind": "weekdays", "days": [4, 0, 4], "time": "07:05"}) == Weekdays(
        (0, 4), time(7, 5)
    )


def test_a_zone_the_computer_does_not_know_is_refused():
    assert zone("Europe/Berlin").key == "Europe/Berlin"
    for bad in ("Mars/Olympus_Mons", "", "../etc/passwd"):
        with pytest.raises(BadRule, match="not a time zone"):
            zone(bad)
