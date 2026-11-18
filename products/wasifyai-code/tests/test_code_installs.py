"""Installs for a session on the person's own program (ADR-0107, stage H4; the owner's choice A):
the program tries to install, the window offers to install what the project lists, Wasify AI runs it
in its own sandbox (`who="person"`), and the program is told and carries on."""

import asyncio
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_code_harness import Accounts
from test_code_sessions import Gateway, Index
from wasifyai_code import installs
from wasifyai_code.place import FakePlace, FakeTurn, scripted
from wasifyai_code.runtime import Refused, Sessions
from wasifyai_code.store import CodeStore, Owner

ME = Owner("t1", "u1")


def tool(folder: Path, name: str, body: str) -> None:
    """A pretended command on the sandbox's PATH."""
    folder.mkdir(parents=True, exist_ok=True)
    made = folder / name
    made.write_text(f"#!/bin/sh\n{body}\n")
    made.chmod(made.stat().st_mode | stat.S_IEXEC)


class Place(FakePlace):
    """The pretended place, with a sandbox of our own: a command put in front of what is run, so
    a test can see it was used and by whom."""

    def __init__(self, agent, bin_dir: Path):
        super().__init__(agent)
        self.bin_dir = bin_dir
        self.sandboxes: list[tuple[Path, str]] = []

    async def harness_models(self, harness: str) -> dict:
        return {"models": [{"id": "opus", "name": "Opus"}], "current": "default", "error": ""}

    async def sandbox(self, folder, *, who: str = "agent"):
        self.sandboxes.append((Path(folder), who))
        env = {"PATH": f"{self.bin_dir}{os.pathsep}/usr/bin:/bin", "HOME": str(folder)}
        return ["/usr/bin/env"], env


async def tries_to_install(turn: FakeTurn) -> None:
    turn.write("package.json", '{"dependencies": {"flatpickr": "^4"}}\n')
    turn.step("terminal", command="npm install flatpickr")
    turn.say("I could not fetch flatpickr: the network is closed.")


async def carries_on(turn: FakeTurn) -> None:
    turn.say("Now it is imported.")


@pytest.fixture
def world(tmp_path: Path):
    data = tmp_path / "appdata"
    project = tmp_path / "shop"
    project.mkdir()
    store = CodeStore.in_folder(data / "code")
    bin_dir = tmp_path / "bin"
    tool(bin_dir, "npm", 'echo "added 1 package"; echo "$@" > installed.txt')
    place = Place(scripted(tries_to_install, carries_on), bin_dir)
    state = SimpleNamespace(
        code_store=store, code_sessions=None,
        coding_server=SimpleNamespace(harness_ids=("claude-code", "codex")),
        coding_gateway=Gateway(), coding_harnesses=Accounts(), creation_index=Index(),
        desktop_dir=data,
    )  # fmt: skip
    made = Sessions(state, place=place)
    yield SimpleNamespace(store=store, project=project, sessions=made, place=place)
    store.close()


# ---- what is installed ---------------------------------------------------------------------------


def test_the_project_says_what_is_installed(tmp_path):
    assert installs.what_installs(tmp_path) is None
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "package-lock.json").write_text("{}")
    node = installs.what_installs(tmp_path)
    assert node is not None
    assert node.view() == {"command": "npm install", "from": "package.json and package-lock.json"}
    assert node.steps == (("npm", "install", "--no-fund", "--no-audit"),)

    (tmp_path / "requirements.txt").write_text("requests\n")
    both = installs.what_installs(tmp_path)
    assert both is not None
    assert both.shown == "npm install && pip install -r requirements.txt (into .venv)"
    assert both.source == "package.json, package-lock.json and requirements.txt"
    assert both.steps[1] == ("python3", "-m", "venv", ".venv")  # made first, when it is not there

    py = tmp_path / "py"
    py.mkdir()
    (py / "pyproject.toml").write_text("[project]\nname='x'\n")
    (py / ".venv" / "bin").mkdir(parents=True)
    (py / ".venv" / "bin" / "python").write_text("")
    only = installs.what_installs(py)
    assert only is not None and len(only.steps) == 1 and only.steps[0][-2:] == ("-e", ".")


async def test_an_install_runs_in_the_sandbox_and_says_how_it_went(tmp_path):
    bin_dir = tmp_path / "bin"
    tool(bin_dir, "npm", 'echo "added 1 package"; echo "$@" > installed.txt')
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "package.json").write_text("{}")
    seen = []

    async def sandbox(f):
        seen.append(f)
        return ["/usr/bin/env"], {"PATH": f"{bin_dir}:/usr/bin:/bin"}

    found = installs.what_installs(folder)
    assert found is not None
    done = await installs.run(sandbox, folder, found)
    assert done["ok"] is True and "added 1 package" in done["output"] and done["why"] == ""
    assert (folder / "installed.txt").read_text().strip() == "install --no-fund --no-audit"
    assert seen == [folder]

    tool(bin_dir, "npm", 'echo "npm ERR! 404 Not Found"; exit 1')
    failed = await installs.run(sandbox, folder, found)
    assert (failed["ok"], failed["exit_code"], failed["why"]) == (False, 1, "It ended with code 1.")
    assert "404" in failed["output"]

    tool(bin_dir, "npm", "sleep 30")
    slow = await installs.run(sandbox, folder, found, limit_s=0.5)
    assert slow["ok"] is False and "longer than" in slow["why"]

    async def none(f):
        return [], {}

    assert (await installs.run(none, folder, found))["ok"] is False  # never outside a sandbox


