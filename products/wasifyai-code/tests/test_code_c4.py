# ruff: noqa: E501, F811  (test data on one line; `world` is a fixture taken from another file)
"""Stage C4 on the pretended place: the preview of a project (a real program on a real port),
the first starter, and `wasify-make` (the question, the app's own action, the file in the
project and the note the command reads). Only the agent and the picture are pretended."""

import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_code_edits import card, sessions, start, turn_of, world  # noqa: F401
from test_code_sessions import ME
from wasifyai_code import assets, rules, starters
from wasifyai_code import preview as previews
from wasifyai_code import store as rows
from wasifyai_code.place import FakeTurn
from wasifyai_code.runtime import Refused

PY = sys.executable
SERVE = f"{PY} -m http.server $PORT --bind $HOST"
ENGINE_FILES = Path(__file__).resolve().parents[3] / "services" / "coding-engine"


async def stands_in(folder: Path):
    """Where the sandbox would be: `env` in front, and a clean environment."""
    return ["/usr/bin/env"], {"PATH": os.environ["PATH"], "HOME": str(folder)}


def with_previews(live) -> None:
    live.previews = previews.Previews(stands_in)


def pid_of(live, made) -> int:
    running = live.previews.get(made["id"])
    assert running is not None
    return running.pid


async def until(preview_of, state: str, wait_s: float = 20) -> dict:
    for _ in range(int(wait_s / 0.05)):
        seen = preview_of()
        if seen["running"] and seen["running"]["state"] == state:
            return seen["running"]
        await asyncio.sleep(0.05)
    raise AssertionError(f"the preview never was {state}: {preview_of()}")


# ---- the preview -------------------------------------------------------------------------------------


async def test_a_preview_is_started_found_by_its_port_and_stopped_with_what_it_started(world):
    live, _ = sessions(world, None)
    with_previews(live)
    made = await start(live, world)
    (world.project / "index.html").write_text("<h1>Bakery</h1>")
    seen = live.preview(ME, made["id"])
    assert seen["command"] == "" and seen["running"] is None
    # nothing is set: the project's files suggest a command, and nothing runs
    assert seen["suggested"][0]["command"].startswith("python3 -m http.server")
    with pytest.raises(Refused) as no:
        await live.start_preview(ME, made["id"])
    assert no.value.code == "no_command"
    began = await live.start_preview(ME, made["id"], SERVE)
    assert began["command"] == SERVE and began["running"]["state"] in ("starting", "running")
    running = await until(lambda: live.preview(ME, made["id"]), "running")
    assert running["port"] and running["url"] == f"http://localhost:{running['port']}/"
    assert running["open_to_network"] is False and running["listens_nowhere"] is False
    page = await asyncio.to_thread(
        lambda: urllib.request.urlopen(f"http://127.0.0.1:{running['port']}/", timeout=5).read()
    )
    assert b"<h1>Bakery</h1>" in page
    assert live.view(ME, made["id"])["previewing"] is True
    pid = pid_of(live, made)
    stopped = await live.stop_preview(ME, made["id"])
    assert stopped["running"] is None and live.view(ME, made["id"])["previewing"] is False
    await asyncio.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    with pytest.raises(OSError):
        await asyncio.to_thread(
            lambda: urllib.request.urlopen(f"http://127.0.0.1:{running['port']}/", timeout=1)
        )


async def test_a_preview_that_listens_on_every_address_says_so(world):
    live, _ = sessions(world, None)
    with_previews(live)
    made = await start(live, world)
    await live.start_preview(ME, made["id"], f"{PY} -m http.server $PORT --bind 0.0.0.0")
    running = await until(lambda: live.preview(ME, made["id"]), "running")
    assert running["open_to_network"] is True
    await live.stop_preview(ME, made["id"])


async def test_a_command_that_ends_says_why_and_a_new_start_replaces_the_old(world):
    live, _ = sessions(world, None)
    with_previews(live)
    made = await start(live, world)
    await live.start_preview(ME, made["id"], "echo 'no such script'; exit 3")
    ended = await until(lambda: live.preview(ME, made["id"]), "ended")
    assert ended["exit_code"] == 3 and "no such script" in ended["output"] and not ended["stopped"]
    await live.start_preview(ME, made["id"], SERVE)
    first = pid_of(live, made)
    await until(lambda: live.preview(ME, made["id"]), "running")
    await live.start_preview(ME, made["id"])  # again, with the command that is kept
    assert pid_of(live, made) != first
    await asyncio.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(first, 0)
    await live.delete(ME, made["id"])  # deleting the session ends its preview
    assert live.previews.running() == []


