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
from wasifyai_api.desktop_language import LanguageService, Selection
from wasifyai_api.llama_server import LlamaServer
from wasifyai_api.services import ApiServices
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_api.tool_host import ApiToolHost
from wasifyai_code import place as places
from wasifyai_code.client import READ_TOOLS, WRITE_TOOLS, ThisComputer
from wasifyai_code.place import Account, Busy, NoSuchSession, SessionSpec
from wasifyai_code.routes import build_routes
from wasifyai_code.runtime import owner_of, sessions_for
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
        # the model on this computer: a model of a running Ollama chosen in the Model hub
        self.language = LanguageService(InMemorySettingsStore(), LlamaServer(self.data))
        self.language.selected = Selection(
            "server", "qwen3.8:27b-mlx (ollama)", 8192, tool="ollama",
            url="http://127.0.0.1:11434", model="qwen3.8:27b-mlx",
        )  # fmt: skip
        self.gateway = CodingGateway(
            secrets=self.secrets, usage=self.usage,
            base_url=lambda: "http://127.0.0.1:9", language=self.language,
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
        more.setdefault("model", "this-computer")
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


async def test_a_session_that_may_write_gets_the_editor_and_the_terminal_and_both_wait(box):
    place = box.place()
    session = await place.start(box.spec(read_only=False))
    asked = await box.made_with(session)
    # it reads and edits; it has no terminal, no patch tool and no browser
    assert [t["name"] for t in asked["agent_settings"]["tools"]] == [
        "glob", "grep", "file_editor", "terminal",
    ]  # fmt: skip
    assert (
        "run commands in a terminal"
        in asked["agent_settings"]["agent_context"]["system_message_suffix"]
    )
    # every use of the editor that changes something waits; our rules give the answer
    assert asked["security_analyzer"] == {
        "kind": "WasifyRules", "wait_tools": ["file_editor", "terminal"],
    }  # fmt: skip
    assert asked["confirmation_policy"]["kind"] == "ConfirmRisky"
    assert asked["confirmation_policy"]["confirm_unknown"] is False
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
    body.setdefault("model", "this-computer")
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
    assert made["project"] == "bakery-site" and made["model"] == "this-computer"
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
        ("claude-sonnet-5-5", False),
        ("claude-haiku-5-5", False),
        ("this-computer", True),
    ]  # fmt: skip  (both cloud models wait for the one key)


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
        # the model on this computer is the Model hub's, and none is chosen yet
        assert [m["id"] for m in models] == [
            "claude-sonnet-5-5",
            "claude-haiku-5-5",
            "this-computer",
        ]
        assert models[2]["ready"] is False
        assert models[0]["default"] is True and models[0]["ready"] is False  # no key is saved
        # the gateway's door is there; a person's own token opens nothing at it, nor does no token
        for headers in ({}, auth(), {"x-api-key": "wcg-made-up"}):
            r = c.post("/coding-gateway/v1/messages", json={"model": "x"}, headers=headers)
            assert r.status_code == 401, headers
        # the three actions are offered to the assistant, and say what to set up
        ids = {a.id for a in services.actions.registry}
        want = {"code.session.start", "code.session.send", "code.session.stop", "code.session.undo"}
        assert want <= ids
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


async def test_a_file_is_found_by_part_of_its_name_without_leaving_the_project(box, tmp_path):
    (box.project / "node_modules" / "left-pad").mkdir(parents=True)
    (box.project / "node_modules" / "left-pad" / "prices.js").write_text("x")
    (box.project / "PRICES.md").write_text("# prices")
    (tmp_path / "outside-prices.txt").write_text("x")
    (box.project / "out").symlink_to(tmp_path)
    made = await started(box)
    url = f"{BASE}/sessions/{made['id']}/files/find"
    found = (await box.http.get(url, params={"q": "price"})).json()
    assert [e["path"] for e in found["entries"]] == ["PRICES.md", "shop/prices.py"]
    assert found["more"] is False
    assert (await box.http.get(url, params={"q": "nothing-like-this"})).json()["entries"] == []
    assert (await box.http.get(url, params={"q": ""})).status_code == 422


