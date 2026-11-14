# ruff: noqa: E501  (test data is easier to read on one line)
"""Sessions that change files (stage C2), on the pretended place: the checkpoint around a turn,
the question before a change Undo cannot put back, "Allow for this project", the Changes tab's
data, undo and bringing back. Real files, a real git and a real store; only the agent is
pretended."""

import asyncio
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_code_sessions import ME, Gateway, Index
from wasifyai_code import place as places
from wasifyai_code import rules
from wasifyai_code import store as rows
from wasifyai_code.place import FakePlace, FakeTurn, scripted
from wasifyai_code.runtime import ASK_KIND, INTERRUPT, UNDONE_NOTE, Refused, Sessions
from wasifyai_code.store import CodeStore


@pytest.fixture
def world(tmp_path: Path):
    data = tmp_path / "appdata"
    project = tmp_path / "bakery-site"
    (project / "src").mkdir(parents=True)
    (project / "src" / "home.html").write_text("<h1>Bakery</h1>\n<p>Welcome</p>\n")
    (project / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (project / "run.sh").chmod(0o755)
    (project / "old.txt").write_text("old\n")
    (project / ".gitignore").write_text(".env\nbuild/\n")
    (project / ".env").write_text("KEY=1\n")
    store = CodeStore.in_folder(data / "code")
    state = SimpleNamespace(
        code_store=store, code_sessions=None, coding_server=object(), coding_gateway=Gateway(),
        creation_index=Index(), desktop_dir=data,
    )  # fmt: skip
    yield SimpleNamespace(state=state, store=store, project=project, data=data)
    store.close()


def sessions(world, agent) -> tuple[Sessions, FakePlace]:
    place = FakePlace(agent)
    made = Sessions(world.state, place=place)
    world.state.code_sessions = made
    return made, place


def listing(folder: Path) -> dict[str, tuple[bytes, int]]:
    """Every file under a folder: its bytes and its permissions."""
    out = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file() and ".git" not in path.relative_to(folder).parts[:1]:
            out[str(path.relative_to(folder))] = (
                path.read_bytes(),
                stat.S_IMODE(path.stat().st_mode),
            )
    return out


async def hours(turn: FakeTurn) -> str | None:
    """A turn that changes one file, adds one, deletes one and changes a script that runs."""
    await turn.edit("src/home.html", "<h1>Bakery</h1>\n<p>Open 9 to 5</p>\n", command="str_replace")
    await turn.edit("tests/home.test.js", "test('hours', () => {})\n")
    turn.delete("old.txt")
    await turn.edit("run.sh", "#!/bin/sh\necho hours\n", command="str_replace")
    turn.say("Done.")
    return None


async def start(live: Sessions, world, mode=rows.ASK) -> dict:
    return await live.start(ME, folder=str(world.project), mode=mode)


async def turn_of(live: Sessions, session: dict, text="Add the opening hours") -> dict:
    await live.send(ME, session["id"], text)
    return await live.wait(ME, session["id"])


def kept(live: Sessions, session: dict, name: str) -> list[dict]:
    return [e for e in live.feed(session["id"]).kept if e["event"] == name]


async def card(live: Sessions, session: dict) -> dict:
    """Wait for the approval card of the turn in flight."""
    for _ in range(400):
        found = kept(live, session, INTERRUPT)
        if found and live.view(ME, session["id"])["waiting"]:
            return found[-1]
        await asyncio.sleep(0.01)
    raise AssertionError("no card came")


# ---- a turn that changes files -------------------------------------------------------------------


async def test_a_turn_is_kept_before_and_after_and_its_changes_are_counted(world):
    live, _ = sessions(world, hours)
    made = await start(live, world)
    closed = await turn_of(live, made)
    assert closed["why"] == places.FINISHED and closed["changed"] == 4
    # nothing asked: none of these files is one Undo cannot put back
    assert kept(live, made, INTERRUPT) == []
    done = kept(live, made, "code_state")[-1]
    assert done["state"] == "done" and done["changed"] == 4
    # the checkpoints are under the app's data, and nothing of ours is in the project
    workspace = world.store.list_workspaces(ME)[0]
    assert (world.data / "code" / "checkpoints" / workspace["id"] / "HEAD").is_file()
    assert not (world.project / ".git").exists()
    assert sorted(p.name for p in world.project.iterdir()) == [
        ".env",
        ".gitignore",
        "run.sh",
        "src",
        "tests",
    ]
    (shown,) = live.turns(ME, made["id"])
    assert (
        shown["changed"] == 4
        and shown["can_undo"]
        and not shown["undone"]
        and not shown["can_redo"]
    )


async def test_the_changes_tab_lists_each_file_and_shows_it_before_and_after(world):
    live, _ = sessions(world, hours)
    made = await start(live, world)
    closed = await turn_of(live, made)
    (item,) = (await live.changes(ME, made["id"]))["items"]
    assert item["turn_id"] == closed["id"] and item["can_undo"] and not item["undone"]
    assert {(f["path"], f["what"], f["test"]) for f in item["files"]} == {
        ("src/home.html", "changed", False), ("tests/home.test.js", "added", True),
        ("old.txt", "deleted", False), ("run.sh", "changed", False),
    }  # fmt: skip
    one = await live.change(ME, made["id"], closed["id"], "src/home.html")
    assert one["what"] == "changed" and one["before"].endswith("<p>Welcome</p>\n")
    assert [(line["t"], line["text"]) for line in one["lines"]] == [
        ("same", "<h1>Bakery</h1>"), ("del", "<p>Welcome</p>"), ("add", "<p>Open 9 to 5</p>"),
    ]  # fmt: skip
    new = await live.change(ME, made["id"], closed["id"], "tests/home.test.js")
    assert new["what"] == "added" and new["before"] is None and new["test"]
    gone = await live.change(ME, made["id"], closed["id"], "old.txt")
    assert (
        gone["what"] == "deleted"
        and gone["after"] is None
        and gone["lines"] == [{"t": "del", "text": "old", "a": 1}]
    )
    with pytest.raises(Refused):
        await live.change(ME, made["id"], closed["id"], "no/such.txt")


async def test_a_binary_file_is_named_and_not_shown(world):
    async def picture(turn: FakeTurn) -> str | None:
        turn.write("logo.png", b"\x89PNG\x00\x00\x01")
        return None

    live, _ = sessions(world, picture)
    made = await start(live, world, rows.OWN)
    closed = await turn_of(live, made)
    one = await live.change(ME, made["id"], closed["id"], "logo.png")
    assert one["binary"] and one["after"] is None and one["lines"] == []


async def test_plan_takes_no_checkpoint_and_counts_nothing(world):
    async def look(turn: FakeTurn) -> str | None:
        turn.step("glob", pattern="*")
        turn.say("A bakery.")
        return None

    live, _ = sessions(world, look)
    made = await start(live, world, rows.PLAN)
    closed = await turn_of(live, made, "What is this?")
    assert closed["changed"] == 0 and closed["checkpoint_id"] is None
    assert "changed" not in kept(live, made, "code_state")[-1]
    assert not (world.data / "code" / "checkpoints").exists()
    assert (await live.changes(ME, made["id"]))["items"] == []


# ---- asking ----------------------------------------------------------------------------------------


async def secret(turn: FakeTurn) -> str | None:
    wrote = await turn.edit(".env", "KEY=2\n", command="str_replace")
    turn.say("Changed." if wrote else "I left .env alone.")
    return None


async def test_a_change_undo_cannot_put_back_waits_for_a_yes(world):
    live, place = sessions(world, secret)
    made = await start(live, world)
    await live.send(ME, made["id"], "Set the key to 2")
    asked = await card(live, made)
    assert asked["kind"] == ASK_KIND and asked["interrupt_id"]
    assert asked["payload"] == {
        "ask": rules.NOT_UNDOABLE, "step_id": asked["payload"]["step_id"], "tool": "file_editor",
        "command": "str_replace", "path": ".env", "says": "", "project": "bakery-site",
        "undo": False, "steps": 1,
    }  # fmt: skip
    # nothing has run while it waits
    assert (world.project / ".env").read_text() == "KEY=1\n"
    assert live.view(ME, made["id"])["working"]
    assert await live.answer(ME, made["id"], asked["interrupt_id"], rules.YES)
    closed = await live.wait(ME, made["id"])
    assert (world.project / ".env").read_text() == "KEY=2\n" and closed["answer"] == "Changed."
    result = kept(live, made, "tool_result")[-1]
    assert result["status"] == "ok" and result["output"]["answer"] == "yes"
    assert result["id"] == asked["payload"]["step_id"]
    assert not live.view(ME, made["id"])["waiting"]
    # an ignored file is not among a turn's changes: Undo does not know it
    assert closed["changed"] == 0
    # a second answer finds nothing waiting
    assert not await live.answer(ME, made["id"], asked["interrupt_id"], rules.NO)
    # and the next change of that kind asks again: a yes was for once
    await live.send(ME, made["id"], "Again")
    await card(live, made)
    await live.stop(ME, made["id"])


async def test_a_no_leaves_the_file_and_the_agent_is_told(world):
    live, place = sessions(world, secret)
    made = await start(live, world)
    await live.send(ME, made["id"], "Set the key to 2")
    asked = await card(live, made)
    await live.answer(ME, made["id"], asked["interrupt_id"], rules.NO)
    closed = await live.wait(ME, made["id"])
    assert (world.project / ".env").read_text() == "KEY=1\n"
    assert closed["answer"] == "I left .env alone." and closed["why"] == places.FINISHED
    result = kept(live, made, "tool_result")[-1]
    assert result["status"] == "refused" and result["output"]["answer"] == "no"
    said = [c for c in place.calls if c[0] == "answer"][-1]
    assert said[3] is False and "said no" in said[4]


async def test_allow_for_this_project_stops_the_question_until_it_is_taken_back(world):
    live, _ = sessions(world, secret)
    made = await start(live, world)
    before = live.project(ME, made["id"])
    assert before["mode"] == rows.ASK and before["project"] == "bakery-site"
    assert before["kinds"] == [
        {"id": "not_undoable", "allowed": False, "asked_now": True},
        {"id": "delete", "allowed": False, "asked_now": True},
        {"id": "install", "allowed": False, "asked_now": True},
    ]
    await live.send(ME, made["id"], "Set the key to 2")
    asked = await card(live, made)
    await live.answer(ME, made["id"], asked["interrupt_id"], rules.ALLOW)
    await live.wait(ME, made["id"])
    assert kept(live, made, "tool_result")[-1]["output"]["answer"] == "allow"
    assert live.project(ME, made["id"])["kinds"][0]["allowed"]
    # the next one runs with no card, and is marked so that it is never hidden
    await turn_of(live, made, "Again")
    assert len(kept(live, made, INTERRUPT)) == 1
    assert kept(live, made, "tool_result")[-1]["output"]["answer"] == "allowed"
    # it is for this project and this person: another project starts with nothing allowed
    other = world.project.parent / "other-site"
    other.mkdir()
    second = await live.start(ME, folder=str(other), mode=rows.ASK)
    assert not any(k["allowed"] for k in live.project(ME, second["id"])["kinds"])
    # taken back: it asks again
    assert not live.allow(ME, made["id"], "not_undoable", False)["kinds"][0]["allowed"]
    await live.send(ME, made["id"], "Once more")
    await card(live, made)
    await live.stop(ME, made["id"])
    with pytest.raises(Refused):
        live.allow(ME, made["id"], "anything", True)


async def test_work_on_its_own_asks_nothing_and_the_mode_holds_from_the_next_change(world):
    live, _ = sessions(world, secret)
    made = await start(live, world, rows.OWN)
    await turn_of(live, made)
    assert (world.project / ".env").read_text() == "KEY=2\n" and kept(live, made, INTERRUPT) == []
    assert "answer" not in kept(live, made, "tool_result")[-1]["output"]
    # back to "Ask me": the same conversation, and the next change is asked
    place_session = world.store.get_session(ME, made["id"])["place_session"]
    assert (await live.set_mode(ME, made["id"], rows.ASK))["mode"] == rows.ASK
    assert world.store.get_session(ME, made["id"])["place_session"] == place_session
    await live.send(ME, made["id"], "Again")
    await card(live, made)
    await live.stop(ME, made["id"])


async def test_stop_while_a_card_waits_ends_the_turn_and_nothing_runs(world):
    live, _ = sessions(world, secret)
    made = await start(live, world)
    await live.send(ME, made["id"], "Set the key to 2")
    asked = await card(live, made)
    assert await live.stop(ME, made["id"])
    closed = live.turns(ME, made["id"])[-1]
    assert closed["why"] == places.STOPPED and (world.project / ".env").read_text() == "KEY=1\n"
    assert not live.view(ME, made["id"])["waiting"]
    assert not await live.answer(ME, made["id"], asked["interrupt_id"], rules.YES)


async def test_from_plan_to_a_mode_that_edits_the_agent_begins_again_with_the_last_answer(world):
    async def plan(turn: FakeTurn) -> str | None:
        turn.say("Plan: add an hours line.")
        return None

    live, place = sessions(world, scripted(plan, hours))
    made = await start(live, world, rows.PLAN)
    await turn_of(live, made, "How would you add the hours?")
    first = world.store.get_session(ME, made["id"])["place_session"]
    assert (await live.set_mode(ME, made["id"], rows.ASK))["mode"] == rows.ASK
    assert world.store.get_session(ME, made["id"])["place_session"] is None
    place.agent = hours
    closed = await turn_of(live, made, "Carry out this plan.")
    second = world.store.get_session(ME, made["id"])["place_session"]
    assert second and second != first and not place.sessions[second].spec.read_only
    sent = place.sent(second)[-1]
    assert "Plan: add an hours line." in sent and sent.endswith("Carry out this plan.")
    assert closed["changed"] == 4 and any("begins again" in n for n in closed["notes"])
    with pytest.raises(Refused):
        await live.set_mode(ME, made["id"], "everything")


# ---- undo ------------------------------------------------------------------------------------------


async def test_undo_puts_every_file_back_exactly_and_bring_it_back_returns_the_turn(world):
    live, place = sessions(world, hours)
    made = await start(live, world)
    was = listing(world.project)
    closed = await turn_of(live, made)
    after = listing(world.project)
    assert after != was

    undone = await live.undo(ME, made["id"], closed["id"])
    assert undone == {
        "turn_id": closed["id"],
        "undone": True,
        "files": 4,
        "own_changes": False,
        "notes": [],
    }
    assert listing(world.project) == was  # bytes and permissions, the deleted file, no new one
    assert os.access(world.project / "run.sh", os.X_OK) and not (world.project / "tests").exists()
    (shown,) = live.turns(ME, made["id"])
    assert shown["undone"] and shown["can_redo"] and not shown["can_undo"]
    (item,) = (await live.changes(ME, made["id"]))["items"]
    assert item["undone"] and item["can_redo"] and len(item["files"]) == 4  # still in the list

    back = await live.redo(ME, made["id"], closed["id"])
    assert back["undone"] is False and listing(world.project) == after
    (shown,) = live.turns(ME, made["id"])
    assert not shown["undone"] and shown["can_undo"] and not shown["can_redo"]
    # and it can be undone again
    await live.undo(ME, made["id"], closed["id"])
    assert listing(world.project) == was
    # the agent is told with the next message, because it cannot know
    await turn_of(live, made, "Try another way")
    assert place.sent(place.calls[0][1])[-1] == f"{UNDONE_NOTE}\n\nTry another way"


async def test_only_the_newest_turn_that_changed_files_is_undone_and_never_during_a_turn(world):
    async def one(turn: FakeTurn) -> str | None:
        await turn.edit("a.txt", "a\n")
        return None

    async def two(turn: FakeTurn) -> str | None:
        await turn.edit("b.txt", "b\n")
        return None

    async def asks(turn: FakeTurn) -> str | None:
        turn.say("Which colour?")
        return None

    waiting = asyncio.Event()

    async def slow(turn: FakeTurn) -> str | None:
        await waiting.wait()
        return None

    live, _ = sessions(world, scripted(one, two, asks, slow))
    made = await start(live, world)
    first = await turn_of(live, made, "one")
    second = await turn_of(live, made, "two")
    await turn_of(live, made, "a question")  # changed nothing: it is not in the way
    with pytest.raises(Refused) as no:
        await live.undo(ME, made["id"], first["id"])
    assert no.value.code == "not_last"
    await live.undo(ME, made["id"], second["id"])
    assert not (world.project / "b.txt").exists() and (world.project / "a.txt").exists()
    await live.undo(ME, made["id"], first["id"])  # now it is the newest that stands
    assert not (world.project / "a.txt").exists()
    # what comes back is the turn undone last: the first, then the second
    with pytest.raises(Refused):
        await live.redo(ME, made["id"], second["id"])
    await live.redo(ME, made["id"], first["id"])
    assert (world.project / "a.txt").exists() and not (world.project / "b.txt").exists()
    await live.redo(ME, made["id"], second["id"])
    assert (world.project / "b.txt").read_text() == "b\n"
    await live.undo(ME, made["id"], second["id"])
    await live.send(ME, made["id"], "slow")
    with pytest.raises(Refused) as busy:
        await live.redo(ME, made["id"], second["id"])
    assert busy.value.code == "busy"
    assert not any(t["can_undo"] or t["can_redo"] for t in live.turns(ME, made["id"]))
    waiting.set()
    await live.wait(ME, made["id"])


async def test_an_undone_turn_does_not_come_back_once_a_later_turn_changed_files(world):
    async def one(turn: FakeTurn) -> str | None:
        await turn.edit("a.txt", "a\n")
        return None

    async def two(turn: FakeTurn) -> str | None:
        await turn.edit("b.txt", "b\n")
        return None

    live, _ = sessions(world, scripted(one, two))
    made = await start(live, world)
    first = await turn_of(live, made, "one")
    await live.undo(ME, made["id"], first["id"])
    second = await turn_of(live, made, "two")
    shown = {t["id"]: t for t in live.turns(ME, made["id"])}
    assert shown[first["id"]]["undone"] and not shown[first["id"]]["can_redo"]
    assert shown[second["id"]]["can_undo"]
    with pytest.raises(Refused):
        await live.redo(ME, made["id"], first["id"])
    # once the later turn is undone too, the files are as that first undo left them
    await live.undo(ME, made["id"], second["id"])
    assert [t["can_redo"] for t in live.turns(ME, made["id"])] == [False, True]


async def test_what_the_person_changed_since_goes_back_too_and_the_answer_says_so(world):
    live, _ = sessions(world, hours)
    made = await start(live, world)
    closed = await turn_of(live, made)
    (world.project / "src" / "home.html").write_text("mine\n")
    (world.project / ".env").write_text("KEY=mine\n")
    undone = await live.undo(ME, made["id"], closed["id"])
    assert undone["own_changes"] is True
    assert (world.project / "src" / "home.html").read_text() == "<h1>Bakery</h1>\n<p>Welcome</p>\n"
    # an ignored file is never touched by undo
    assert (world.project / ".env").read_text() == "KEY=mine\n"
    # nothing is lost: bringing it back returns the person's own change as well
    await live.redo(ME, made["id"], closed["id"])
    assert (world.project / "src" / "home.html").read_text() == "mine\n"


async def test_undo_puts_the_persons_own_git_back_where_it_was(world):
    def git(*args: str) -> str:
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        return subprocess.run(
            ["git", "-c", "user.name=T", "-c", "user.email=t@example.test", *args],
            cwd=world.project, env=env, check=True, capture_output=True, text=True,
        ).stdout.strip()  # fmt: skip

    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "first")
    head = git("rev-parse", "HEAD")

    async def commits(turn: FakeTurn) -> str | None:
        await turn.edit("src/home.html", "changed\n", command="str_replace")
        git("add", "-A")
        git("commit", "-q", "-m", "the agent's")
        return None

    live, _ = sessions(world, commits)
    made = await start(live, world)
    closed = await turn_of(live, made)
    assert git("rev-parse", "HEAD") != head
    await live.undo(ME, made["id"], closed["id"])
    assert git("rev-parse", "HEAD") == head and git("status", "--porcelain") == ""


