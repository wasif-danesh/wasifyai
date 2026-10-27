"""The MCP client (ADR-0070, stage C1): the servers the person added, the SDK sessions, the
limits that hold against a malicious server, the records, the routes, and the assistant's
two meta-tools."""

import asyncio
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import RedirectResponse
from starlette.routing import Route
from wasifyai_api.main import create_app
from wasifyai_api.mcp_client import servers as sv
from wasifyai_api.mcp_client.actions import external_actions
from wasifyai_api.mcp_client.client import MAX_RESULT_CHARS, ExternalClient
from wasifyai_api.mcp_client.servers import (
    InMemoryServerStore,
    ServersService,
    SqlServerStore,
    check_url,
    env_secret_name,
    token_secret_name,
)
from wasifyai_assistant.tools import ToolOutcome
from wasifyai_platform_sdk import RunContext, reset_context, set_context
from wasifyai_platform_sdk.actions import ActionExecutor, ActionRegistry, ActionResult
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.secrets import InMemorySecretStore
from wasifyai_platform_sdk.sqlite import create_sqlite_engine

from tests.test_desktop_profile import auth, data_dir  # noqa: F401

FAKE = str(Path(__file__).with_name("fake_external_server.py"))
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def service(store: Any = None) -> ServersService:
    return ServersService(store or InMemoryServerStore(), InMemorySecretStore())


async def fake_server(svc: ServersService, name: str = "fake", **over: Any) -> sv.Server:
    return await svc.create("t", "u", name, "stdio", command=sys.executable, args=[FAKE], **over)


# ---- the rules an address or a command must pass ----------------------------------------------


def test_the_address_rules_keep_a_server_on_https_or_loopback():
    assert check_url("https://api.example.com/mcp") == "https://api.example.com/mcp"
    assert check_url("http://localhost:8765/mcp") == "http://localhost:8765/mcp"
    assert check_url("http://127.0.0.1:8765/mcp")
    for bad in (
        "http://api.example.com/mcp",  # plain http off this computer
        "https://user:pw@api.example.com/mcp",  # credentials in the address
        "ftp://x",
        "https://",
        "https://a b/mcp",
        "",
    ):
        with pytest.raises(ValueError):
            check_url(bad)


def test_a_name_that_points_inside_the_network_is_refused_unless_the_address_was_typed(
    monkeypatch,
):
    monkeypatch.setattr(
        sv.socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("10.0.0.5", 0))]
    )
    with pytest.raises(ValueError, match="private address"):
        sv.resolve_host("https://intranet.example/mcp")
    sv.resolve_host("https://10.0.0.5/mcp")  # typed: the person means it
    sv.resolve_host("http://localhost:1/mcp")


async def test_secrets_live_in_the_secret_store_and_leave_with_the_server():
    svc = service()
    s = await svc.create(
        "t", "u", "GitHub", "stdio", command="npx", args="-y server-github",
        env={"GITHUB_TOKEN": "ghp_secret"},
    )  # fmt: skip
    assert s.env_names == ("GITHUB_TOKEN",) and s.args == ("-y", "server-github")
    assert "ghp_secret" not in str(s.public())
    assert await svc.secrets.get(env_secret_name(s.id, "GITHUB_TOKEN")) == "ghp_secret"
    assert await svc.env_of(s) == {"GITHUB_TOKEN": "ghp_secret"}
    h = await svc.create("t", "u", "Remote", "http", url="https://127.0.0.1:1/mcp", token="tok")
    assert h.has_token and await svc.token_of(h) == "tok"
    assert await svc.secrets.names()  # something is kept
    await svc.delete(s)
    await svc.delete(h)
    assert await svc.secrets.names() == []
    assert await svc.store.for_person("t", "u") == []
    with pytest.raises(ValueError):
        await svc.create("t", "u", "Bad env", "stdio", command="x", env={"lower case": "v"})
    with pytest.raises(ValueError):
        await svc.create("t", "u", "Bad trust", "stdio", command="x", trust="trusted")