async def test_no_preview_without_a_sandbox(world, tmp_path):
    live, _ = sessions(world, None)
    made = await start(live, world)
    with pytest.raises(Refused) as no:  # the pretended place has no sandbox
        await live.start_preview(ME, made["id"], "true")
    assert no.value.code == "no_sandbox"

    async def nothing(folder: Path):
        return [], {}

    with pytest.raises(previews.PreviewError):
        await previews.Previews(nothing).start("s", tmp_path, "true")


def test_what_listens_is_read_from_the_systems_own_list():
    said = """COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
node    71001 me   17u  IPv4 0x1      0t0  TCP 127.0.0.1:5173 (LISTEN)
node    71001 me   18u  IPv6 0x2      0t0  TCP [::1]:5173 (LISTEN)
node    71002 me   19u  IPv4 0x3      0t0  TCP *:24678 (LISTEN)
"""
    found = previews.read_listening(said)
    assert found == [("127.0.0.1", 5173), ("[::1]", 5173), ("*", 24678)]
    assert previews.choose(found, 5173) == (
        5173,
        False,
    )  # the port we asked for, kept to this computer
    assert previews.choose(found, 9999) == (5173, False)  # another one: the lowest it listens on
    assert previews.choose([("*", 3000)], 3000) == (3000, True)
    assert previews.choose([], 3000) is None


def test_which_command_starts_a_project(tmp_path: Path):
    def of(files: dict[str, str]) -> list[str]:
        folder = tmp_path / str(len(list(tmp_path.iterdir())))
        folder.mkdir()
        for name, text in files.items():
            (folder / name).write_text(text)
        return [s["command"] for s in previews.suggest(folder)]

    assert of({}) == []
    assert of({"package.json": '{"scripts": {"dev": "vite", "start": "node .", "test": "x"}}'}) == [
        "npm run dev",
        "npm start",
    ]
    assert of({"package.json": '{"scripts": {"dev": "vite"}}', "pnpm-lock.yaml": ""}) == [
        "pnpm run dev"
    ]
    assert of({"package.json": "broken", "index.html": ""}) == [
        "python3 -m http.server $PORT --bind 127.0.0.1"
    ]
    assert of({"manage.py": ""}) == ["python3 manage.py runserver $PORT"]


# ---- the starter -------------------------------------------------------------------------------------


async def test_a_new_project_is_made_from_the_starter_with_its_check_and_preview_set(world):
    live, _ = sessions(world, None)
    parent = world.project.parent
    assert [s["id"] for s in starters.list_starters()] == ["web"]
    made = await live.start_new(ME, parent=str(parent), name="Tax Shop")
    folder = parent / "Tax Shop"
    assert made["folder"] == str(folder.resolve()) and made["mode"] == "ask"
    assert made["check_command"] == "npm test" and made["preview_command"] == "npm run dev"
    names = sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())
    assert names == [
        ".gitignore",
        "README.md",
        "dev-server.mjs",
        "index.html",
        "package.json",
        "src/app.js",
        "src/logic.js",
        "src/style.css",
        "tests/logic.test.js",
    ]
    assert json.loads((folder / "package.json").read_text())["name"] == "tax-shop"
    assert "<h1>Tax Shop</h1>" in (folder / "index.html").read_text()
    assert "{{" not in "".join(p.read_text() for p in folder.rglob("*") if p.is_file())
    # the same name again, and names that are not names, are refused; nothing is written
    for name, code in (
        ("Tax Shop", "not_empty"),
        ("../up", "bad_name"),
        (".hidden", "bad_name"),
        ("a/b", "bad_name"),
    ):
        with pytest.raises(Refused) as no:
            await live.start_new(ME, parent=str(parent), name=name)
        assert no.value.code == code, name
    with pytest.raises(Refused):
        await live.start_new(ME, parent=str(parent), name="Other", starter="none")
    with pytest.raises(Refused):
        await live.start_new(ME, parent=str(world.data), name="Inside the app")
    assert not (parent / "Other").exists() and not (world.data / "Inside the app").exists()


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="needs Node on this computer")
async def test_the_starter_passes_its_own_check_and_serves_its_page(tmp_path):
    folder = starters.make("web", tmp_path, "bakery")
    done = await asyncio.to_thread(
        lambda: subprocess.run(
            ["node", "--test"], cwd=folder, capture_output=True, text=True, timeout=60
        )
    )
    assert done.returncode == 0, done.stdout + done.stderr
    shown = previews.Previews(stands_in)
    p = await shown.start("s", folder, "npm run dev")
    try:
        for _ in range(400):
            if p.state != previews.STARTING:
                break
            await asyncio.sleep(0.05)
        assert p.state == previews.RUNNING and p.port == p.wanted and not p.open_to_network, (
            p.view()
        )
        page = await asyncio.to_thread(
            lambda: urllib.request.urlopen(f"http://127.0.0.1:{p.port}/", timeout=5).read().decode()
        )
        assert "<h1>bakery</h1>" in page and "/__changes" in page
        outside = await asyncio.to_thread(
            lambda: urllib.request.urlopen(
                f"http://127.0.0.1:{p.port}/src/logic.js", timeout=5
            ).read()
        )
        assert b"export function greeting" in outside
        with pytest.raises(OSError):  # nothing above the project is served
            await asyncio.to_thread(
                lambda: urllib.request.urlopen(
                    f"http://127.0.0.1:{p.port}/..%2f..%2fetc/hosts", timeout=5
                )
            )
    finally:
        await shown.close_all()