# ---- in a session ------------------------------------------------------------------------------


async def test_a_program_that_tries_to_install_is_offered_the_projects_own_install(world):
    s = world.sessions
    made = await s.start(ME, folder=str(world.project), model="claude-code:opus", mode="own")
    await s.send(ME, made["id"], "Add a date picker")
    await s.wait(ME, made["id"])
    card = s.view(ME, made["id"])["install"]
    assert card == {"state": "offered", "harness": "claude-code", "tried": "npm install flatpickr",
                    "changed": "", "command": "npm install", "from": "package.json"}  # fmt: skip
    said = [e for e in s.feed(made["id"]).kept if e["event"] == "code_install"]
    assert said and said[-1]["state"] == "offered"

    after = await s.install(ME, made["id"])
    assert after["install"]["state"] == "installing"
    await s.installed(made["id"])
    card = s.view(ME, made["id"])["install"]
    assert card["state"] == "installed" and "added 1 package" in card["output"]
    # in our own sandbox, for the person, and in the project
    folder, who = world.place.sandboxes[-1]
    assert (folder.resolve(), who) == (world.project.resolve(), "person")
    assert (world.project / "installed.txt").is_file()

    # the program is told, and carries on
    for _ in range(100):
        if len(s.store.list_turns(ME, made["id"])) == 2:
            break
        await asyncio.sleep(0.02)
    await s.wait(ME, made["id"])
    turns = s.store.list_turns(ME, made["id"])
    assert len(turns) == 2
    assert turns[1]["request"].startswith(
        "I installed the project's packages for you: `npm install`"
    )
    assert "Claude Code cannot reach a package index" in turns[1]["request"]
    assert turns[1]["answer"] == "Now it is imported."


async def test_not_now_closes_the_card_and_the_next_try_brings_it_back(world):
    s = world.sessions
    made = await s.start(ME, folder=str(world.project), model="codex:default", mode="own")
    await s.send(ME, made["id"], "Add a date picker")
    await s.wait(ME, made["id"])
    assert s.not_now(ME, made["id"])["install"] is None
    assert world.place.sandboxes == []  # nothing ran
    world.place.agent = tries_to_install
    await s.send(ME, made["id"], "Try again")
    await s.wait(ME, made["id"])
    assert s.view(ME, made["id"])["install"]["state"] == "offered"


async def test_wasify_ais_own_agent_gets_no_card_and_cannot_ask_for_one(world):
    s = world.sessions
    made = await s.start(ME, folder=str(world.project), model="sonnet", mode="own")
    world.place.agent = tries_to_install
    await s.send(ME, made["id"], "Add a date picker")
    await s.wait(ME, made["id"])
    assert s.view(ME, made["id"])["install"] is None
    with pytest.raises(Refused) as raised:
        await s.install(ME, made["id"])
    assert raised.value.code == "not_on_harness"


async def test_a_project_that_lists_nothing_is_not_offered_an_install(world):
    s = world.sessions

    async def bare(turn: FakeTurn) -> None:
        turn.step("terminal", command="pip install requests")

    world.place.agent = bare
    made = await s.start(ME, folder=str(world.project), model="claude-code:opus", mode="own")
    await s.send(ME, made["id"], "Fetch a page")
    await s.wait(ME, made["id"])
    assert s.view(ME, made["id"])["install"] is None
    with pytest.raises(Refused) as raised:
        await s.install(ME, made["id"])
    assert raised.value.code == "nothing_to_install"


async def test_an_install_while_the_program_works_is_told_once_its_turn_is_over(world):
    s = world.sessions
    go_on = asyncio.Event()

    async def waits(turn: FakeTurn) -> None:
        await tries_to_install(turn)
        await go_on.wait()

    world.place.agent = scripted(waits, carries_on)
    made = await s.start(ME, folder=str(world.project), model="claude-code:opus", mode="own")
    await s.send(ME, made["id"], "Add a date picker")
    for _ in range(100):
        if s.view(ME, made["id"])["install"]:
            break
        await asyncio.sleep(0.02)
    await s.install(ME, made["id"])
    await s.installed(made["id"])
    assert len(s.store.list_turns(ME, made["id"])) == 1  # not while it works
    go_on.set()
    await s.wait(ME, made["id"])
    for _ in range(100):
        if len(s.store.list_turns(ME, made["id"])) == 2:
            break
        await asyncio.sleep(0.02)
    await s.wait(ME, made["id"])
    turns = s.store.list_turns(ME, made["id"])
    assert len(turns) == 2 and turns[1]["request"].startswith("I installed")