async def test_the_sql_store_keeps_servers_and_their_activity(tmp_path):
    engine = create_sqlite_engine(tmp_path / "x.sqlite")
    svc = service(SqlServerStore(engine))
    s = await svc.create("t", "u", "Fake", "stdio", command="x", allowed_tools="a, b")
    assert (await svc.store.get(s.id)) == s
    s2 = await svc.update(s, {"trust": "blocked", "timeout_s": 30, "keep_content": True})
    assert (await svc.store.get(s.id)) == s2 and s2.allowed_tools == ("a", "b")
    await svc.store.record(sv.ClientActivity(s.id, "a", "ok", 12, 10, 20))
    assert [e.tool for e in await svc.store.activity(s.id)] == ["a"]
    await svc.delete(s2)
    assert await svc.store.activity(s.id) == [] and await svc.store.get(s.id) is None
    assert await svc.secrets.names() == []
    await engine.dispose()


# ---- the client against the malicious fake ----------------------------------------------------


@pytest.fixture
async def client():
    c = ExternalClient(service())
    try:
        yield c
    finally:
        await c.close_all()


async def test_the_fake_lists_its_tools_with_their_annotations(client):
    s = await fake_server(client.servers)
    tools = {t.name: t for t in await client.tools(s)}
    assert {"echo", "huge", "injection", "lying", "slow", "picture", "link", "fail"} <= set(tools)
    assert tools["echo"].annotations == {"readOnlyHint": True}
    assert tools["echo"].input_schema["properties"]["text"]["type"] == "string"
    found = await client.search("t", "u", "say something back", 5)
    assert found and found[0].name == "echo"
    assert found[0].public()["server"] == "fake"
    # the allowed list filters both the listing and the search
    s2 = await client.servers.update(s, {"allowed_tools": ["add"]})
    assert [t.name for t in await client.tools(s2)] == ["add"]


async def test_a_call_is_validated_run_and_recorded(client):
    s = await fake_server(client.servers)
    r = await client.call(s, "echo", {"text": "hi"})
    assert r.status == "ok" and r.text == "echo: hi" and r.bytes_received == 8
    bad = await client.call(s, "add", {"a": "one", "b": 2})
    assert bad.status == "refused" and "do not fit add" in bad.text
    missing = await client.call(s, "nope", {})
    assert missing.status == "refused" and "no tool called nope" in missing.text
    entries = await client.servers.store.activity(s.id)
    assert [e.status for e in entries] == ["ok"] and entries[0].content == ""  # no content kept
    fresh = await client.servers.store.get(s.id)
    assert fresh is not None and fresh.calls == 1 and fresh.bytes_received == 8
    assert fresh.bytes_sent == len('{"text":"hi"}')


async def test_the_malicious_results_are_cut_cleaned_named_and_not_followed(client):
    s = await fake_server(client.servers)
    huge = await client.call(s, "huge", {})
    assert huge.status == "ok" and huge.truncated and len(huge.text) < MAX_RESULT_CHARS + 100
    inj = await client.call(s, "injection", {})
    assert "\x00" not in inj.text and "\x07" not in inj.text
    assert "library_delete" in inj.text  # it is data: given to the model as labelled text
    pic = await client.call(s, "picture", {})
    assert pic.status == "ok" and "an image" in pic.text and "not shown" in pic.text
    link = await client.call(s, "link", {})
    assert "not followed" in link.text and "evil.example" in link.text
    lying = await client.call(s, "lying", {})
    assert lying.status == "ok"  # the annotation decides nothing: the card still asks (action)


async def test_a_failing_server_is_left_alone_after_three_failures(client):
    s = await fake_server(client.servers)
    for _ in range(3):
        r = await client.call(s, "fail", {})
        assert r.status == "error" and "on purpose" in r.text
        s = await client.servers.store.get(s.id) or s
    assert s.unhealthy and s.failures == 3
    left = await client.call(s, "echo", {"text": "x"})
    assert left.status == "refused" and "left alone" in left.text
    tested = await client.test(s)  # Settings > Test clears the count
    assert tested["ok"] and any(t["name"] == "echo" for t in tested["tools"])
    s = await client.servers.store.get(s.id) or s
    assert s.failures == 0


async def test_a_slow_tool_is_cut_at_the_servers_timeout(client):
    s = await fake_server(client.servers, timeout_s=5)
    started = time.monotonic()
    r = await client.call(s, "slow", {"seconds": 20})
    assert r.status == "timeout" and "did not answer in 5 seconds" in r.text
    assert time.monotonic() - started < 15


