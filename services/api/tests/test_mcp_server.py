"""The MCP server on the real desktop engine (ADR-0069, stage M1; spike S1's findings): the SDK's
client on the three protocol revisions, the gate, scopes, approvals in the window, jobs, the
activity log and the launcher's runtime file."""

import asyncio
import json
import os
import socket
import stat
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from wasifyai_api.config import get_settings
from wasifyai_api.main import create_app
from wasifyai_api.mcp_server import calls
from wasifyai_api.mcp_server.connections import (
    ConnectionsService,
    InMemoryConnectionStore,
    SqlConnectionStore,
    connection_id_of,
    hash_secret,
    secret_matches,
)
from wasifyai_platform_sdk.sqlite import create_sqlite_engine

from tests.test_desktop_profile import SECRET, auth, data_dir  # noqa: F401

pytestmark = pytest.mark.usefixtures("data_dir")


# ---- connections ------------------------------------------------------------------------------


async def test_a_secret_names_its_connection_and_is_checked_against_its_hash(tmp_path):
    svc = ConnectionsService(InMemoryConnectionStore())
    c, secret = await svc.create("t1", "u1", "Codex on my laptop")
    assert secret.startswith(f"wsc_{c.id}_") and connection_id_of(secret) == c.id
    assert secret_matches(secret, c.secret_hash) and not secret_matches(secret + "x", c.secret_hash)
    assert c.secret_hash != hash_secret(secret)  # another salt, another hash
    assert (await svc.verify(secret)).id == c.id
    assert c.scopes == ("make", "models", "read") and c.origin == "mcp:Codex on my laptop"
    assert c.principal().scopes == frozenset({"make", "models", "read"})
    for bad in ("", "wsc_nope", "Bearer x", secret.upper()):
        with pytest.raises(Exception, match="connection|secret"):
            await svc.verify(bad)
    rotated, fresh = await svc.rotate("t1", "u1", c.id)
    assert fresh != secret and (await svc.verify(fresh)).id == c.id
    with pytest.raises(Exception, match="wrong secret"):
        await svc.verify(secret)
    await svc.revoke("t1", "u1", c.id)
    with pytest.raises(Exception, match="revoked"):
        await svc.verify(fresh)
    with pytest.raises(KeyError):
        await svc.mine("t1", "someone-else", c.id)


async def test_what_a_connection_may_hold_is_checked_and_the_floor_cannot_be_stored():
    svc = ConnectionsService(InMemoryConnectionStore())
    with pytest.raises(ValueError, match="unknown scopes"):
        await svc.create("t1", "u1", "x", scopes=["make", "everything"])
    with pytest.raises(ValueError, match="unknown scopes"):
        await svc.create("t1", "u1", "x", scopes=["admin"])
    with pytest.raises(ValueError, match="always ask"):
        await svc.create("t1", "u1", "x", policy={"destroy": "auto"})
    with pytest.raises(ValueError, match="name"):
        await svc.create("t1", "u1", "")
    c, _ = await svc.create("t1", "u1", "ok", scopes=["library"], policy={"make": "auto"})
    assert c.scopes == ("library", "read") and c.approval.make == "auto"
    c = await svc.update(
        "t1", "u1", c.id, {"approval": {"make": "ask_costly"}, "rate_per_minute": 5}
    )
    assert c.approval.make == "ask_costly" and c.rate_per_minute == 5
    with pytest.raises(ValueError, match="rate"):
        await svc.update("t1", "u1", c.id, {"rate_per_minute": 0})


async def test_the_sql_store_keeps_connections_and_their_activity(tmp_path):
    from wasifyai_api.mcp_server.connections import ActivityEntry

    store = SqlConnectionStore(create_sqlite_engine(tmp_path / "app.db"))
    svc = ConnectionsService(store)
    c, secret = await svc.create(
        "t1", "u1", "Claude Code", scopes=["make", "library"], policy={"make": "auto"},
        write_folders=[str(tmp_path / "out")],
    )  # fmt: skip
    again = await store.get(c.id)
    assert again == c
    assert [x.name for x in await store.for_person("t1", "u1")] == ["Claude Code"]
    await store.record(ActivityEntry(c.id, "tools/call", "image_generate", "ok", 1200, 300))
    (entry,) = await store.activity(c.id)
    assert (entry.method, entry.tool, entry.status, entry.duration_ms) == (
        "tools/call", "image_generate", "ok", 1200,
    )  # fmt: skip
    await svc.touch(c)
    assert (await store.get(c.id)).last_used_at is not None  # type: ignore[union-attr]


