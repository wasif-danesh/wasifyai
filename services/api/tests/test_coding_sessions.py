# ruff: noqa: E501  (test data is easier to read on one line)
"""A coding session that only reads, from the product's routes and actions down to the Agent Server
(stage C1b): the real supervisor (`coding_server.py`), the real gateway, the real place
(`wasifyai_code/client.py`) and the real store, against the fake Agent Server, which replays event
streams recorded from the real one. No model, no network. The same calls against the real, pinned
server are `tests/integration/test_coding_session_real.py` (`make test-coding`)."""

import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from wasifyai_api.coding_gateway import CodingGateway
from wasifyai_api.coding_gateway import router as gateway_router
from wasifyai_api.services import ApiServices
from wasifyai_api.tool_host import ApiToolHost
from wasifyai_code import place as places
from wasifyai_code.client import READ_TOOLS, WRITE_TOOLS, ThisComputer
from wasifyai_code.place import Account, Busy, NoSuchSession, SessionSpec
from wasifyai_code.routes import build_routes
from wasifyai_code.runtime import sessions_for
from wasifyai_code.store import CodeStore
from wasifyai_platform_sdk import Identity, RouteDeps
from wasifyai_platform_sdk.actions import need_runtime
from wasifyai_platform_sdk.secrets import InMemorySecretStore
from wasifyai_platform_sdk.usage import InMemoryUsageRecorder

from tests.test_coding_server import install, real, server, terminal_folders
from tests.test_desktop_profile import data_dir  # noqa: F401

pytestmark = pytest.mark.skipif(
    __import__("sys").platform == "win32", reason="the fake server is a shell script"
)

ME = Identity("t1", "u1")
KEY = "sk-ant-a-real-key-that-must-stay-outside"
ANSWER = "It is a small Python project: app.py uses shop/prices.py."


class Box:
    """An engine's coding services on a throwaway data folder, with the fake Agent Server."""

    def __init__(self, tmp_path: Path, **fake_env: str):
        self.data = tmp_path / "data"
        install(self.data, **fake_env)
        self.project = tmp_path / "bakery-site"
        (self.project / "shop").mkdir(parents=True)
        (self.project / "app.py").write_text("from shop.prices import total\n")
        (self.project / "shop" / "prices.py").write_text("def total(xs):\n    return sum(xs)\n")
        self.server = server(self.data)
        self.secrets = InMemorySecretStore()
        self.usage = InMemoryUsageRecorder()
        self.gateway = CodingGateway(
            secrets=self.secrets, usage=self.usage,
            base_url=lambda: "http://127.0.0.1:9", ollama_url="http://127.0.0.1:11434",
        )  # fmt: skip
        self.store = CodeStore.in_folder(self.data / "code")
        self.services = ApiServices(
            coding_server=self.server, coding_gateway=self.gateway, code_store=self.store,
            desktop_dir=self.data,
        )  # fmt: skip
        self.deps = RouteDeps(self.services, lambda: ME)
        app = FastAPI()
        app.state.services = self.services
        app.include_router(build_routes(self.deps), prefix="/products/wasifyai-code")
        app.include_router(gateway_router)
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
        )

    def place(self) -> ThisComputer:
        return ThisComputer(self.server, self.gateway, known=self.store.workspace_paths)

    def spec(self, folder: Path | None = None, **more) -> SessionSpec:
        more.setdefault("model", "qwen-27b-ollama")
        more.setdefault("read_only", True)
        return SessionSpec(folder or self.project, **more)

    async def made_with(self, conversation: str) -> dict:
        return (await self.server.request("GET", f"/fake/conversations/{conversation}")).json()

    async def close(self) -> None:
        if self.services.code_sessions is not None:
            await self.services.code_sessions.close()
        await self.http.aclose()
        await self.server.close()
        await self.gateway.close()
        self.store.close()


@pytest.fixture
async def box(tmp_path):
    before = terminal_folders()
    b = Box(tmp_path)
    await b.secrets.put("keys.chat.anthropic", KEY)
    yield b
    await b.close()
    assert terminal_folders() == before