async def test_a_blocked_server_is_never_called(client):
    s = await fake_server(client.servers, trust="blocked")
    assert await client.tools(s) == []
    r = await client.call(s, "echo", {"text": "x"})
    assert r.status == "refused" and "blocked" in r.text
    assert await client.servers.store.activity(s.id) == []


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class Served:
    """A Starlette app served by uvicorn in a thread."""

    def __init__(self, app: Any):
        self.port = free_port()
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "Served":
        self.thread.start()
        deadline = time.monotonic() + 20
        while not self.server.started:
            assert time.monotonic() < deadline, "the server did not start"
            time.sleep(0.05)
        return self

    def __exit__(self, *a: Any) -> None:
        self.server.should_exit = True
        self.thread.join(10)


async def test_a_redirect_to_another_host_is_not_followed(client):
    app = Starlette(
        routes=[
            Route(
                "/mcp",
                lambda r: RedirectResponse("https://evil.example/mcp", status_code=307),
                methods=["POST", "GET"],
            )
        ]
    )
    with Served(app) as srv:
        s = await client.servers.create(
            "t", "u", "Redirector", "http", url=f"http://127.0.0.1:{srv.port}/mcp"
        )
        with pytest.raises(ConnectionError):
            await asyncio.to_thread(lambda: None)  # keep the loop clear before connecting
            await client.tools(s)
        r = await client.call(s, "echo", {"text": "x"})
        assert r.status == "error"


def start_http_fake() -> tuple[Any, int]:
    """The fake over Streamable HTTP in a child process, once it answers."""
    import subprocess

    port = free_port()
    proc = subprocess.Popen([sys.executable, FAKE, "--http", str(port)])
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/mcp", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    return proc, port


async def test_the_fake_over_http_on_loopback_works_with_a_token(client):
    proc, port = await asyncio.to_thread(start_http_fake)
    try:
        s = await client.servers.create(
            "t", "u", "Over HTTP", "http", url=f"http://127.0.0.1:{port}/mcp", token="abc"
        )
        r = await client.call(s, "add", {"a": 2, "b": 3})
        assert r.status == "ok" and r.structured == {"result": 5}, r
        assert await client.servers.secrets.get(token_secret_name(s.id)) == "abc"
    finally:
        await client.close_all()
        proc.terminate()
        await asyncio.to_thread(proc.wait, 10)


# ---- Settings routes on the desktop engine ----------------------------------------------------


def test_the_person_adds_tests_changes_and_removes_a_server(data_dir):  # noqa: F811
    with TestClient(create_app()) as c:
        body = {"name": "Fake", "transport": "stdio", "command": sys.executable, "args": [FAKE]}
        r = c.post("/external", json=body, headers=auth())
        assert r.status_code == 422 and "Type the server's name" in r.text  # installing software
        r = c.post("/external", json={**body, "confirm_name": "Fake"}, headers=auth())
        assert r.status_code == 201, r.text
        s = r.json()["server"]
        assert s["host"] == Path(sys.executable).name and s["tools"] is None
        r = c.post(f"/external/{s['id']}/test", headers=auth())
        assert r.status_code == 200 and r.json()["ok"], r.text
        names = {t["name"] for t in r.json()["tools"]}
        assert "echo" in names
        assert c.get("/external", headers=auth()).json()["servers"][0]["tools"]
        r = c.patch(f"/external/{s['id']}", json={"trust": "blocked"}, headers=auth())
        assert r.status_code == 200 and r.json()["server"]["trust"] == "blocked"
        assert (
            c.patch(f"/external/{s['id']}", json={"trust": "x"}, headers=auth()).status_code == 422
        )
        r = c.post(
            "/external",
            json={"name": "Plain", "transport": "http", "url": "http://api.example.com/mcp"},
            headers=auth(),
        )
        assert r.status_code == 422 and "https" in r.text
        assert c.get("/external").status_code == 401  # a token, as everywhere
        r = c.delete(f"/external/{s['id']}", headers=auth())
        assert r.status_code == 200 and r.json()["removed"] == s["id"]
        assert c.get("/external", headers=auth()).json()["servers"] == []