# ---- the engine on a real port -----------------------------------------------------------------


class Engine:
    """The desktop engine served by uvicorn in a thread, so the SDK's client can reach it."""

    def __init__(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        # the engine's own address, as the desktop entry point sets it: engine.json names it
        os.environ["DESKTOP_PUBLIC_URL"] = f"http://127.0.0.1:{self.port}"
        get_settings.cache_clear()
        self.app = create_app()
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="warning"))
        self._sock = sock
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.run(self.server.serve(sockets=[self._sock]))

    def start(self) -> "Engine":
        self._thread.start()
        deadline = time.monotonic() + 30
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("the engine did not start")
            time.sleep(0.05)
        return self

    def stop(self) -> None:
        self.server.should_exit = True
        self._thread.join(15)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def post(self, path: str, body: dict | None = None, **kw: Any) -> httpx.Response:
        return httpx.post(f"{self.base}{path}", json=body, headers=auth(), timeout=30, **kw)

    def get(self, path: str) -> httpx.Response:
        return httpx.get(f"{self.base}{path}", headers=auth(), timeout=30)

    def connection(self, name: str = "Codex", **body: Any) -> tuple[dict, str]:
        r = self.post("/connections", {"name": name, **body})
        assert r.status_code == 201, r.text
        return r.json()["connection"], r.json()["secret"]


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(calls, "APPROVAL_WAIT_S", 0.5)  # a card nobody answers: do not wait 25 s
    e = Engine().start()
    try:
        yield e
    finally:
        e.stop()


def sdk(engine: Engine, secret: str, mode: str):
    hc = httpx2.AsyncClient(headers={"Authorization": f"Bearer {secret}"}, timeout=60)
    return Client(streamable_http_client(f"{engine.base}/mcp", http_client=hc), mode=mode)


def text_of(result: Any) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


@pytest.mark.parametrize("mode", ["legacy", "auto", "2026-07-28"])
async def test_the_three_protocol_revisions_list_and_call_what_the_scopes_offer(engine, mode):
    _, secret = engine.connection("Claude Code")
    async with sdk(engine, secret, mode) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert {
            "image_generate",
            "app_status",
            "job_status",
            "job_wait",
            "models_list",
            "approval_status",
        } <= set(tools)
        assert "library_search" not in tools and "library_delete" not in tools  # not in the scopes
        assert tools["image_generate"].annotations.read_only_hint is False
        assert tools["app_status"].annotations.read_only_hint is True
        assert "prompt" in tools["image_generate"].input_schema["properties"]
        status = await client.call_tool("app_status", {})
        assert not status.is_error and status.structured_content["status"] == "ok"
        assert "image.generate" in text_of(status) or status.structured_content["output"]
        nope = await client.call_tool("library_search", {"query": "x"})
        assert nope.is_error and "not offered" in text_of(nope)