async def test_the_limit_of_a_session_can_be_changed_and_holds_at_the_gateway(box):
    made = await started(box)
    assert made["cost_limit_usd"] == 5.0 and made["model_calls"] == 0  # the usual limit, said
    url = f"{BASE}/sessions/{made['id']}"
    changed = await box.http.patch(url, json={"cost_limit_usd": 8})
    assert changed.status_code == 200 and changed.json()["cost_limit_usd"] == 8.0
    assert box.store.get_session(_owner(), made["id"])["cost_limit_usd"] == 8.0
    await box.http.post(f"{url}/messages", json={"text": "Analyse this codebase."})
    await ended(box, made["id"])
    assert box.gateway.spent(made["id"])["limit_usd"] == 8.0  # the session was opened with it
    await box.http.patch(url, json={"cost_limit_usd": 12.5})
    assert box.gateway.spent(made["id"])["limit_usd"] == 12.5  # and a later change reaches it
    for bad in ({"cost_limit_usd": 0}, {"cost_limit_usd": 1000}, {"title": "x"}):
        assert (await box.http.patch(url, json=bad)).status_code == 422
    assert (
        await box.http.patch(f"{BASE}/sessions/nobody", json={"cost_limit_usd": 3})
    ).status_code == 404


async def test_a_session_says_what_it_is_counted_in_and_its_limit_in_tokens_can_be_changed(box):
    made = await started(box)
    # a model with a known price is counted in dollars; the usual limit in tokens is said too
    assert made["counted_in"] == "usd" and made["token_limit"] == 3_000_000
    url = f"{BASE}/sessions/{made['id']}"
    changed = await box.http.patch(url, json={"token_limit": 4_000_000})
    assert changed.status_code == 200 and changed.json()["token_limit"] == 4_000_000
    assert box.store.get_session(_owner(), made["id"])["token_limit"] == 4_000_000
    for bad in ({"token_limit": 0}, {"token_limit": 10**10}, {"token_limit": 1.5}):
        assert (await box.http.patch(url, json=bad)).status_code == 422


# ---- a session that changes files (stage C2), through the routes -------------------------------


async def card_of(box: Box, session_id: str, seconds: float = 20.0) -> dict:
    """Wait until the session's turn waits for the person, and give the card's event."""
    feed = box.services.code_sessions.feed(session_id)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        view = (await box.http.get(f"{BASE}/sessions/{session_id}")).json()
        cards = [e for e in feed.kept if e["event"] == "interrupt"]
        if view["waiting"] and cards:
            return cards[-1]
        await asyncio.sleep(0.05)
    raise AssertionError("no card came")


def site(box: Box) -> None:
    """The files the recorded edit turn was made on."""
    (box.project / "src").mkdir()
    (box.project / "src" / "home.html").write_text("<h1>Bakery</h1>\n<p>Welcome</p>\n")


async def test_a_turn_that_edits_runs_to_its_end_and_its_changes_are_listed_and_undone(box):
    site(box)
    made = await started(box, mode="own")
    assert made["mode"] == "own" and made["waiting"] is False
    url = f"{BASE}/sessions/{made['id']}"
    r = await box.http.post(f"{url}/messages", json={"text": "Add the hours. #replay:edit-asked"})
    assert r.status_code == 202
    seen = await ended(box, made["id"])
    assert seen["ended"] == "finished" and seen["answer"] == "The hours are on the home page."
    # the fake replays the steps and writes nothing: the folders a new file needs were made by
    # the place when it let the "create" through
    assert (box.project / "tests").is_dir()
    # every change waited in the engine and was let through at once: nobody was asked
    feed = box.services.code_sessions.feed(made["id"])
    assert not [e for e in feed.kept if e["event"] == "interrupt"]
    asked = await box.made_with(box.store.get_session(_owner(), made["id"])["place_session"])
    assert asked["security_analyzer"]["kind"] == "WasifyRules"
    # the Changes tab's routes (the replay changed no file, so the turn is not among them)
    assert (await box.http.get(f"{url}/changes")).json() == {"items": []}
    (turn_row,) = (await box.http.get(f"{url}/turns")).json()["items"]
    assert turn_row["changed"] == 0 and not turn_row["can_undo"] and not turn_row["undone"]
    r = await box.http.post(f"{url}/turns/{turn_row['id']}/undo")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_last"
    assert (await box.http.get(f"{url}/changes/{turn_row['id']}/file?path=a")).status_code == 404
    # the checkpoints are in the app's data, which the sandbox closes, and not in the project
    workspace = box.store.list_workspaces(_owner())[0]
    assert (box.data / "code" / "checkpoints" / workspace["id"] / "HEAD").is_file()
    assert not (box.project / ".git").exists()