# ---- the rules ---------------------------------------------------------------------------------------


def test_which_steps_are_a_kind_of_request(tmp_path: Path):
    project = tmp_path / "p"
    project.mkdir()
    ignored = {".env", "build/out.js"}.__contains__

    def kind(**step) -> str | None:
        return rules.classify({"tool": "file_editor", **step}, project, ignored)

    assert kind(command="create", path=str(project / ".env")) == rules.NOT_UNDOABLE
    assert kind(command="str_replace", path=str(project / "build" / "out.js")) == rules.NOT_UNDOABLE
    assert (
        kind(command="insert", path=".env") == rules.NOT_UNDOABLE
    )  # a path from the project's top
    assert kind(command="create", path=str(project / "src" / "a.js")) is None
    assert kind(command="view", path=str(project / ".env")) is None  # looking is not a change
    assert (
        kind(command="create", path=str(tmp_path / "elsewhere" / ".env")) is None
    )  # the sandbox's
    assert kind(command="create", path=str(project / ".." / "p" / ".env")) == rules.NOT_UNDOABLE
    assert rules.classify({"tool": "grep", "pattern": ".env"}, project, ignored) is None


def test_the_engines_own_filler_is_not_shown_as_the_agents_reason():
    from wasifyai_code.runtime import _reason

    assert _reason({"tool": "file_editor", "summary": "Set the key so the hours load."}) == (
        "Set the key so the hours load."
    )
    assert _reason({"tool": "file_editor", "summary": 'file_editor: {"command": "create"}'}) == ""
    assert _reason({"tool": "file_editor"}) == ""