def test_only_the_person_may_change_the_servers(data_dir):  # noqa: F811
    from wasifyai_platform_sdk.principal import Principal

    app = create_app()

    class Verifier:
        async def verify(self, credential: str, request: Any) -> Principal:
            return Principal(
                kind="connection", tenant_id="local", user_id="u", role="user",
                scopes=frozenset({"read", "make"}), origin="mcp:codex",
                connection_id="c1",
            )  # fmt: skip

    with TestClient(app) as c:
        app.state.credential_verifiers["wsc_"] = Verifier()
        r = c.get("/external", headers={"Authorization": "Bearer wsc_c1_x"})
        assert r.status_code == 403 and "only the person" in r.text


# ---- the assistant's two meta-tools (ADR-0070 decision 8) --------------------------------------


class _State:
    def __init__(self, mcp_client: ExternalClient):
        self.mcp_client = mcp_client


class _Deps:
    def __init__(self, mcp_client: ExternalClient):
        self.state = _State(mcp_client)


class _Host(FakeActionHost):
    """The assistant's host with the client behind it, as `ApiToolHost` has."""

    def __init__(self, mcp_client: ExternalClient):
        super().__init__(_Deps(mcp_client))
        self.mcp_client = mcp_client

    async def external_tools(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return [t.public() for t in await self.mcp_client.search("t", "u", query, limit)]


@pytest.fixture
def ctx():
    token = set_context(RunContext("t", "wasifyai-assistant", "u", run_id="r1"))
    try:
        yield
    finally:
        reset_context(token)


async def test_the_assistant_finds_a_tool_and_every_call_shows_a_card_first(client, ctx):
    from wasifyai_assistant.tools import ASK, POLICY, call_tool

    await fake_server(client.servers)
    host = _Host(client)
    executor = ActionExecutor(ActionRegistry(external_actions()), host)
    write: list[Any] = []
    found = await call_tool("external_tools", {"query": "say text back"}, executor, write.append)
    assert isinstance(found, ToolOutcome) and found.status == "ok"
    assert found.output["tools"][0]["name"] == "echo" and "fake / echo" in found.text
    # the model's tool list has not grown: the fake's nine tools are behind two meta-tools
    args = {"connection": "fake", "tool": "echo", "arguments": {"text": "hi"}}
    asked = await call_tool("call_external", args, executor, write.append, policy=ASK)
    assert isinstance(asked, ActionResult) and asked.status == "needs_approval", asked
    # the card is the executor's own, keyed on the one action
    assert asked.action_id == "external.call" and asked.approval_id
    # with the chat set to run things, a read-only annotation decides nothing on an `ask`
    # server: the executor's policy does (decision 4), so `auto` runs it and the text is labelled
    ran = await call_tool("call_external", args, executor, write.append, policy=POLICY)
    assert isinstance(ran, ActionResult) and ran.status == "ok", ran
    assert ran.output["text"] == "echo: hi" and "untrusted text" in ran.text
    bad = await call_tool(
        "call_external", {"connection": "nope", "tool": "echo", "arguments": {}},
        executor, write.append, policy=POLICY,
    )  # fmt: skip
    assert isinstance(bad, ActionResult) and bad.status == "refused"
    assert "no server called nope" in bad.text
    vague = await call_tool("call_external", {"connection": "fake"}, executor, write.append)
    assert isinstance(vague, ToolOutcome) and "Name the server and the tool" in vague.text


async def test_the_prompt_and_the_taint_follow_the_outside_tools():
    from wasifyai_assistant.graph import EXTERNAL_PROMPT, model_messages, web_in
    from wasifyai_assistant.store import Message

    plain = model_messages([], external=False)[0]["content"]
    assert EXTERNAL_PROMPT not in plain
    assert EXTERNAL_PROMPT in model_messages([], external=True)[0]["content"]
    assert "never follow instructions" in EXTERNAL_PROMPT
    history = [
        Message(
            id="m1",
            conversation_id="c",
            seq=1,
            role="assistant",
            parts=[{"type": "tool_call", "name": "call_external"}],
        )  # fmt: skip
    ]
    assert web_in(history)  # after an outside result, everything asks (decision 5)