async def test_a_change_undo_cannot_put_back_is_asked_and_answered_through_the_routes(box):
    site(box)
    (box.project / ".gitignore").write_text("src/\n")  # the recorded turn edits src/home.html
    made = await started(box, mode="ask")
    url = f"{BASE}/sessions/{made['id']}"
    project = (await box.http.get(f"{url}/project")).json()
    assert project["mode"] == "ask" and [k["id"] for k in project["kinds"]] == [
        "not_undoable",
        "delete",
        "install",
        "make",
    ]
    await box.http.post(f"{url}/messages", json={"text": "#replay:edit-asked"})
    card = await card_of(box, made["id"])
    assert card["kind"] == "code_ask" and card["payload"]["ask"] == "not_undoable"
    assert (
        card["payload"]["path"] == "src/home.html" and card["payload"]["command"] == "str_replace"
    )
    assert (await box.http.get(url)).json()["working"]
    # a wrong answer and a wrong card are refused in words
    assert (
        await box.http.post(f"{url}/asks/{card['interrupt_id']}", json={"answer": "maybe"})
    ).status_code == 422
    r = await box.http.post(f"{url}/asks/nothing", json={"answer": "yes"})
    assert r.status_code == 200 and r.json()["answered"] is False
    # "Allow for this project": it runs, and the next change of that kind does not ask
    r = await box.http.post(f"{url}/asks/{card['interrupt_id']}", json={"answer": "allow"})
    assert r.json()["answered"] is True
    seen = await ended(box, made["id"])
    assert seen["ended"] == "finished"
    feed = box.services.code_sessions.feed(made["id"])
    assert len([e for e in feed.kept if e["event"] == "interrupt"]) == 1
    answers = [e["output"].get("answer") for e in feed.kept if e["event"] == "tool_result"]
    assert answers == [None, "allow", None]  # looking; the ignored file; a file Undo knows
    # the card, its answer and the count of changed files are events the SSE contract knows
    from pydantic import TypeAdapter
    from wasifyai_contracts.events import SseEvent

    for event in feed.kept:
        TypeAdapter(SseEvent).validate_python(event)
    assert feed.kept[-1]["state"] == "done" and feed.kept[-1]["changed"] == 0
    assert (await box.http.get(f"{url}/project")).json()["kinds"][0]["allowed"] is True
    # taken back in "What this project may do"
    r = await box.http.put(f"{url}/project/allowed/not_undoable", json={"allowed": False})
    assert r.json()["kinds"][0]["allowed"] is False
    assert (
        await box.http.put(f"{url}/project/allowed/nothing", json={"allowed": True})
    ).status_code == 422


async def test_a_no_and_a_stop_while_the_card_waits_through_the_routes(box):
    site(box)
    (box.project / ".gitignore").write_text("secret.txt\nsrc/\n")
    made = await started(box, mode="ask")
    url = f"{BASE}/sessions/{made['id']}"
    await box.http.post(f"{url}/messages", json={"text": "#replay:edit-refused"})
    card = await card_of(box, made["id"])
    assert card["payload"]["path"] == "secret.txt"
    await box.http.post(f"{url}/asks/{card['interrupt_id']}", json={"answer": "no"})
    seen = await ended(box, made["id"])
    assert seen["ended"] == "finished" and seen["answer"] == "I left it."
    feed = box.services.code_sessions.feed(made["id"])
    (result,) = [e for e in feed.kept if e["event"] == "tool_result"]
    assert result["status"] == "refused" and result["output"]["answer"] == "no"
    # Stop while a card waits: the turn ends as stopped, within a second
    await box.http.post(f"{url}/messages", json={"text": "#replay:edit-asked"})
    await card_of(box, made["id"])
    began = time.monotonic()
    r = await box.http.post(f"{url}/stop")
    assert r.json()["stopped"] is True and time.monotonic() - began < 1.5
    seen = (await box.http.get(url)).json()
    assert seen["ended"] == "stopped" and not seen["working"] and not seen["waiting"]
    # the mode is changed through the same route as the limit
    r = await box.http.patch(url, json={"mode": "plan"})
    assert r.status_code == 200 and r.json()["mode"] == "plan"
    assert (await box.http.patch(url, json={"mode": "everything"})).status_code == 422