async def test_a_make_asks_in_the_window_and_the_persons_yes_runs_it_as_a_job(engine):
    c, secret = engine.connection("Codex")
    async with sdk(engine, secret, "2026-07-28") as client:
        asked = await client.call_tool("image_generate", {"prompt": "a red teapot"})
        s = asked.structured_content
        assert s["status"] == "needs_approval" and s["approval_id"], asked
        assert "Wasify AI window" in text_of(asked)
        approval_id = s["approval_id"]
        # the window: the card is in the pending list, the person says yes
        pending = engine.get("/actions/approvals").json()["approvals"]
        assert [p["approval_id"] for p in pending] == [approval_id]
        assert (
            pending[0]["connection"] == "Codex" and pending[0]["params"]["prompt"] == "a red teapot"
        )
        decided = engine.post(f"/actions/approvals/{approval_id}", {"approved": True}).json()
        assert decided["status"] == "approved" and decided["result_status"] in ("running", "ok")
        # the agent follows it: approval_status, then the job
        followed = await client.call_tool(
            "approval_status", {"approval_id": approval_id, "wait_seconds": 1}
        )
        f = followed.structured_content
        assert f["status"] == "approved"
        if f.get("job_id"):
            done = await client.call_tool("job_wait", {"job_id": f["job_id"], "seconds": 30})
            assert done.structured_content["status"] == "ok", done
            assert "image_id" in json.dumps(done.structured_content["output"])
        assert engine.get("/actions/approvals").json()["approvals"] == []
        # a second card the person says no to
        again = await client.call_tool("image_generate", {"prompt": "a blue teapot"})
        aid = again.structured_content["approval_id"]
        assert (
            engine.post(f"/actions/approvals/{aid}", {"approved": False}).json()["status"]
            == "denied"
        )
        status = await client.call_tool("approval_status", {"approval_id": aid})
        assert status.structured_content["status"] == "denied"
    activity = engine.get(f"/connections/{c['id']}/activity").json()["activity"]
    assert any(a["tool"] == "image_generate" for a in activity)
    assert all("teapot" not in json.dumps(a) for a in activity)  # no content in the log


async def test_a_connection_allowed_to_run_things_gets_a_job_handle_at_once(engine):
    _, secret = engine.connection("Trusted", approval={"make": "auto"})
    async with sdk(engine, secret, "legacy") as client:
        made = await client.call_tool("image_generate", {"prompt": "a green teapot"})
        s = made.structured_content
        assert s["status"] in ("ok", "running"), made
        if s["status"] == "running":
            done = await client.call_tool("job_wait", {"job_id": s["job_id"], "seconds": 30})
            assert done.structured_content["status"] == "ok"
        delete = await client.call_tool("library_delete", {"kind": "image", "id": "x"})
        assert delete.is_error and "not offered" in text_of(delete)  # library is not a scope here


def test_the_gate_refuses_what_it_must(engine):
    c, secret = engine.connection("Gate", scopes=["read"])
    url = f"{engine.base}/mcp"
    body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    h = {"Accept": "application/json, text/event-stream"}
    assert httpx.post(url, json=body, headers=h).status_code == 401
    assert (
        httpx.post(
            url,
            json=body,
            headers={**h, "Authorization": "Bearer wsc_0000000000000000_xxxxxxxxxxxxxxxxxxxxxxxx"},
        ).status_code
        == 401
    )
    good = {**h, "Authorization": f"Bearer {secret}"}
    assert (
        httpx.post(url, json=body, headers={**good, "Origin": "http://evil.example"}).status_code
        == 403
    )
    assert httpx.post(url, json=body, headers={**good, "Host": "evil.example"}).status_code == 421
    big = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"x": "a" * (1 << 20)}}
    assert httpx.post(url, json=big, headers=good).status_code == 413
    # the rate: a fresh connection allowed three calls a minute
    slow, slow_secret = engine.connection("Slow", scopes=["read"])
    r = httpx.patch(
        f"{engine.base}/connections/{slow['id']}", json={"rate_per_minute": 3}, headers=auth()
    )
    assert r.status_code == 200
    slow_h = {**h, "Authorization": f"Bearer {slow_secret}"}
    codes = [httpx.post(url, json=body, headers=slow_h).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    assert httpx.delete(f"{engine.base}/connections/{c['id']}", headers=auth()).json()["revoked"]
    assert httpx.post(url, json=body, headers=good).status_code == 401


def test_the_launcher_switch_writes_and_removes_the_runtime_file(engine):
    state = engine.get("/connections/launcher").json()
    assert state["available"] is True and state["enabled"] is False
    on = httpx.put(
        f"{engine.base}/connections/launcher", json={"enabled": True}, headers=auth()
    ).json()
    assert on["enabled"] is True and on["connection"]["kind"] == "launcher"
    path = Path(on["file"])
    assert path.name == "engine.json" and stat.S_IMODE(path.stat().st_mode) == 0o600
    content = json.loads(path.read_text())
    assert content["host"] == "127.0.0.1" and content["pid"] == os.getpid()
    assert content["secret"].startswith("wsc_") and content["port"] == engine.port
    assert on["connection"]["id"] not in {
        c["id"] for c in engine.get("/connections").json()["connections"]
    }  # the launcher's connection is not in the list of the person's own
    snippets = engine.get("/connections/snippets").json()["snippets"]
    assert "wasify" in snippets["codex_toml"] and "mcpServers" in snippets["claude_code_json"]
    off = httpx.put(
        f"{engine.base}/connections/launcher", json={"enabled": False}, headers=auth()
    ).json()
    assert off["enabled"] is False and not path.exists()
    # the launcher's secret is the connection's: it opens the endpoint while on
    on = httpx.put(
        f"{engine.base}/connections/launcher", json={"enabled": True}, headers=auth()
    ).json()
    secret = json.loads(Path(on["file"]).read_text())["secret"]
    r = httpx.post(
        f"{engine.base}/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {secret}",
        },
    )
    assert r.status_code == 200


