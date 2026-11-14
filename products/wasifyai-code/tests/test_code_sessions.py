# ruff: noqa: E501  (test data is easier to read on one line)
"""The coding sessions in flight (`runtime.py`), on the pretended place: starting, a turn, the
relay inside the engine, Stop in every state, and what search is given. The same against the fake
Agent Server is `services/api/tests/test_coding_sessions.py`."""

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from wasifyai_code import place as places
from wasifyai_code import store as rows
from wasifyai_code.index import CodeIndexSource
from wasifyai_code.place import FakePlace, FakeTurn, PlaceError, scripted
from wasifyai_code.runtime import (
    KIND,
    NotAvailable,
    Refused,
    Sessions,
    check_folder,
    sessions_for,
    store_for,
    words_of,
)
from wasifyai_code.store import CodeStore, Owner

ME = Owner("t1", "u1")


class Gateway:
    """What the runtime asks of the engine's model gateway."""

    def __init__(self):
        self.not_ready: dict[str, str] = {}

    def model(self, model_id):
        if model_id not in (None, "sonnet", "local"):
            raise SimpleNamespaceError("That model is not one a coding session can use.")
        return SimpleNamespace(id=model_id or "sonnet")

    async def ready(self, model_id):
        return self.not_ready.get(model_id)

    def spent(self, session_id):
        return {"usd": 0.25}

    async def list_models(self):
        return [{"id": "sonnet", "ready": True}]


class SimpleNamespaceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class Index:
    def __init__(self):
        self.items: dict[str, tuple] = {}

    async def index(self, tenant, product, user, kind, item, text):
        self.items[item] = (tenant, product, user, kind, text)


@pytest.fixture
def world(tmp_path: Path):
    data = tmp_path / "appdata"
    project = tmp_path / "bakery-site"
    project.mkdir()
    (project / "index.html").write_text("<h1>Bakery</h1>")
    store = CodeStore.in_folder(data / "code")
    state = SimpleNamespace(
        code_store=store, code_sessions=None, coding_server=object(), coding_gateway=Gateway(),
        creation_index=Index(), desktop_dir=data,
    )  # fmt: skip
    yield SimpleNamespace(state=state, store=store, project=project, data=data, tmp=tmp_path)
    store.close()


def sessions(world, agent=None) -> tuple[Sessions, FakePlace]:
    place = FakePlace(agent)
    made = Sessions(world.state, place=place)
    world.state.code_sessions = made
    return made, place


async def answer(turn: FakeTurn) -> str | None:
    turn.step("glob", pattern="**/*")
    turn.piece("It is ")
    turn.piece("a bakery.")
    turn.say("It is a bakery.")
    return None


# ---- starting ----------------------------------------------------------------------------------


async def test_a_folder_becomes_a_workspace_once_and_each_start_is_a_new_session(world):
    live, place = sessions(world)
    first = await live.start(ME, folder=str(world.project))
    second = await live.start(ME, folder=str(world.project) + "/", title="Second look")
    assert first["id"] != second["id"] and first["folder"] == second["folder"]
    assert len(world.store.list_workspaces(ME)) == 1
    assert first["title"] == "bakery-site" and second["title"] == "Second look"
    assert first["mode"] == rows.PLAN and first["state"] == "new" and first["model"] == "sonnet"
    assert place.calls == []  # nothing is started at the place until something is asked


async def test_a_model_that_is_not_ready_or_not_known_is_refused_in_words(world):
    live, _ = sessions(world)
    world.state.coding_gateway.not_ready["sonnet"] = "No key is saved for Claude Sonnet 5.5."
    with pytest.raises(Refused, match="No key is saved") as e:
        await live.start(ME, folder=str(world.project))
    assert e.value.code == "model_not_ready"
    with pytest.raises(Refused) as e:
        await live.start(ME, folder=str(world.project), model="gpt-something")
    assert e.value.code == "no_such_model"
    assert (await live.start(ME, folder=str(world.project), model="local"))["model"] == "local"