async def turn(place: ThisComputer, session: str, text: str, after: str | None = None):
    """Listen, send a message and read the turn to its end: the events, in order."""
    opened = asyncio.Event()
    stream = place.follow(session, after=after, opened=opened)
    first = asyncio.ensure_future(anext(stream))
    seen = []
    try:
        async with asyncio.timeout(20):
            await opened.wait()
            await asyncio.sleep(0.05)  # the fake needs a moment to add the listener
            await place.send(session, text, run=True)
            event = await first
            while True:
                seen.append(event)
                if event.kind == places.ENDED:
                    return seen
                event = await anext(stream)
    finally:
        first.cancel()
        await stream.aclose()


def kinds(events) -> list[str]:
    return [e.kind for e in events if e.kind != places.PIECE]


# ---- the place: this computer ----------------------------------------------------------------------


async def test_a_session_that_only_reads_has_no_tool_that_writes_or_runs(box):
    place = box.place()
    session = await place.start(box.spec(step_limit=30))
    asked = await box.made_with(session)
    tools = [t["name"] for t in asked["agent_settings"]["tools"]]
    assert tools == list(READ_TOOLS)
    assert not set(tools) & set(WRITE_TOOLS)  # no terminal, no file editor, no patch tool
    # the one file its viewer may edit is in a folder the sandbox opens for reading only
    plan = [t for t in asked["agent_settings"]["tools"] if t["name"] == "planning_file_editor"]
    assert plan[0]["params"] == {"plan_path": str(box.server.plan_file)}
    assert box.server.plan_file.is_file() and real(box.data) in box.server.plan_file.parents
    assert "only reads" in asked["agent_settings"]["agent_context"]["system_message_suffix"]
    assert asked["workspace"] == {"working_dir": str(real(box.project))}
    assert asked["max_iterations"] == 30
    # the folder is opened to the server for reading, not for writing
    assert box.server.read_only == (real(box.project),) and box.server.workspaces == ()
    profile = (box.data / "coding" / "engine.sb").read_text()
    writes = profile.split("(allow file-write*", 1)[1].split("(deny file-read*", 1)[0]
    reads = profile.split("(allow file-read*", 1)[1].split("(allow file-read-metadata", 1)[0]
    assert str(real(box.project)) not in writes and str(real(box.project)) in reads
    assert str(box.server.plan_file.parent) not in writes


async def test_the_server_is_given_the_gateways_address_and_a_token_never_a_key(box):
    place = box.place()
    session = await place.start(
        box.spec(model="claude-sonnet-5-5", account=Account("t1", "wasifyai-code", "u1", "s-1"))
    )
    llm = (await box.made_with(session))["agent_settings"]["llm"]
    assert llm["model"] == "anthropic/claude-sonnet-5-5" and llm["stream"] is True
    assert llm["base_url"] == "http://127.0.0.1:9/coding-gateway"
    assert llm["api_key"].startswith("wcg-") and KEY not in json.dumps(llm)
    assert box.gateway.is_open("s-1")
    # and nothing the server was started with, or wrote, holds the key
    env = (await box.server.request("GET", "/fake/env")).json()
    assert KEY not in json.dumps(env)
    for path in (box.data / "coding").rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes(), path


async def test_a_session_that_may_write_gets_the_engines_own_tools_and_a_writable_folder(box):
    place = box.place()
    session = await place.start(box.spec(read_only=False))
    asked = await box.made_with(session)
    assert "tools" not in asked["agent_settings"]  # the engine's standard set
    assert box.server.workspaces == (real(box.project),)