# ---- wasify-make ---------------------------------------------------------------------------------------


def test_a_call_of_wasify_make_is_read_or_refused_in_words():
    ask = assets.parse('wasify-make picture "a round logo of a loaf" assets/logo.png --size wide')
    assert (ask.kind, ask.text, ask.path, ask.size) == (
        "picture",
        "a round logo of a loaf",
        "assets/logo.png",
        "wide",
    )
    assert assets.parse("wasify-make speech 'Welcome.' hello.wav").kind == "speech"
    # what a real model wrote: it went into the project first, and made the folder
    led = assets.parse(
        'cd /p/shop && mkdir -p assets && wasify-make picture "a logo; flat" assets/logo.png'
    )
    assert (led.cwd, led.text, led.path) == ("/p/shop", "a logo; flat", "assets/logo.png")
    assert led.key == assets.parse('wasify-make picture "a logo; flat" assets/logo.png').key
    for bad in (
        "wasify-make picture logo.png",
        "wasify-make picture 'x' logo.jpg",
        "wasify-make speech 'x' a.png",
        "wasify-make picture 'x' a.png --size huge",
        "wasify-make picture 'x' a.png && rm a.png",
        "echo hi",
        "wasify-make picture 'unclosed a.png",
        "wasify-make film 'x' a.png",
        "wasify-make picture 'x' a.png --fast",
    ):
        with pytest.raises(assets.AssetError):
            assets.parse(bad)
    assert rules.command_kind("wasify-make picture 'x' a.png") == rules.MAKE
    assert rules.command_kind("mkdir assets && wasify-make picture 'x' assets/a.png") == rules.MAKE
    # asked in every mode, also in "Work on its own", until it is allowed for the project
    assert rules.decide("own", [], [rules.MAKE]) == ("ask", rules.MAKE)
    assert rules.decide("own", [rules.MAKE], [rules.MAKE]) == (rules.ALLOWED, rules.MAKE)
    assert rules.decide("own", [], [rules.DELETE, rules.INSTALL]) == (rules.YES, "")