def test_folders_that_hold_what_the_sandbox_keeps_out_are_refused(world, tmp_path):
    home = tmp_path / "home"
    for made in ("Projects/site", "Library/Application Support/x", ".ssh", ".config/tool"):
        (home / made).mkdir(parents=True)
    data = home / "Library" / "Application Support" / "ai.wasifyai.desktop"
    data.mkdir()
    disk = tmp_path / "other-disk" / "work"
    disk.mkdir(parents=True)

    def code(folder) -> str:
        with pytest.raises(Refused) as e:
            check_folder(str(folder), data_dir=data, home=home)
        return e.value.code

    assert check_folder(str(home / "Projects/site"), data_dir=data, home=home).name == "site"
    assert check_folder(str(disk), data_dir=data, home=home) == disk.resolve()  # outside the home
    assert code("") == "bad_folder" and code("Projects/site") == "bad_folder"
    assert code(home / "Projects/nothing") == "no_folder"
    assert code(home) == "too_wide" and code(tmp_path) == "too_wide" and code("/") == "too_wide"
    assert code(home / "Library") == "private_folder"
    assert code(data) == "private_folder" and code(data.parent) == "private_folder"
    assert (
        code(home / ".ssh") == "private_folder" and code(home / ".config/tool") == "private_folder"
    )
    # a link to a closed folder is that folder
    (home / "Projects" / "sneaky").symlink_to(home / ".ssh")
    assert code(home / "Projects" / "sneaky") == "private_folder"


# ---- a turn ----------------------------------------------------------------------------------------


async def test_a_turn_reads_and_is_closed_with_its_answer_and_no_new_word(world):
    live, place = sessions(world, answer)
    made = await live.start(ME, folder=str(world.project))
    turn = await live.send(ME, made["id"], "  What is this?  ")
    assert turn["request"] == "What is this?" and live.running(made["id"])
    closed = await live.wait(ME, made["id"])
    assert closed["state"] == rows.DONE and closed["why"] == places.FINISHED
    assert closed["answer"] == "It is a bakery." and closed["steps"] == 1
    assert closed["result"] == ""  # nothing was changed, so nothing was checked: no word
    seen = live.view(ME, made["id"])
    assert seen["state"] == "done" and not seen["working"] and seen["answer"] == "It is a bakery."
    assert seen["turns"] == 1 and seen["result"] == "" and seen["ended"] == places.FINISHED
    # the place was given a session that only reads, in this person's name
    (_, _, spec) = place.calls[0]
    assert spec.read_only and spec.workspace == world.project.resolve()
    assert (spec.account.tenant_id, spec.account.user_id) == ("t1", "u1")
    assert spec.account.session_id == made["id"] and spec.model == "sonnet"
    assert not live.running(made["id"])
    assert (world.project / "index.html").read_text() == "<h1>Bakery</h1>"


async def test_the_word_a_session_had_stands_after_a_turn_that_only_read(world):
    live, _ = sessions(world, answer)
    made = await live.start(ME, folder=str(world.project))
    world.store.set_session_result(ME, made["id"], rows.PASSED)
    await live.send(ME, made["id"], "A question")
    closed = await live.wait(ME, made["id"])
    assert closed["result"] == rows.PASSED and live.view(ME, made["id"])["result"] == rows.PASSED


async def test_the_second_turn_goes_to_the_same_session_of_the_place(world):
    live, place = sessions(world, answer)
    made = await live.start(ME, folder=str(world.project))
    for text in ("first", "second"):
        await live.send(ME, made["id"], text)
        await live.wait(ME, made["id"])
    assert [c[0] for c in place.calls] == ["start", "send", "send"]
    assert [t["position"] for t in live.turns(ME, made["id"])] == [1, 2]
    assert all(t["why"] == places.FINISHED for t in live.turns(ME, made["id"]))


async def test_the_relay_gives_states_steps_words_and_the_message_in_order(world):
    live, _ = sessions(world, answer)
    made = await live.start(ME, folder=str(world.project))
    feed = live.feed(made["id"])
    got: list[dict] = []

    async def listen():
        async for event in feed.follow():
            got.append(event)
            if event["type"] == "code_state" and event["state"] == rows.DONE:
                return

    listening = asyncio.ensure_future(listen())
    await asyncio.sleep(0)
    await live.send(ME, made["id"], "What is this?")
    await asyncio.wait_for(listening, 5)
    assert [(e["type"], e.get("state") or e.get("status")) for e in got] == [
        ("code_state", rows.WORKING), ("code_step", "started"), ("code_piece", None),
        ("code_piece", None), ("code_text", None), ("code_state", rows.TURN_ENDED),
        ("code_state", rows.DONE),
    ]  # fmt: skip
    assert got[1]["tool"] == "glob" and got[1]["given"] == {"pattern": "**/*"}
    assert all(e["session_id"] == made["id"] for e in got)
    assert got[-1]["why"] == places.FINISHED and got[-1]["cost_usd"] == 0.25
    assert [e["seq"] for e in got] == list(range(1, 8))
    assert [e["type"] for e in feed.kept] == [e["type"] for e in got if e["type"] != "code_piece"]