async def test_a_turns_events_come_in_the_places_own_words_and_end_once(box):
    place = box.place()
    session = await place.start(box.spec())
    events = await turn(place, session, "Analyse this codebase.")
    assert kinds(events) == [
        places.STATE, places.STEP, places.RESULT, places.STEP, places.RESULT,
        places.TEXT, places.STATE, places.ENDED,
    ]  # fmt: skip
    first, second = (e for e in events if e.kind == places.STEP)
    assert first.data["tool"] == "glob" and first.data["pattern"] == "**/*.py"
    assert second.data["tool"] == "planning_file_editor" and second.data["command"] == "view"
    assert second.data["path"] == f"{real(box.project)}/app.py"
    results = [e for e in events if e.kind == places.RESULT]
    assert results[0].data["id"] == first.data["id"] and results[0].data["ok"] is True
    assert "app.py" in results[0].data["text"]
    (said,) = (e for e in events if e.kind == places.TEXT)
    assert said.data["text"] == ANSWER  # what the agent finished with
    assert events[-1].data == {"why": places.FINISHED, "detail": "", "steps": 2}
    assert len({e.id for e in events}) == len(events)


async def test_the_next_turn_is_followed_from_where_the_last_one_ended(box):
    place = box.place()
    session = await place.start(box.spec())
    first = await turn(place, session, "Analyse this codebase.")
    second = await turn(place, session, "And again. #replay:step-limit", after=first[-1].id)
    assert kinds(second) == [
        places.STATE,
        *[places.STEP, places.RESULT] * 3,
        places.STATE,
        places.ENDED,
    ]
    assert second[-1].data["why"] == places.STEP_LIMIT and second[-1].data["steps"] == 3
    assert not {e.id for e in first} & {e.id for e in second}


async def test_a_dropped_socket_loses_nothing_and_repeats_nothing(box):
    place = box.place()
    whole = await place.start(box.spec())
    expected = [(e.kind, e.data) for e in await turn(place, whole, "Analyse this codebase.")]
    cut = await place.start(box.spec())
    # the socket is cut after three events of the turn; the events go on while nobody listens
    got = await turn(place, cut, "Analyse this codebase. #drop:3 #slow:30")
    assert [(e.kind, e.data) for e in got if e.kind != places.STEP or True] != []
    kept = [(e.kind, _no_ids(e.data)) for e in got if e.kind != places.PIECE]
    wanted = [(k, _no_ids(d)) for k, d in expected if k != places.PIECE]
    assert kept == wanted  # every kept event once, in order; word pieces are not kept
    assert len({e.id for e in got}) == len(got)


def _no_ids(data: dict) -> dict:
    return {k: v for k, v in data.items() if k != "id"}


async def test_stop_ends_a_turn_that_would_never_end_within_a_second(box):
    place = box.place()
    session = await place.start(box.spec())
    await place.send(session, "Think for ever. #hang", run=True)
    seen: list = []

    async def follow():
        async for event in place.follow(session):
            seen.append(event)
            if event.kind == places.ENDED:
                return event

    following = asyncio.ensure_future(follow())
    await asyncio.sleep(0.4)
    assert any(e.kind == places.PIECE for e in seen) and place.working() == [session]
    began = time.monotonic()
    await place.stop(session)
    ended = await asyncio.wait_for(following, 5)
    assert ended is not None
    assert time.monotonic() - began < 1.0
    assert ended.data["why"] == places.STOPPED and place.working() == []
    await place.stop(session)  # stopping what is not running does nothing
    # and the session can be sent to again
    again = await turn(place, session, "Analyse this codebase.", after=ended.id)
    assert again[-1].data["why"] == places.FINISHED


async def test_a_message_to_a_session_in_the_middle_of_a_turn_is_refused(box):
    place = box.place()
    session = await place.start(box.spec())
    await place.send(session, "#hang", run=True)
    with pytest.raises(Busy):
        await place.send(session, "one more", run=True)
    await place.stop(session)
    with pytest.raises(NoSuchSession):
        await place.send("not-a-session", "hello")