class Actions:
    """Stands for the app's action executor: it "makes" a picture and says who asked."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail = False

    async def run_action(self, action_id, params, origin, *, actor, person_approved=False):
        self.calls.append((action_id, dict(params), origin, actor.user_id, person_approved))
        if self.fail:
            return SimpleNamespace(
                status="needs_setup", output={}, text="No picture model is set up."
            )
        return SimpleNamespace(status="ok", output={"image_id": "img-1"}, text="")


def note_of(world, command: str) -> dict:
    key = assets.parse(command).key
    return json.loads((world.data / "coding-fixed" / "made" / f"{key}.json").read_text())


def read_by_the_command(world, command: str) -> tuple[int, str]:
    """Run the real `wasify-make` the way the sandbox would find it: beside the notes."""
    tool = world.data / "coding-fixed" / "bin" / "wasify-make"
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text((ENGINE_FILES / "wasify-make").read_text())
    import shlex

    done = subprocess.run(
        [PY, str(tool), *shlex.split(command)[1:]], capture_output=True, text=True, timeout=30
    )
    return done.returncode, done.stdout.strip()


def makes(command: str, said: list[bool]):
    async def agent(turn: FakeTurn) -> None:
        turn.step("terminal", id="c1", command=command)
        said.append(await turn.confirm(command, tool="terminal", command=command))
        turn.say("Done.")

    return agent


async def test_a_picture_is_asked_first_made_by_the_app_and_put_into_the_project(
    world, monkeypatch
):
    command = 'wasify-make picture "a round logo of a loaf" assets/logo.png'
    said: list[bool] = []
    live, _ = sessions(world, makes(command, said))
    world.state.actions = actions = Actions()
    world.state.storage = world.state.engine = object()

    async def picture(state, identity, ask):
        done = await state.actions.run_action(
            "image.generate",
            {"prompt": ask.text, "size": ask.size},
            "window",
            actor=identity,
            person_approved=True,
        )
        if done.status != "ok":
            raise assets.AssetError(done.text)
        return b"\x89PNG-pretended", "1024 by 1024"

    monkeypatch.setattr(assets, "_picture", picture)
    made = await start(live, world, mode=rows.OWN)  # even in "Work on its own" it is asked
    await live.send(ME, made["id"], "Give the site a logo")
    asked = await card(live, made)
    assert asked["payload"]["ask"] == "make" and asked["payload"]["command"] == command
    assert (
        actions.calls == [] and not (world.project / "assets").exists()
    )  # nothing before the answer
    await live.answer(ME, made["id"], asked["interrupt_id"], rules.YES)
    await live.wait(ME, made["id"])
    assert said == [True]
    assert actions.calls == [
        (
            "image.generate",
            {"prompt": "a round logo of a loaf", "size": "square"},
            "window",
            ME.user_id,
            True,
        )
    ]
    assert (world.project / "assets" / "logo.png").read_bytes() == b"\x89PNG-pretended"
    assert note_of(world, command) == {
        "ok": True,
        "message": "Made assets/logo.png (1024 by 1024). It is also in the person's library.",
    }
    assert read_by_the_command(world, command) == (
        0,
        "Made assets/logo.png (1024 by 1024). It is also in the person's library.",
    )
    # a no makes nothing, and the command says so
    other = 'wasify-make picture "a banner" assets/banner.png'
    live2, _ = sessions(world, makes(other, said))
    again = await start(live2, world, mode=rows.ASK)
    await live2.send(ME, again["id"], "And a banner")
    asked = await card(live2, again)
    await live2.answer(ME, again["id"], asked["interrupt_id"], rules.NO)
    await live2.wait(ME, again["id"])
    assert len(actions.calls) == 1 and not (world.project / "assets" / "banner.png").exists()
    code, words = read_by_the_command(world, other)
    assert code == 1 and "Nothing was made" in words
    # the app could not make it: said to the agent, never thrown at the turn
    actions.fail = True
    third = 'wasify-make picture "a cake" assets/cake.png'
    live3, _ = sessions(world, makes(third, said))
    last = await start(live3, world, mode=rows.ASK)
    await live3.send(ME, last["id"], "And a cake")
    asked = await card(live3, last)
    await live3.answer(ME, last["id"], asked["interrupt_id"], rules.ALLOW)
    closed = await live3.wait(ME, last["id"])
    assert closed["why"] == "finished" and not (world.project / "assets" / "cake.png").exists()
    assert read_by_the_command(world, third) == (1, "Nothing was made: No picture model is set up.")
    assert "make" in [k["id"] for k in live3.project(ME, last["id"])["kinds"] if k["allowed"]]


async def test_a_picture_is_never_written_outside_the_project(world, tmp_path):
    notes = tmp_path / "notes"
    world.state.actions, world.state.storage = Actions(), object()
    for command in (
        'wasify-make picture "x" ../outside.png',
        'wasify-make picture "x" /tmp/claude-outside.png',
    ):
        said = await assets.make(world.state, ME, world.project, notes, command)
        assert said == "Nothing was made: The file must be inside this project."
    assert world.state.actions.calls == [] and not (world.project.parent / "outside.png").exists()
    said = await assets.make(
        world.state, ME, world.project, notes, 'cd /etc && wasify-make picture "x" a.png'
    )
    assert said == "Nothing was made: The file must be inside this project."
    # a command that cannot be read leaves a note too, and raises nothing
    assert "Nothing was made" in await assets.make(
        world.state, ME, world.project, notes, "wasify-make picture"
    )