async def test_a_failed_install_is_said_to_the_person_and_to_the_program(world):
    tool(world.place.bin_dir, "npm", 'echo "npm ERR! 404 flatpickr"; exit 1')
    s = world.sessions
    made = await s.start(ME, folder=str(world.project), model="claude-code:opus", mode="own")
    await s.send(ME, made["id"], "Add a date picker")
    await s.wait(ME, made["id"])
    await s.install(ME, made["id"])
    await s.installed(made["id"])
    card = s.view(ME, made["id"])["install"]
    assert card["state"] == "failed" and card["why"] == "It ended with code 1."
    for _ in range(100):
        if len(s.store.list_turns(ME, made["id"])) == 2:
            break
        await asyncio.sleep(0.02)
    await s.wait(ME, made["id"])
    told = s.store.list_turns(ME, made["id"])[1]["request"]
    assert "did not work" in told and "npm ERR! 404 flatpickr" in told


# ---- a command known only when it ends (Claude Code, seen in the real window 2026-11-16) ---------


def test_a_command_said_first_as_terminal_is_known_when_it_ends():
    from wasifyai_code import place as places
    from wasifyai_code.events import Reader

    reader = Reader()
    call = {"kind": "ACPToolCallEvent", "tool_call_id": "toolu_1", "tool_kind": "execute"}
    first = reader.read({**call, "title": "Terminal", "status": "pending", "raw_input": {}})
    assert first == [
        (places.STEP, {"tool": "terminal", "command": "Terminal", "summary": "Terminal",
                       "id": "toolu_1"})
    ]  # fmt: skip
    ran = "npm install --save-exact is-number@7.0.0 2>&1"
    last = reader.read(
        {**call, "title": ran, "status": "failed", "raw_input": {"command": ran}, "content": []}
    )
    assert len(last) == 1 and last[0][0] == places.RESULT
    assert last[0][1]["ok"] is False
    assert last[0][1]["given"] == {"command": ran, "summary": ran}
    # said once: an update that brings nothing new gives nothing new
    again = Reader()
    again.read({**call, "title": ran, "status": "pending", "raw_input": {"command": ran}})
    done = again.read({**call, "title": ran, "status": "completed", "raw_input": {"command": ran}})
    assert "given" not in done[0][1]


async def test_the_card_is_offered_for_a_command_known_only_when_it_ended(world):
    from wasifyai_code import place as places

    async def like_claude_code(turn: FakeTurn) -> None:
        turn.step("terminal", id="c1", command="Terminal")
        turn._place._emit(
            turn._session, places.RESULT,
            {"id": "c1", "tool": "terminal", "ok": False, "text": "",
             "given": {"command": "npm install --save-exact is-number@7.0.0"}},
        )  # fmt: skip

    world.place.agent = like_claude_code
    (world.project / "package.json").write_text("{}")
    s = world.sessions
    made = await s.start(ME, folder=str(world.project), model="claude-code:opus", mode="own")
    await s.send(ME, made["id"], "Add is-number")
    await s.wait(ME, made["id"])
    card = s.view(ME, made["id"])["install"]
    assert card is not None and card["tried"] == "npm install --save-exact is-number@7.0.0"
    result = [e for e in s.feed(made["id"]).kept if e["event"] == "tool_result"][-1]
    assert result["arguments"] == {"command": "npm install --save-exact is-number@7.0.0"}


async def test_once_packages_were_needed_a_change_to_the_list_offers_the_install_again(world):
    """Told to add a package to package.json, Claude Code added it and did not try to install
    again (the real window, 2026-11-16). The change to the list brings the card back."""

    async def lists_it(turn: FakeTurn) -> None:
        turn.write("package.json", '{"dependencies": {"is-number": "7.0.0"}}\n')
        turn.say("Added is-number to package.json.")

    async def tidies(turn: FakeTurn) -> None:
        turn.write("package.json", '{"name": "shop"}\n')

    s = world.sessions
    made = await s.start(ME, folder=str(world.project), model="claude-code:opus", mode="own")
    # a change to the list before any install was needed offers nothing
    # the place counts turns: the agent for each one, in order
    world.place.agent = scripted(tidies, tries_to_install, lists_it)
    await s.send(ME, made["id"], "Name the project")
    await s.wait(ME, made["id"])
    assert s.view(ME, made["id"])["install"] is None

    await s.send(ME, made["id"], "Add a date picker")
    await s.wait(ME, made["id"])
    await s.install(ME, made["id"])
    await s.installed(made["id"])
    for _ in range(100):
        if len(s.store.list_turns(ME, made["id"])) == 3:
            break
        await asyncio.sleep(0.02)
    await s.wait(ME, made["id"])
    told = s.store.list_turns(ME, made["id"])[2]["request"]
    assert "Do not run an install yourself" in told
    card = s.view(ME, made["id"])["install"]
    assert card["state"] == "offered" and card["changed"] == "package.json" and card["tried"] == ""
