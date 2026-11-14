"""The coding product's rows, on SQLite and on Postgres (the same tests on both)."""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from wasifyai_code.store import (
    STILL_RUNNING,
    CodeStore,
    Missed,
    NotFound,
    Owner,
    from_text,
    utc_text,
)

ME = Owner("t1", "u1")
OTHER_PERSON = Owner("t1", "u2")
OTHER_TENANT = Owner("t2", "u1")
OTHER_PRODUCT = Owner("t1", "u1", product_id="another-product")
TABLES = ("workspaces", "sessions", "turns", "checks", "checkpoints", "schedules", "schedule_runs")
RULE = {"kind": "daily", "time": "09:00"}
DUE = "2027-06-01T07:00:00+00:00"


def fill(store: CodeStore, owner: Owner = ME) -> dict:
    """One of every row."""
    w = store.add_workspace(
        owner, "/projects/one", name="one", check_command="npm test", check_from="suggested"
    )
    s = store.add_session(owner, w["id"], title="fix the bug", model="first-model")
    t = store.add_turn(owner, s["id"], "fix the bug")
    c = store.add_check(
        owner,
        workspace_id=w["id"],
        session_id=s["id"],
        turn_id=t["id"],
        round=1,
        command="npm test",
        result="failed",
        exit_code=1,
        seconds=2.5,
        output_file="/data/out/1.txt",
        changed_tests=["a.test.ts"],
    )
    k = store.add_checkpoint(
        owner,
        workspace_id=w["id"],
        kind="turn",
        commit_id="c" * 40,
        tree_id="t" * 40,
        label="fix the bug",
        session_id=s["id"],
        turn_id=t["id"],
    )
    d = store.add_schedule(
        owner,
        workspace_id=w["id"],
        request="tidy",
        rule=RULE,
        time_zone="Europe/Berlin",
        next_due=DUE,
    )
    [r] = store.come_due(d, next_due="2027-06-02T07:00:00+00:00", latest=DUE, run_latest=True) or []
    return {
        "workspace": w,
        "session": s,
        "turn": t,
        "check": c,
        "checkpoint": k,
        "schedule": d,
        "run": r,
    }


def test_every_row_carries_the_tenant_the_product_and_the_person(any_store):
    made = fill(any_store)
    for name, row in made.items():
        assert (row["tenant_id"], row["product_id"], row["user_id"]) == (
            "t1",
            "wasifyai-code",
            "u1",
        ), name
    for table in TABLES:  # and in the database itself, for every table there is
        [row] = any_store.db.all(f"SELECT tenant_id, product_id, user_id FROM {table}")
        assert dict(row) == {"tenant_id": "t1", "product_id": "wasifyai-code", "user_id": "u1"}, (
            table
        )


@pytest.mark.parametrize(
    "stranger", [OTHER_PERSON, OTHER_TENANT, OTHER_PRODUCT], ids=["person", "tenant", "product"]
)
def test_nothing_is_seen_or_changed_by_another_person_tenant_or_product(any_store, stranger):
    mine = fill(any_store)
    w, s, t, d = mine["workspace"], mine["session"], mine["turn"], mine["schedule"]

    for get, item in (
        (any_store.get_workspace, w),
        (any_store.get_session, s),
        (any_store.get_turn, t),
        (any_store.get_checkpoint, mine["checkpoint"]),
        (any_store.get_schedule, d),
        (any_store.get_run, mine["run"]),
    ):
        with pytest.raises(NotFound):
            get(stranger, item["id"])
    assert any_store.list_workspaces(stranger) == [] and any_store.list_sessions(stranger) == []
    assert (
        any_store.list_turns(stranger, s["id"]) == [] and any_store.list_schedules(stranger) == []
    )
    assert any_store.list_checks(stranger, session_id=s["id"]) == []
    assert (
        any_store.list_checkpoints(stranger, w["id"]) == []
        and any_store.list_runs(stranger, d["id"]) == []
    )
    with pytest.raises(NotFound):
        any_store.add_session(stranger, w["id"])  # not on somebody else's workspace
    with pytest.raises(NotFound):
        any_store.add_turn(stranger, s["id"], "x")
    with pytest.raises(NotFound):
        any_store.set_check(stranger, w["id"], "true")
    with pytest.raises(NotFound):
        any_store.update_schedule(stranger, d["id"], next_due=None, enabled=False)

    with pytest.raises(NotFound):
        any_store.finish_turn(stranger, t["id"], result="passed")
    any_store.set_session_result(stranger, s["id"], "passed")
    any_store.set_last_pass(stranger, w["id"], "x")
    assert any_store.delete_workspace(stranger, w["id"]) is False
    assert any_store.delete_schedule(stranger, d["id"]) is False
    assert any_store.get_session(ME, s["id"])["result"] == ""
    assert any_store.get_turn(ME, t["id"])["state"] == "working"
    assert any_store.get_workspace(ME, w["id"])["last_pass"] is None
    assert len(any_store.list_runs(ME, d["id"])) == 1