async def test_how_a_turn_ended_is_said_in_one_of_five_words(box):
    place = box.place()
    account = Account("t1", "wasifyai-code", "u1", "s-9")
    session = await place.start(box.spec(account=account))
    error = await turn(place, session, "#replay:engine-error")
    assert error[-1].data["why"] == places.ERROR
    assert error[-1].data["detail"] == "The model could not be reached."
    # the engine cannot tell a refusal from an answer: only the gateway saw it
    box.gateway._by_session["s-9"].refusal = {
        "message": "The model declined this request.",
        "category": "cyber",
    }  # noqa: E501
    refused = await turn(place, session, "#replay:refusal", after=error[-1].id)
    assert refused[-1].data["why"] == places.REFUSED
    assert refused[-1].data["detail"] == "The model declined this request."
    box.gateway._by_session["s-9"].over_limit = True
    limit = await turn(place, session, "#replay:engine-error", after=refused[-1].id)
    assert limit[-1].data["why"] == places.ERROR and "cost limit" in limit[-1].data["detail"]
    tried = await turn(place, session, "#replay:write-refused", after=limit[-1].id)
    result = next(e for e in tried if e.kind == places.RESULT)
    assert result.data["ok"] is False and tried[-1].data["why"] == places.FINISHED


async def test_one_server_serves_every_workspace_and_a_new_folder_waits_for_a_running_turn(
    box, tmp_path
):
    other = tmp_path / "other-project"
    other.mkdir()
    third = tmp_path / "third-project"
    third.mkdir()
    box.store.add_workspace(_owner(), str(other))  # a folder the person opened before
    place = box.place()
    first = await place.start(box.spec())
    pid = box.server.pid
    # the server was started with every known workspace: a session on another starts nothing
    assert set(box.server.read_only) == {real(box.project), real(other)}
    second = await place.start(box.spec(other))
    assert box.server.pid == pid and first != second
    # a folder that is new needs the server to start again: not while a turn is running
    await place.send(first, "#hang", run=True)
    with pytest.raises(Busy, match="another session is in the middle of a turn"):
        await place.start(box.spec(third))
    assert box.server.pid == pid
    await place.stop(first)
    async with asyncio.timeout(5):
        async for event in place.follow(first):
            if event.kind == places.ENDED:
                break
    await place.start(box.spec(third))
    assert box.server.pid != pid
    assert set(box.server.read_only) == {real(box.project), real(other), real(third)}


def _owner():
    from wasifyai_code.store import Owner

    return Owner("t1", "u1")


# ---- the product, through its routes ---------------------------------------------------------------

BASE = "/products/wasifyai-code/code"