async def test_a_refusal_is_a_plain_message_and_an_error_is_written_on_the_turn(world):
    async def refuse(turn: FakeTurn) -> str:
        turn.say("The model declined this request.")
        return places.REFUSED

    async def broken(turn: FakeTurn) -> str:
        raise RuntimeError("The model could not be reached.")

    live, _ = sessions(world, scripted(refuse, broken))
    made = await live.start(ME, folder=str(world.project))
    await live.send(ME, made["id"], "Do something it will not")
    refused = await live.wait(ME, made["id"])
    assert (
        refused["why"] == places.REFUSED and refused["answer"] == "The model declined this request."
    )
    assert refused["notes"] == []  # it is not an error
    await live.send(ME, made["id"], "Now break")
    failed = await live.wait(ME, made["id"])
    assert failed["why"] == places.ERROR and failed["notes"] == ["The model could not be reached."]
    kinds = [e["type"] for e in live.feed(made["id"]).kept]
    assert kinds.count("code_refusal") == 1


async def test_a_place_that_cannot_start_ends_the_turn_in_words(world):
    live, place = sessions(world)

    async def cannot(spec):
        raise PlaceError("The coding engine is not set up yet. Set it up in Settings first.")

    place.start = cannot  # type: ignore[method-assign]
    made = await live.start(ME, folder=str(world.project))
    await live.send(ME, made["id"], "Hello")
    closed = await live.wait(ME, made["id"])
    assert closed["why"] == places.ERROR and "not set up yet" in closed["notes"][0]
    assert not live.running(made["id"])


async def test_stop_works_in_every_state_within_a_second(world):
    reached = asyncio.Event()

    async def for_ever(turn: FakeTurn) -> None:
        turn.step("grep", pattern="x")
        reached.set()
        await asyncio.sleep(3600)

    live, place = sessions(world, for_ever)
    made = await live.start(ME, folder=str(world.project))
    assert await live.stop(ME, made["id"]) is False  # nothing is running
    # 1. at once, before the place has done anything
    await live.send(ME, made["id"], "one")
    began = time.monotonic()
    assert await live.stop(ME, made["id"]) is True
    assert time.monotonic() - began < 1.0
    # 2. while the agent works
    await live.send(ME, made["id"], "two")
    await asyncio.wait_for(reached.wait(), 5)
    began = time.monotonic()
    assert await live.stop(ME, made["id"]) is True
    assert time.monotonic() - began < 1.0
    assert ("stop", place.calls[-1][1]) == place.calls[-1][:2]
    # 3. while the place is still making the session
    slow = asyncio.Event()

    async def slow_start(spec):
        slow.set()
        await asyncio.sleep(3600)

    other = await live.start(ME, folder=str(world.project))
    place.start = slow_start  # type: ignore[method-assign]
    await live.send(ME, other["id"], "three")
    await asyncio.wait_for(slow.wait(), 5)
    began = time.monotonic()
    assert await live.stop(ME, other["id"]) is True
    assert time.monotonic() - began < 1.0
    whys = [t["why"] for t in live.turns(ME, made["id"])] + [
        t["why"] for t in live.turns(ME, other["id"])
    ]
    assert whys == [places.STOPPED] * 3
    assert not live.running(made["id"]) and not live.running(other["id"])


async def test_a_message_while_the_agent_works_and_an_empty_one_are_refused(world):
    async def for_ever(turn: FakeTurn) -> None:
        await asyncio.sleep(3600)

    live, _ = sessions(world, for_ever)
    made = await live.start(ME, folder=str(world.project))
    with pytest.raises(Refused) as e:
        await live.send(ME, made["id"], "   ")
    assert e.value.code == "nothing_to_do"
    await live.send(ME, made["id"], "one")
    with pytest.raises(Refused) as e:
        await live.send(ME, made["id"], "two")
    assert e.value.code == "busy"
    await live.stop(ME, made["id"])


async def test_another_person_cannot_see_send_to_or_stop_a_session(world):
    live, _ = sessions(world, answer)
    made = await live.start(ME, folder=str(world.project))
    other = Owner("t1", "someone-else")
    for call in (
        lambda: live.send(other, made["id"], "hello"),
        lambda: live.stop(other, made["id"]),
        lambda: live.wait(other, made["id"]),
        lambda: live.delete(other, made["id"]),
    ):
        with pytest.raises(Refused) as e:
            await call()
        assert e.value.code == "not_found"
    with pytest.raises(Refused):
        live.view(Owner("another-tenant", "u1"), made["id"])