def test_a_workspace_keeps_its_check_command_in_our_store(any_store):
    w = any_store.add_workspace(
        ME, "/projects/one", name="one", check_command="cargo test", check_from="suggested"
    )
    assert (w["check_command"], w["check_from"], w["check_limit_s"], w["last_pass"]) == (
        "cargo test",
        "suggested",
        600,
        None,
    )

    w = any_store.set_check(ME, w["id"], "cargo test --all", limit_s=120)
    assert (w["check_command"], w["check_from"], w["check_limit_s"]) == (
        "cargo test --all",
        "person",
        120,
    )
    w = any_store.set_check(ME, w["id"], "")  # nothing to check with, and it says so
    assert (w["check_command"], w["check_from"], w["check_limit_s"]) == ("", "", 120)

    blank = any_store.add_workspace(ME, "/projects/two")
    assert (blank["check_command"], blank["check_from"]) == ("", "")
    assert [x["path"] for x in any_store.list_workspaces(ME)] == ["/projects/one", "/projects/two"]


def test_turns_are_numbered_in_their_session_and_move_through_their_states(any_store):
    made = fill(any_store)
    s, first = made["session"], made["turn"]
    second = any_store.add_turn(ME, s["id"], "and the other one")
    assert (first["position"], first["state"], first["result"], first["rounds"]) == (
        1,
        "working",
        "",
        0,
    )
    assert second["position"] == 2 and second["workspace_id"] == made["workspace"]["id"]

    any_store.set_turn(ME, first["id"], state="turn_ended")
    any_store.set_turn(
        ME, first["id"], state="checking", rounds=1, checkpoint_id=made["checkpoint"]["id"]
    )
    row = any_store.get_turn(ME, first["id"])
    assert (row["state"], row["rounds"], row["checkpoint_id"]) == (
        "checking",
        1,
        made["checkpoint"]["id"],
    )
    any_store.note_turn(ME, first["id"], "Refused, nobody to ask: rm -rf build")

    row = any_store.finish_turn(
        ME, first["id"], result="failed", why="rounds_used", rounds=3, needs_you=True
    )
    assert (row["state"], row["result"], row["why"], row["rounds"], row["needs_you"]) == (
        "done",
        "failed",
        "rounds_used",
        3,
        True,
    )
    assert row["notes"] == ["Refused, nobody to ask: rm -rf build"] and row["finished_at"]

    # a turn that is over stays as it was said
    any_store.finish_turn(ME, first["id"], result="passed")
    any_store.set_turn(ME, first["id"], state="working")
    assert any_store.get_turn(ME, first["id"])["result"] == "failed"
    assert [t["position"] for t in any_store.list_turns(ME, s["id"])] == [1, 2]


def test_only_the_four_words_and_the_known_states_can_be_written(any_store):
    made = fill(any_store)
    w, s, t = made["workspace"], made["session"], made["turn"]
    errors = (sqlite3.IntegrityError,) if any_store.db.dialect == "sqlite" else (Exception,)
    with pytest.raises(errors):
        any_store.set_session_result(ME, s["id"], "probably fine")
    with pytest.raises(errors):
        any_store.finish_turn(ME, t["id"], result="ok")
    with pytest.raises(errors):
        any_store.set_turn(ME, t["id"], state="thinking")
    with pytest.raises(errors):
        any_store.add_check(
            ME,
            workspace_id=w["id"],
            session_id=s["id"],
            turn_id=t["id"],
            round=1,
            command="x",
            result="",
        )
    with pytest.raises(errors):
        any_store.add_checkpoint(
            ME, workspace_id=w["id"], kind="backup", commit_id="c", tree_id="t"
        )


def test_a_check_row_holds_what_decision_8_asks(any_store):
    made = fill(any_store)
    c = made["check"]
    assert (c["workspace_id"], c["session_id"], c["turn_id"]) == (
        made["workspace"]["id"],
        made["session"]["id"],
        made["turn"]["id"],
    )
    assert (c["round"], c["command"], c["result"], c["seconds"], c["exit_code"]) == (
        1,
        "npm test",
        "failed",
        2.5,
        1,
    )
    assert c["output_file"] == "/data/out/1.txt" and c["changed_tests"] == ["a.test.ts"]
    assert any_store.list_checks(ME, turn_id=made["turn"]["id"]) == [c]
    assert any_store.list_checks(ME, session_id=made["session"]["id"]) == [c]