# ---- the launcher (`wasify-mcp`, the Rust binary beside the shell) -----------------------------

LAUNCHER = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "desktop"
    / "src-tauri"
    / "target"
    / "debug"
    / "wasify-mcp"
)
needs_launcher = pytest.mark.skipif(
    not LAUNCHER.is_file(),
    reason="build it: cargo build --bin wasify-mcp in apps/desktop/src-tauri",
)


def launcher(runtime_file: Path):
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command=str(LAUNCHER), args=[], env={"WASIFY_ENGINE_JSON": str(runtime_file)}
    )


@needs_launcher
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_the_launcher_reaches_the_engine_through_the_runtime_file(engine, mode):
    on = await asyncio.to_thread(
        lambda: httpx.put(
            f"{engine.base}/connections/launcher", json={"enabled": True}, headers=auth()
        ).json()
    )
    async with Client(launcher(Path(on["file"])), mode=mode) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert {"image_generate", "app_status", "approval_status"} <= tools
        status = await client.call_tool("app_status", {})
        assert not status.is_error and status.structured_content["status"] == "ok"
        asked = await client.call_tool(
            "image_generate", {"prompt": "a teapot through the launcher"}
        )
        assert asked.structured_content["status"] == "needs_approval"
    activity = engine.get(f"/connections/{on['connection']['id']}/activity").json()["activity"]
    assert any(a["tool"] == "image_generate" for a in activity)


@needs_launcher
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_the_launcher_answers_itself_when_the_app_is_closed(tmp_path, mode):
    async with Client(launcher(tmp_path / "missing.json"), mode=mode) as client:
        tools = [t.name for t in (await client.list_tools()).tools]
        assert tools == ["app_status"]
        r = await client.call_tool("app_status", {})
        assert r.is_error and "Open Wasify AI" in text_of(r)


@needs_launcher
async def test_the_launcher_refuses_a_runtime_file_it_cannot_trust(tmp_path):
    bad = tmp_path / "engine.json"
    bad.write_text(json.dumps({"pid": 99999999, "host": "127.0.0.1", "port": 1, "secret": "x"}))
    bad.chmod(0o644)  # readable by others: refused, and so is a stale pid
    async with Client(launcher(bad), mode="2026-07-28") as client:
        r = await client.call_tool("app_status", {})
        assert r.is_error and "Open Wasify AI" in text_of(r)
    far = tmp_path / "far.json"
    far.write_text(json.dumps({"pid": os.getpid(), "host": "10.0.0.5", "port": 1, "secret": "x"}))
    far.chmod(0o600)
    async with Client(launcher(far), mode="2026-07-28") as client:
        r = await client.call_tool("app_status", {})
        assert r.is_error and "Open Wasify AI" in text_of(r)