async def test_closing_stops_every_turn_in_flight(world):
    async def for_ever(turn: FakeTurn) -> None:
        await asyncio.sleep(3600)

    live, _ = sessions(world, for_ever)
    made = await live.start(ME, folder=str(world.project))
    await live.send(ME, made["id"], "one")
    await live.close()
    assert live.turns(ME, made["id"])[0]["why"] == places.STOPPED


# ---- cost ----------------------------------------------------------------------------------------


async def test_each_model_call_is_added_to_the_sessions_row(world):
    live, _ = sessions(world)
    made = await live.start(ME, folder=str(world.project), cost_limit_usd=2.5)
    for usd in (0.014, 0.006):
        await live._on_call(
            SimpleNamespace(session_id=made["id"], usd=usd, input_tokens=1000, output_tokens=50)
        )
    seen = live.view(ME, made["id"])
    assert seen["cost_usd"] == pytest.approx(0.02) and seen["cost_limit_usd"] == 2.5
    assert (seen["tokens_in"], seen["tokens_out"]) == (2000, 100)
    assert world.store.get_session(ME, made["id"])["model_calls"] == 2


# ---- search (ADR-0041) -----------------------------------------------------------------------------


async def test_a_session_is_given_to_search_by_its_title_project_and_first_request(world):
    live, _ = sessions(world, answer)
    made = await live.start(ME, folder=str(world.project), title="Opening hours")
    index = world.state.creation_index
    assert index.items[made["id"]] == (
        "t1", "wasifyai-code", "u1", KIND, "Opening hours. Coding session on bakery-site",
    )  # fmt: skip
    await live.send(ME, made["id"], "Where are the opening hours shown?")
    await live.wait(ME, made["id"])
    assert index.items[made["id"]][4] == (
        "Opening hours. Coding session on bakery-site. Where are the opening hours shown?"
    )
    await live.send(ME, made["id"], "And the prices?")  # only the first request names it
    await live.wait(ME, made["id"])
    assert "prices" not in index.items[made["id"]][4]
    assert words_of("", "site", "") == "Coding session on site"


async def test_search_never_fails_a_request(world):
    async def broken(*a):
        raise RuntimeError("the embedder is down")

    world.state.creation_index.index = broken
    live, _ = sessions(world)
    assert (await live.start(ME, folder=str(world.project)))["state"] == "new"
    world.state.creation_index = None
    assert (await live.start(ME, folder=str(world.project)))["state"] == "new"


async def test_the_index_source_lists_every_session_and_says_which_are_gone(world):
    live, _ = sessions(world, answer)
    one = await live.start(ME, folder=str(world.project), title="First")
    two = await live.start(Owner("t1", "u2"), folder=str(world.project), title="Second")
    await live.send(ME, one["id"], "Find the footer")
    await live.wait(ME, one["id"])
    engine = SimpleNamespace(
        dialect=SimpleNamespace(name="sqlite"),
        url=SimpleNamespace(database=str(world.data / "wasifyai.db")),
    )
    source = CodeIndexSource(engine)  # type: ignore[arg-type]
    assert (source.product_id, source.kind) == ("wasifyai-code", "code_session")
    items = await source.page(None, 10)
    assert sorted(i.item_id for i in items) == sorted([one["id"], two["id"]])
    by = {i.item_id: i for i in items}
    assert by[one["id"]].text == "First. Coding session on bakery-site. Find the footer"
    assert (by[two["id"]].tenant_id, by[two["id"]].user_id, by[two["id"]].kind) == (
        "t1", "u2", "code_session",
    )  # fmt: skip
    first, second = sorted([one["id"], two["id"]])
    assert [i.item_id for i in await source.page(first, 10)] == [second]
    assert await live.delete(ME, one["id"]) is True
    assert await source.present([one["id"], two["id"], "0" * 32]) == {two["id"]}
    assert await source.present([]) == set()
    # where there is no desktop store nothing is listed, and nothing is said to be gone
    nowhere = CodeIndexSource(
        SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"), url=SimpleNamespace(database="x")
        )  # type: ignore[arg-type]
    )
    assert await nowhere.page(None, 10) == [] and await nowhere.present(["a"]) == {"a"}


# ---- where there is no coding ----------------------------------------------------------------------


def test_without_a_store_or_an_engine_coding_is_not_available():
    empty = SimpleNamespace(
        code_store=None, code_sessions=None, coding_server=None, coding_gateway=None
    )  # noqa: E501
    with pytest.raises(NotAvailable):
        store_for(empty)
    with pytest.raises(NotAvailable):
        sessions_for(empty)