# ---- the check and the person's terminal (stage C3) ------------------------------------------------


async def test_the_check_is_read_set_run_and_read_again_through_the_routes(box):
    made = await started(box, mode="ask")
    url = f"{BASE}/sessions/{made['id']}"
    (box.project / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    seen = (await box.http.get(f"{url}/check")).json()
    assert seen["command"] == "" and seen["rounds"] == 3 and seen["limit_s"] == 600
    assert [s["command"] for s in seen["suggested"]] == ["python3 -m pytest"]
    # nothing to run yet
    assert (await box.http.post(f"{url}/check/run")).status_code == 409
    put = await box.http.put(
        f"{url}/check", json={"command": "echo checked; exit 4", "limit_s": 60}
    )
    assert put.status_code == 200 and put.json()["source"] == "person"
    assert (
        await box.http.put(f"{url}/check", json={"command": "x", "limit_s": 1})
    ).status_code == 422
    ran = (await box.http.post(f"{url}/check/run")).json()
    assert (ran["check"]["result"], ran["check"]["exit_code"]) == ("failed", 4)
    assert ran["session"]["result"] == "failed" and ran["session"]["check_command"].startswith(
        "echo"
    )
    assert "output_file" not in ran["check"]
    whole = (await box.http.get(f"{url}/checks/{ran['check']['id']}")).json()
    assert whole["output"] == "checked\n" and whole["cut"] is False
    assert (await box.http.get(f"{url}/checks/nothing")).status_code == 404
    # another person's session is not found
    other = RouteDeps(box.services, lambda: Identity("t1", "someone-else"))
    app = FastAPI()
    app.include_router(build_routes(other), prefix="/products/wasifyai-code")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as theirs:
        assert (await theirs.get(f"{url}/check")).status_code == 404
        assert (await theirs.post(f"{url}/terminals", json={})).status_code == 404
    # the stream said it: checking, the check, done with the word
    kept = [e for e in box.services.code_sessions.feed(made["id"]).kept]
    assert [e["event"] for e in kept] == ["code_state", "code_check", "code_state"]
    assert (
        kept[1]["round"] == 0 and kept[1]["tail"] == "checked\n" and kept[2]["result"] == "failed"
    )


async def test_no_terminal_is_opened_where_there_is_no_sandbox(box):
    """These tests run the supervisor without `sandbox-exec`. A shell of the person's is never
    started outside a sandbox, so here it is refused; the real one is in the integration tests."""
    made = await started(box, mode="ask")
    url = f"{BASE}/sessions/{made['id']}"
    assert (await box.http.get(f"{url}/terminals")).json() == {"items": []}
    refused = await box.http.post(f"{url}/terminals", json={"cols": 80, "rows": 24})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "no_sandbox"
    assert (await box.http.post(f"{url}/terminals", json={"cols": 1})).status_code == 422
    for call in (
        box.http.get(f"{url}/terminals/none/events"),
        box.http.post(f"{url}/terminals/none/input", json={"data": "x"}),
        box.http.post(f"{url}/terminals/none/size", json={"cols": 80, "rows": 24}),
    ):
        assert (await call).status_code == 404
    assert (await box.http.delete(f"{url}/terminals/none")).status_code == 204


# ---- extensions (stage X2) ---------------------------------------------------------------------------


async def test_extensions_are_listed_switched_added_and_removed_through_the_routes(box, tmp_path):
    made = await started(box)
    (project,) = (await box.http.get(f"{BASE}/workspaces")).json()["items"]
    assert project["name"] == "bakery-site"
    listed = (await box.http.get(f"{BASE}/extensions?workspace_id={project['id']}")).json()["items"]
    assert listed[0]["id"] == "own:explain-in-plain-words" and listed[0]["on"] is True
    assert all(e["kind"] == "skill" and e["source"] in ("own", "catalogue") for e in listed)
    assert (await box.http.get(f"{BASE}/extensions?workspace_id=nothing")).status_code == 404
    one = (await box.http.get(f"{BASE}/extensions/own:write-the-tests-first")).json()
    assert (
        one["text"].startswith("---\nname: write-the-tests-first")
        and one["where"][0]["on"] is False
    )
    assert (await box.http.get(f"{BASE}/extensions/own:nothing")).status_code == 404
    url = f"{BASE}/extensions/own:write-the-tests-first/on"
    r = await box.http.put(url, json={"workspace_id": project["id"], "on": True})
    assert r.status_code == 200 and r.json()["on"] is True
    assert (
        await box.http.put(url, json={"workspace_id": "nothing", "on": True})
    ).status_code == 404
    # a session of the project is started with the skills that are on
    await box.http.post(
        f"{BASE}/sessions/{made['id']}/messages", json={"text": "Analyse this codebase."}
    )
    await ended(box, made["id"])
    conversation = box.store.get_session(owner_of(ME), made["id"])["place_session"]
    given = (await box.made_with(conversation))["agent_settings"]["agent_context"]["skills"]
    assert [s["name"] for s in given] == [
        "explain-in-plain-words", "pictures-with-wasify", "write-the-tests-first",
    ]  # fmt: skip
    assert all(s["content"] and s["is_agentskills_format"] for s in given)
    # a folder of the person's
    mine = tmp_path / "house-style"
    mine.mkdir()
    (mine / "SKILL.md").write_text(
        "---\nname: house-style\ndescription: How pages are worded.\n---\nShort sentences.\n"
    )
    seen = await box.http.post(f"{BASE}/extensions/look", json={"folder": str(mine)})
    assert seen.status_code == 200 and seen.json()["brings"] == "text"
    assert (
        await box.http.post(f"{BASE}/extensions/look", json={"folder": str(tmp_path)})
    ).status_code == 422
    added = await box.http.post(
        f"{BASE}/extensions", json={"folder": str(mine), "workspace_id": project["id"]}
    )
    assert added.status_code == 201 and added.json()["on"] is True
    item = added.json()["id"].split(":")[1]
    only = (await box.http.get(f"{BASE}/extensions?ids={item}")).json()["items"]
    assert [e["id"] for e in only] == [added.json()["id"]] and only[0]["added_at"]
    # somebody else sees the short list and nothing of this person's
    theirs = RouteDeps(box.services, lambda: Identity("t1", "someone-else"))
    app = FastAPI()
    app.include_router(build_routes(theirs), prefix="/products/wasifyai-code")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as other:
        ids = [e["id"] for e in (await other.get(f"{BASE}/extensions")).json()["items"]]
        assert added.json()["id"] not in ids and "own:explain-in-plain-words" in ids
        assert (await other.get(f"{BASE}/extensions/{added.json()['id']}")).status_code == 404
        assert (await other.get(f"{BASE}/workspaces")).json() == {"items": []}
    assert (
        await box.http.delete(f"{BASE}/extensions/own:explain-in-plain-words")
    ).status_code == 403
    assert (await box.http.delete(f"{BASE}/extensions/{added.json()['id']}")).status_code == 204
    assert (await box.http.get(f"{BASE}/extensions?ids={item}")).json() == {"items": []}


# ---- plugins (stage X3) and scheduled runs (stage C6) ------------------------------------------------


async def test_a_plugin_is_approved_through_its_own_route_and_only_then_switched_on(box, tmp_path):
    await started(box)
    (project,) = (await box.http.get(f"{BASE}/workspaces")).json()["items"]
    folder = tmp_path / "work-log"
    (folder / ".plugin").mkdir(parents=True)
    (folder / ".plugin" / "plugin.json").write_text(
        json.dumps({"name": "work-log", "description": "Keeps a log of the work."})
    )
    (folder / "hooks").mkdir()
    hooks = {"PostToolUse": [{"matcher": "*", "hooks": [{"command": "date >> log.txt"}]}]}
    (folder / "hooks" / "hooks.json").write_text(json.dumps({"hooks": hooks}))
    seen = (await box.http.post(f"{BASE}/extensions/look", json={"folder": str(folder)})).json()
    assert seen["kind"] == "plugin" and seen["brings"]["hooks"][0]["command"] == "date >> log.txt"
    added = await box.http.post(
        f"{BASE}/extensions", json={"folder": str(folder), "workspace_id": project["id"]}
    )
    assert added.status_code == 201 and added.json()["on"] is False
    url = f"{BASE}/extensions/{added.json()['id']}"
    on = {"workspace_id": project["id"], "on": True}
    refused = await box.http.put(f"{url}/on", json=on)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "needs_approval"
    assert (await box.http.post(f"{BASE}/extensions/own:nothing/approve")).status_code == 404
    approved = await box.http.post(f"{url}/approve")
    assert approved.status_code == 200 and approved.json()["approved"] is True
    assert (await box.http.put(f"{url}/on", json=on)).json()["on"] is True


async def test_a_schedule_is_made_from_a_template_run_now_and_let_go_through_the_routes(box):
    site(box)
    await started(box, mode="own")
    (project,) = (await box.http.get(f"{BASE}/workspaces")).json()["items"]
    templates = (await box.http.get(f"{BASE}/schedules/templates")).json()["items"]
    nightly = next(t for t in templates if t["id"] == "nightly-check")
    assert nightly["rule_words"] == "Every day at 02:00"
    body = {
        "workspace_id": project["id"], "request": "Add the hours. #replay:edit-asked",
        "rule": nightly["rule"], "title": nightly["title"], "model": "this-computer",
    }  # fmt: skip
    for bad, code in (
        ({"rule": {"kind": "every", "minutes": 1}}, "bad_rule"),
        ({"workspace_id": "nothing"}, "not_found"),
        ({"model": "no-such-model"}, "no_such_model"),
    ):
        r = await box.http.post(f"{BASE}/schedules", json=body | bad)
        assert r.status_code in (404, 422) and r.json()["detail"]["code"] == code, r.text
    made = await box.http.post(f"{BASE}/schedules", json=body)
    assert made.status_code == 201, made.text
    schedule = made.json()
    assert schedule["title"] == "Check it every night" and schedule["next_due"]
    assert schedule["project"] == "bakery-site" and schedule["enabled"] is True
    listed = (await box.http.get(f"{BASE}/schedules")).json()
    assert [s["id"] for s in listed["items"]] == [schedule["id"]] and listed["time_zone"]
    url = f"{BASE}/schedules/{schedule['id']}"
    run = await box.http.post(f"{url}/run")
    assert run.status_code == 202 and run.json()["state"] == "waiting"
    deadline = time.monotonic() + 30
    latest: dict = {}
    while time.monotonic() < deadline:
        (latest,) = (await box.http.get(url)).json()["runs"]
        if latest["state"] not in ("waiting", "running"):
            break
        await asyncio.sleep(0.05)
    assert latest["state"] == "done" and latest["open"] is True, latest
    # the run's session is a scheduled run's, on a copy inside the coding engine's own folder,
    # and the copy is not one of the person's projects
    session = (await box.http.get(f"{BASE}/sessions/{latest['session_id']}")).json()
    assert session["scheduled_run"] is True and session["mode"] == "own"
    assert [w["id"] for w in (await box.http.get(f"{BASE}/workspaces")).json()["items"]] == [
        project["id"]
    ]
    copies = Path(box.server.run_dir) / "copies" / latest["id"]
    assert (copies / "bakery-site" / "src" / "home.html").is_file()
    runs = f"{BASE}/schedules/runs/{latest['id']}"
    assert (await box.http.get(f"{runs}/changes")).json()["files"] == []
    gone = await box.http.post(f"{runs}/discard")
    assert gone.status_code == 200 and gone.json()["open"] is False and not copies.exists()
    again = await box.http.post(f"{runs}/apply")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "no_copy"
    # paused: no next time; another person sees nothing of it; deleted: gone
    paused = await box.http.patch(url, json={"enabled": False})
    assert paused.json()["enabled"] is False and paused.json()["next_due"] is None
    other = RouteDeps(box.services, lambda: Identity("t1", "someone-else"))
    app = FastAPI()
    app.include_router(build_routes(other), prefix="/products/wasifyai-code")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as theirs:
        assert (await theirs.get(f"{BASE}/schedules")).json()["items"] == []
        assert (await theirs.get(url)).status_code == 404
        assert (await theirs.post(f"{runs}/discard")).status_code == 404
    assert (await box.http.delete(url)).status_code == 204
    assert (await box.http.get(url)).status_code == 404