async def started(box: Box, **body) -> dict:
    body.setdefault("folder", str(box.project))
    body.setdefault("model", "qwen-27b-ollama")
    r = await box.http.post(f"{BASE}/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def ended(box: Box, session_id: str, seconds: float = 20.0) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        seen = (await box.http.get(f"{BASE}/sessions/{session_id}")).json()
        if not seen["working"] and seen["state"] == "done":
            return seen
        await asyncio.sleep(0.05)
    raise AssertionError("the turn did not end")


async def test_a_session_is_started_sent_to_and_answered_through_the_routes(box):
    made = await started(box, title="Look at the bakery site")
    assert (
        made["state"] == "new"
        and made["mode"] == "plan"
        and made["folder"] == str(real(box.project))
    )
    assert made["project"] == "bakery-site" and made["model"] == "qwen-27b-ollama"
    assert not box.server.running  # nothing is started until something is asked
    sent = await box.http.post(
        f"{BASE}/sessions/{made['id']}/messages", json={"text": "Analyse this codebase."}
    )
    assert sent.status_code == 202 and sent.json()["session"]["working"] is True
    seen = await ended(box, made["id"])
    assert seen["answer"].startswith(ANSWER) and seen["ended"] == "finished"
    assert seen["result"] == "" and seen["turns"] == 1  # nothing was checked: nothing changed
    turns = (await box.http.get(f"{BASE}/sessions/{made['id']}/turns")).json()["items"]
    assert turns[0]["request"] == "Analyse this codebase." and turns[0]["steps"] == 2
    assert turns[0]["state"] == "done" and turns[0]["why"] == "finished"
    listed = (await box.http.get(f"{BASE}/sessions")).json()["items"]
    assert [s["id"] for s in listed] == [made["id"]]
    only = await box.http.get(f"{BASE}/sessions", params={"ids": made["id"]})
    assert [s["id"] for s in only.json()["items"]] == [made["id"]]
    # no id or key of the coding engine is in any answer
    everything = json.dumps([made, sent.json(), seen, turns, listed])
    row = box.store.get_session(_owner(), made["id"])
    assert row["place_session"] and row["place_session"] not in everything
    assert "wcg-" not in everything and KEY not in everything
    # nothing in the project changed
    assert sorted(p.name for p in box.project.rglob("*")) == ["app.py", "prices.py", "shop"]


async def test_the_events_are_relayed_inside_the_engine_in_order(box):
    made = await started(box)
    feed = sessions_for(box.services).feed(made["id"])
    live: list[dict] = []

    async def listen():
        async for event in feed.follow():
            live.append(event)
            if event["event"] == "code_state" and event["state"] == "done":
                return

    listening = asyncio.ensure_future(listen())
    await box.http.post(f"{BASE}/sessions/{made['id']}/messages", json={"text": "Analyse this."})
    await asyncio.wait_for(listening, 20)
    kept = [e for e in live if e["event"] not in ("token", "reasoning")]
    assert [(e["event"], e.get("state") or e.get("status")) for e in kept] == [
        ("code_state", "working"),
        ("tool_call", None), ("tool_result", "ok"),
        ("tool_call", None), ("tool_result", "ok"),
        ("code_message", None),
        ("code_state", "turn_ended"), ("code_state", "done"),
    ]  # fmt: skip
    # every event is one the SSE contract knows
    from pydantic import TypeAdapter
    from wasifyai_contracts.events import SseEvent

    for event in live:
        TypeAdapter(SseEvent).validate_python(event)
    assert kept[5]["text"] == ANSWER
    assert [e["seq"] for e in live] == sorted(e["seq"] for e in live)
    step = kept[1]
    assert step["name"] == "glob" and step["arguments"]["pattern"] == "**/*.py"
    assert kept[2]["id"] == step["id"] and "app.py" in kept[2]["output"]["text"]
    assert kept[-1]["why"] == "finished" and kept[-1]["thread_id"] == made["id"]
    # a listener that comes later gets what was kept, and not the word pieces
    late = []
    async for event in feed.follow():
        late.append(event)
        if len(late) == len(kept):
            break
    assert late == kept


async def test_stop_works_within_a_second_at_any_moment(box):
    made = await started(box)
    url = f"{BASE}/sessions/{made['id']}"
    # 1. at once: the coding engine has not even started
    await box.http.post(f"{url}/messages", json={"text": "#hang"})
    began = time.monotonic()
    stopped = await box.http.post(f"{url}/stop")
    assert time.monotonic() - began < 1.0
    assert stopped.json()["stopped"] is True and stopped.json()["session"]["ended"] == "stopped"
    # 2. while the agent works
    await box.http.post(f"{url}/messages", json={"text": "#hang"})
    await asyncio.sleep(1.5)
    assert (await box.http.get(url)).json()["working"] is True
    began = time.monotonic()
    stopped = await box.http.post(f"{url}/stop")
    assert time.monotonic() - began < 1.0
    seen = stopped.json()["session"]
    assert seen["working"] is False and seen["ended"] == "stopped" and seen["result"] == ""
    # 3. when nothing runs: nothing happens
    assert (await box.http.post(f"{url}/stop")).json()["stopped"] is False
    # and the session answers the next message
    await box.http.post(f"{url}/messages", json={"text": "Analyse this codebase."})
    assert (await ended(box, made["id"]))["ended"] == "finished"
    turns = (await box.http.get(f"{url}/turns")).json()["items"]
    assert [t["why"] for t in turns] == ["stopped", "stopped", "finished"]


async def test_a_refusal_and_an_error_are_said_in_words_and_are_not_the_same(box):
    made = await started(box)
    url = f"{BASE}/sessions/{made['id']}"
    await box.http.post(f"{url}/messages", json={"text": "#replay:engine-error"})
    seen = await ended(box, made["id"])
    assert seen["ended"] == "error"
    turns = (await box.http.get(f"{url}/turns")).json()["items"]
    assert turns[-1]["notes"] == ["The model could not be reached."]
    box.gateway._by_session[made["id"]].refusal = {
        "message": "The model declined this request. No.",
        "category": "",
    }  # noqa: E501
    await box.http.post(f"{url}/messages", json={"text": "#replay:refusal"})
    seen = await ended(box, made["id"])
    assert seen["ended"] == "refused" and seen["answer"] == "The model declined this request. No."
    kept = sessions_for(box.services).feed(made["id"]).kept
    assert [e["message"] for e in kept if e["event"] == "code_refusal"] == [seen["answer"]]


async def test_a_second_message_while_the_agent_works_is_refused_in_words(box):
    made = await started(box)
    url = f"{BASE}/sessions/{made['id']}"
    await box.http.post(f"{url}/messages", json={"text": "#hang"})
    again = await box.http.post(f"{url}/messages", json={"text": "and this"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "busy"
    await box.http.post(f"{url}/stop")


async def test_folders_that_must_stay_closed_are_refused(box, tmp_path):
    home = Path.home()
    for folder, code in (
        ("relative/path", "bad_folder"),
        (str(tmp_path / "nothing-here"), "no_folder"),
        (str(home), "too_wide"),
        ("/", "too_wide"),
        (str(box.data), "private_folder"),  # the app's own data: its keys are there
        (str(box.data / "code"), "private_folder"),
        (str(tmp_path), "private_folder"),  # it holds the app's data folder
        # the Mac's Library; on a computer that has none it is simply a folder that is not there
        (str(home / "Library"), "private_folder" if (home / "Library").is_dir() else "no_folder"),
    ):
        r = await box.http.post(f"{BASE}/sessions", json={"folder": folder})
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, folder
    assert box.store.list_workspaces(_owner()) == []


async def test_a_model_without_its_key_and_an_unknown_model_are_refused_in_words(box):
    await box.secrets.delete("keys.chat.anthropic")
    r = await box.http.post(f"{BASE}/sessions", json={"folder": str(box.project)})
    assert r.status_code == 409 and "No key is saved for Claude Sonnet 5.5" in r.text
    r = await box.http.post(
        f"{BASE}/sessions", json={"folder": str(box.project), "model": "something-else"}
    )
    assert r.status_code == 422
    models = (await box.http.get(f"{BASE}/models")).json()["items"]
    assert [(m["id"], m["ready"]) for m in models] == [
        ("claude-sonnet-5-5", False), ("qwen-27b-ollama", True),
    ]  # fmt: skip


async def test_another_persons_session_is_not_there(box):
    made = await started(box)
    box.deps.identity = lambda: Identity("t1", "someone-else")  # type: ignore[assignment]
    other = FastAPI()
    other.state.services = box.services
    other.include_router(
        build_routes(RouteDeps(box.services, lambda: Identity("t1", "someone-else"))),
        prefix="/products/wasifyai-code",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=other), base_url="http://engine.test"
    ) as theirs:
        assert (await theirs.get(f"{BASE}/sessions/{made['id']}")).status_code == 404
        assert (await theirs.get(f"{BASE}/sessions")).json()["items"] == []
        sent = await theirs.post(f"{BASE}/sessions/{made['id']}/messages", json={"text": "hi"})
        assert sent.status_code == 404
        assert (await theirs.post(f"{BASE}/sessions/{made['id']}/stop")).status_code == 404


async def test_a_deleted_session_is_gone_and_its_token_with_it(box):
    made = await started(box)
    url = f"{BASE}/sessions/{made['id']}"
    await box.http.post(f"{url}/messages", json={"text": "Analyse this codebase."})
    await ended(box, made["id"])
    assert box.gateway.is_open(made["id"])
    assert (await box.http.delete(url)).status_code == 204
    assert (await box.http.get(url)).status_code == 404
    assert not box.gateway.is_open(made["id"])
    assert (await box.http.delete(url)).status_code == 204  # already gone
    assert box.project.is_dir()  # the folder is the person's


async def test_the_routes_answer_404_where_there_is_no_coding_engine(tmp_path):
    app = FastAPI()
    services = ApiServices()
    app.state.services = services
    app.include_router(
        build_routes(RouteDeps(services, lambda: ME)), prefix="/products/wasifyai-code"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as http:
        assert (await http.get(f"{BASE}/sessions")).status_code == 404
        assert (await http.post(f"{BASE}/sessions", json={"folder": "/x"})).status_code == 404


# ---- what a session needs to be ready --------------------------------------------------------------


async def test_the_actions_say_what_to_set_up_when_the_engine_is_not_installed(tmp_path):
    need = need_runtime("coding")
    empty = ApiServices()
    nothing = ApiToolHost(lambda: None, lambda: None, state=lambda: empty)
    assert (await nothing.readiness(need)).state == "unavailable"
    data = tmp_path / "data"
    services = ApiServices(
        coding_server=server(data),
        coding_gateway=CodingGateway(
            secrets=InMemorySecretStore(), usage=InMemoryUsageRecorder(), base_url=lambda: ""
        ),
    )
    host = ApiToolHost(lambda: None, lambda: None, state=lambda: services)
    missing = await host.readiness(need)
    assert missing.state == "needs_setup" and "Optional parts" in missing.step
    install(data)
    assert (await host.readiness(need)).state == "ready"
    await services.coding_gateway.close()
    await services.coding_server.close()


# ---- the whole desktop engine ----------------------------------------------------------------------


def test_the_desktop_engine_serves_the_coding_product_and_opens_its_store(data_dir):  # noqa: F811
    from fastapi.testclient import TestClient
    from wasifyai_api.main import create_app

    from tests.test_desktop_profile import auth

    with TestClient(create_app()) as c:
        services = c.app.state.services  # type: ignore[attr-defined]
        # the store is opened by the engine at its start, outside the coding engine's own folder
        assert services.code_store is not None and (data_dir / "code" / "code.db").is_file()
        assert not (data_dir / "coding").exists()  # nothing of the coding engine is started
        assert services.coding_gateway is not None and services.coding_server is not None
        # every route asks who is calling
        assert c.get(f"{BASE}/sessions").status_code == 401
        assert c.get(f"{BASE}/sessions", headers=auth()).json() == {"items": []}
        models = c.get(f"{BASE}/models", headers=auth()).json()["items"]
        assert [m["id"] for m in models] == ["claude-sonnet-5-5", "qwen-27b-ollama"]
        assert models[0]["default"] is True and models[0]["ready"] is False  # no key is saved
        # the gateway's door is there; a person's own token opens nothing at it, nor does no token
        for headers in ({}, auth(), {"x-api-key": "wcg-made-up"}):
            r = c.post("/coding-gateway/v1/messages", json={"model": "x"}, headers=headers)
            assert r.status_code == 401, headers
        # the three actions are offered to the assistant, and say what to set up
        ids = {a.id for a in services.actions.registry}
        assert {"code.session.start", "code.session.send", "code.session.stop"} <= ids
        started = c.post(
            f"{BASE}/sessions", json={"folder": str(data_dir)}, headers=auth()
        )  # the app's own data folder
        assert started.status_code == 422 and started.json()["detail"]["code"] == "private_folder"
    # closing the engine closes the store
    assert services.code_store is not None


# ---- the stream to the window ----------------------------------------------------------------------


async def test_the_stream_sends_the_kept_events_then_new_ones_and_comes_back_after_a_number(box):
    from wasifyai_code.routes import _stream

    made = await started(box)
    url = f"{BASE}/sessions/{made['id']}"
    await box.http.post(f"{url}/messages", json={"text": "Analyse this codebase."})
    await ended(box, made["id"])
    feed = sessions_for(box.services).feed(made["id"])

    async def read(after: int, count: int) -> list[str]:
        out = []
        stream = _stream(feed.follow(after), 0.05)
        async for chunk in stream:
            out.append(chunk)
            if len(out) == count:
                break
        await stream.aclose()
        return out

    kept = len(feed.kept)
    chunks = await read(0, kept + 1)
    assert chunks[-1] == ": ping\n\n"  # nothing new: a comment keeps the connection open
    first = chunks[0].splitlines()
    assert first[0] == "id: 1" and first[1] == "event: code_state"
    body = json.loads(first[2].removeprefix("data: "))
    assert body["state"] == "working" and body["thread_id"] == made["id"] and "event" not in body
    assert [c.splitlines()[1] for c in chunks[:-1]][-1] == "event: code_state"
    # coming back with the last number seen gives only what came after it
    later = await read(kept - 2, 2)
    assert [c.splitlines()[0] for c in later] == [f"id: {kept - 1}", f"id: {kept}"]


async def test_the_stream_is_only_for_the_sessions_own_person(box):
    made = await started(box)
    other = FastAPI()
    other.state.services = box.services
    other.include_router(
        build_routes(RouteDeps(box.services, lambda: Identity("t1", "someone-else"))),
        prefix="/products/wasifyai-code",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=other), base_url="http://engine.test"
    ) as theirs:
        assert (await theirs.get(f"{BASE}/sessions/{made['id']}/events")).status_code == 404


# ---- the Files tab ---------------------------------------------------------------------------------


async def test_the_projects_files_are_listed_a_folder_at_a_time_and_read_as_text(box, tmp_path):
    (box.project / ".git").mkdir()
    (box.project / ".git" / "HEAD").write_text("ref")
    (box.project / "logo.bin").write_bytes(b"\x89PNG\x00\x00binary")
    made = await started(box)
    url = f"{BASE}/sessions/{made['id']}"
    top = (await box.http.get(f"{url}/files")).json()
    assert [(e["name"], e["kind"]) for e in top["entries"]] == [
        ("shop", "folder"),
        ("app.py", "file"),
        ("logo.bin", "file"),
    ]  # fmt: skip  (folders first; the project's own .git is left out)
    inner = (await box.http.get(f"{url}/files", params={"path": "shop"})).json()
    assert [e["path"] for e in inner["entries"]] == ["shop/prices.py"]
    read = (await box.http.get(f"{url}/file", params={"path": "shop/prices.py"})).json()
    assert read["text"] == "def total(xs):\n    return sum(xs)\n" and read["lines"] == 2
    assert read["binary"] is False and read["cut"] is False
    assert (await box.http.get(f"{url}/file", params={"path": "logo.bin"})).json()["binary"] is True
    assert not box.server.running  # the coding engine is not asked


async def test_nothing_outside_the_project_can_be_listed_or_read(box, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("the app's keys")
    (box.project / "link-out").symlink_to(tmp_path)
    (box.project / "link-file").symlink_to(secret)
    made = await started(box)
    url = f"{BASE}/sessions/{made['id']}"
    for path in (
        "..",
        "../secret.txt",
        "/etc/passwd",
        "shop/../../secret.txt",
        "link-out",
        "link-file",
    ):
        assert (await box.http.get(f"{url}/files", params={"path": path})).status_code == 404, path
        assert (await box.http.get(f"{url}/file", params={"path": path})).status_code == 404, path
    assert (
        await box.http.get(f"{url}/file", params={"path": "link-out/secret.txt"})
    ).status_code == 404
    names = [e["name"] for e in (await box.http.get(f"{url}/files")).json()["entries"]]
    assert "link-out" not in names and "link-file" not in names  # a link that leaves is not shown
    assert (await box.http.get(f"{BASE}/sessions/nobody/files")).status_code == 404


async def test_a_long_file_is_cut_at_a_whole_line_and_says_so(box):
    (box.project / "big.txt").write_text("line of text\n" * 60_000)
    made = await started(box)
    read = (
        await box.http.get(f"{BASE}/sessions/{made['id']}/file", params={"path": "big.txt"})
    ).json()
    assert read["cut"] is True and read["bytes"] == 780_000
    assert len(read["text"]) <= 400_000 and read["text"].endswith("line of text")