def test_sessions_are_listed_newest_first_and_by_id(any_store):
    made = fill(any_store)
    w = made["workspace"]
    b = any_store.add_session(ME, w["id"], title="b", origin="schedule")
    any_store.set_place_session(ME, b["id"], "place-1")
    any_store.set_cursor(ME, b["id"], "event-9")
    b = any_store.get_session(ME, b["id"])
    assert (b["origin"], b["place"], b["place_session"], b["last_event"], b["result"]) == (
        "schedule",
        "this-computer",
        "place-1",
        "event-9",
        "",
    )
    assert [s["id"] for s in any_store.list_sessions(ME)] == [b["id"], made["session"]["id"]]
    assert [s["id"] for s in any_store.list_sessions(ME, ids=[made["session"]["id"]])] == [
        made["session"]["id"]
    ]
    assert any_store.list_sessions(ME, workspace_id="another") == []


def test_a_schedule_is_a_row_with_its_rule_its_zone_and_its_next_time(any_store):
    made = fill(any_store)
    d = any_store.get_schedule(ME, made["schedule"]["id"])
    assert (d["request"], d["rule"], d["time_zone"], d["enabled"], d["run_when_missed"]) == (
        "tidy",
        RULE,
        "Europe/Berlin",
        True,
        True,
    )
    assert d["next_due"] == "2027-06-02T07:00:00+00:00"  # moved on when it came due

    d = any_store.update_schedule(
        ME, d["id"], next_due=None, enabled=False, rule={"kind": "daily", "time": "10:00"}
    )
    assert (d["enabled"], d["next_due"], d["rule"], d["request"]) == (
        False,
        None,
        {"kind": "daily", "time": "10:00"},
        "tidy",
    )
    assert any_store.schedules_on() == []  # off: the timer does not hold it
    d = any_store.update_schedule(ME, d["id"], next_due=DUE, enabled=True)
    assert [x["id"] for x in any_store.schedules_on()] == [d["id"]]
    assert (
        any_store.schedule_for_timer(d["id"]) == d and any_store.schedule_for_timer("none") is None
    )


def test_the_timer_sees_every_persons_schedules_and_a_run_belongs_to_its_schedules_owner(any_store):
    mine, theirs = fill(any_store, ME), fill(any_store, OTHER_TENANT)
    assert {s["id"] for s in any_store.schedules_on()} == {
        mine["schedule"]["id"],
        theirs["schedule"]["id"],
    }
    assert (theirs["run"]["tenant_id"], theirs["run"]["user_id"]) == ("t2", "u1")
    assert any_store.list_runs(ME, theirs["schedule"]["id"]) == []


def test_a_due_time_has_one_row_and_the_second_claim_is_told_no(any_store):
    w = any_store.add_workspace(ME, "/projects/one")
    d = any_store.add_schedule(
        ME, workspace_id=w["id"], request="tidy", rule=RULE, time_zone="UTC", next_due=DUE
    )
    following = "2027-06-02T07:00:00+00:00"

    first = any_store.come_due(
        d, next_due=following, latest=DUE, run_latest=True, latest_note="on time"
    )
    second = any_store.come_due(
        d, next_due=following, latest=DUE, run_latest=True
    )  # the same sight of it

    assert first is not None and [(r["state"], r["due_at"], r["note"]) for r in first] == [
        ("waiting", DUE, "on time")
    ]
    assert second is None and len(any_store.list_runs(ME, d["id"])) == 1
    # even past the first guard, the row itself can be written once
    errors = (sqlite3.IntegrityError,) if any_store.db.dialect == "sqlite" else (Exception,)
    with pytest.raises(errors):
        any_store.db.exec(
            "INSERT INTO schedule_runs"
            "(id, tenant_id, product_id, user_id, schedule_id, due_at, state, created_at) "
            "VALUES ('x', 't1', 'wasifyai-code', 'u1', ?, ?, 'waiting', 'now')",
            (d["id"], DUE),
        )