def test_what_is_decided_for_the_steps_that_wait_together():
    assert rules.decide("ask", [], [None, None]) == (rules.YES, "")
    assert rules.decide("ask", [], [None, "not_undoable"]) == ("ask", "not_undoable")
    assert rules.decide("ask", ["not_undoable"], ["not_undoable"]) == (
        rules.ALLOWED,
        "not_undoable",
    )
    assert rules.decide("ask", ["not_undoable"], ["not_undoable", "delete"]) == ("ask", "delete")
    assert rules.decide("own", [], ["not_undoable", "delete"]) == (rules.YES, "")


def test_a_file_in_a_git_folder_or_one_the_project_ignores_is_left_out(world):
    from wasifyai_code.checkpoints import CheckpointStore

    cps = CheckpointStore(world.data / "cps", world.project)
    assert cps.is_left_out(".env") and cps.is_left_out("build/x/y.js")
    assert cps.is_left_out(".git/config") and cps.is_left_out("sub/.git/HEAD")
    assert not cps.is_left_out("src/home.html") and not cps.is_left_out("new/file.txt")
    assert not cps.is_left_out("../outside") and not cps.is_left_out("/etc/hosts")
    made = cps.checkpoint("one")
    assert cps.file_at(made.id, "src/home.html") == b"<h1>Bakery</h1>\n<p>Welcome</p>\n"
    assert cps.file_at(made.id, ".env") is None and cps.file_at(made.id, "src") is None


def test_an_older_store_file_gets_the_new_columns(tmp_path: Path):
    import sqlite3

    folder = tmp_path / "code"
    folder.mkdir()
    db = sqlite3.connect(folder / "code.db")
    db.executescript(
        "CREATE TABLE workspaces(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, product_id TEXT NOT NULL, user_id TEXT NOT NULL,"
        " name TEXT NOT NULL DEFAULT '', path TEXT NOT NULL, check_command TEXT NOT NULL DEFAULT '', check_from TEXT NOT NULL DEFAULT '',"
        " check_limit_s INTEGER NOT NULL DEFAULT 600, last_pass TEXT, created_at TEXT NOT NULL);"
        "INSERT INTO workspaces(id, tenant_id, product_id, user_id, name, path, created_at) VALUES ('w1', 't1', 'wasifyai-code', 'u1', 'p', '/p', 'now');"
    )
    db.commit()
    db.close()
    store = CodeStore.in_folder(folder)
    try:
        assert store.get_workspace(ME, "w1")["allowed"] == []
        assert store.set_allowed(ME, "w1", ["delete", "delete"])["allowed"] == ["delete"]
    finally:
        store.close()