def test_missed_times_and_a_time_skipped_while_a_run_is_going(any_store):
    w = any_store.add_workspace(ME, "/projects/one")
    d = any_store.add_schedule(
        ME, workspace_id=w["id"], request="tidy", rule=RULE, time_zone="UTC", next_due=DUE
    )
    day = timedelta(days=1)
    at = lambda n: utc_text(from_text(DUE) + n * day)  # noqa: E731

    rows = any_store.come_due(
        d,
        next_due=at(3),
        latest=at(2),
        run_latest=True,
        latest_note="caught up",
        missed=[Missed(at(0), 1, "the app was not open"), Missed(at(1), 1, "the app was not open")],
    )
    assert rows is not None
    assert [(r["due_at"], r["state"], r["finished_at"] is None) for r in rows] == [
        (at(0), "missed", False),
        (at(1), "missed", False),
        (at(2), "waiting", True),
    ]
    run = rows[-1]
    assert any_store.start_run(run) is True and any_store.start_run(run) is False

    d = any_store.get_schedule(ME, d["id"])
    [skipped] = any_store.come_due(d, next_due=at(4), latest=at(3), run_latest=True) or []
    assert (skipped["state"], skipped["note"]) == ("skipped", STILL_RUNNING)
    now = any_store.claim_run(d, "2027-06-04T12:00:00+00:00", "run now")  # "Run now", while it runs
    assert now is not None and now["state"] == "skipped"
    assert any_store.claim_run(d, "2027-06-04T12:00:00+00:00") is None

    any_store.finish_run(run, result="passed", session_id="s1")
    done = any_store.get_run(ME, run["id"])
    assert (done["state"], done["result"], done["session_id"], done["note"]) == (
        "done",
        "passed",
        "s1",
        "",
    )
    any_store.finish_run(run, state="failed", note="late")  # a run that is over stays as it was
    assert any_store.get_run(ME, run["id"])["state"] == "done"

    d = any_store.get_schedule(ME, d["id"])
    [not_run] = (
        any_store.come_due(d, next_due=at(5), latest=at(4), run_latest=False, latest_note="too old")
        or []
    )
    assert (not_run["state"], not_run["note"]) == ("missed", "too old")
    [fresh] = (
        any_store.come_due(
            any_store.get_schedule(ME, d["id"]), next_due=None, latest=at(5), run_latest=True
        )
        or []
    )
    assert fresh["state"] == "waiting" and any_store.get_schedule(ME, d["id"])["next_due"] is None


def test_a_schedule_that_was_switched_off_does_not_come_due(any_store):
    w = any_store.add_workspace(ME, "/projects/one")
    d = any_store.add_schedule(
        ME, workspace_id=w["id"], request="tidy", rule=RULE, time_zone="UTC", next_due=DUE
    )
    any_store.update_schedule(ME, d["id"], next_due=DUE, enabled=False)
    assert any_store.come_due(d, next_due=None, latest=DUE, run_latest=True) is None
    assert any_store.list_runs(ME, d["id"]) == []


def test_deleting_a_workspace_takes_its_rows_and_nobody_elses(any_store):
    mine, other = fill(any_store, ME), fill(any_store, OTHER_PERSON)
    assert any_store.delete_workspace(ME, mine["workspace"]["id"]) is True
    for table in TABLES:
        rows = any_store.db.all(f"SELECT user_id FROM {table}")
        assert [dict(r)["user_id"] for r in rows] == ["u2"], table
    assert any_store.get_workspace(OTHER_PERSON, other["workspace"]["id"])
    assert any_store.delete_workspace(ME, mine["workspace"]["id"]) is False


def test_due_times_are_written_one_way_whatever_zone_they_came_in():
    berlin = timezone(timedelta(hours=2))
    assert utc_text(datetime(2027, 6, 1, 9, 0, 0, 999, tzinfo=berlin)) == DUE
    assert utc_text(datetime(2027, 6, 1, 7, 0, tzinfo=UTC)) == DUE
    assert from_text(DUE) == datetime(2027, 6, 1, 7, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="without a zone"):
        utc_text(datetime(2027, 6, 1, 7, 0))


def test_the_desktop_store_is_one_file_and_closes_what_a_closed_app_left(tmp_path: Path):
    store = CodeStore.in_folder(tmp_path / "data")
    made = fill(store)
    store.start_run(made["run"])
    store.close()
    assert (tmp_path / "data" / "code.db").is_file()

    again = CodeStore.in_folder(tmp_path / "data")  # the app opens again
    turn = again.get_turn(ME, made["turn"]["id"])
    assert (turn["state"], turn["result"], turn["why"]) == ("done", "not_checked", "app_closed")
    run = again.get_run(ME, made["run"]["id"])
    assert (run["state"], run["note"]) == ("failed", "It was stopped when the app closed.")
    assert (
        again.get_session(ME, made["session"]["id"])["title"] == "fix the bug"
    )  # the rest is kept
    again.close()


def test_rows_written_in_the_same_instant_are_still_listed_in_the_order_they_were_written(store):
    made = [store.add_workspace(ME, f"/projects/{n}") for n in range(200)]
    assert [w["path"] for w in store.list_workspaces(ME)] == [w["path"] for w in made]
    assert len({w["created_at"] for w in made}) == 200
