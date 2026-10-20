import json
from typing import Any, TypedDict

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from wasifyai_api.graphs.hello import build_hello
from wasifyai_api.main import create_app
from wasifyai_platform_sdk import (
    GraphRegistry,
    InMemoryEventLog,
    InMemoryRunStore,
    InMemoryUsageRecorder,
)


def hello_registry() -> GraphRegistry:
    registry = GraphRegistry()
    registry.register("hello", build_hello)
    return registry


def mem_app(registry, products, usage, *, storage=None, **kw):
    """An app wired entirely in memory: no Redis, Postgres or network."""
    return create_app(
        registry,
        products,
        InMemorySaver(),
        usage,
        storage,
        heartbeat_s=0.05,
        event_log=InMemoryEventLog(),
        run_store=InMemoryRunStore(),
        **kw,
    )


def parse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = [ln for ln in block.split("\n") if not ln.startswith(":")]
        if not lines:
            continue
        ev = lines[1].removeprefix("event: ")
        out.append((ev, json.loads(lines[2].removeprefix("data: "))))
    return out


@pytest.fixture
def products(tmp_path):
    d = tmp_path / "hello"
    d.mkdir()
    (d / "product.yaml").write_text(
        "id: hello\ncapabilities:\n"
        '  text.chat: { provider: fake, defaults: { reply: "Hello there friend" } }\n'
    )
    return tmp_path


@pytest.fixture
def usage():
    return InMemoryUsageRecorder()


@pytest.fixture
def client(products, usage):
    app = mem_app(hello_registry(), products, usage)
    with TestClient(app) as c:
        yield c


def test_hello_run_streams_tokens_and_done(client):
    r = client.post("/products/hello/runs", json={"input": {"message": "hi"}})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse(r.text)
    names = [e for e, _ in events]
    assert names[0] == "node" and names[-1] == "done"
    assert "".join(d["text"] for e, d in events if e == "token").strip() == "Hello there friend"
    seqs = [d["seq"] for _, d in events]
    assert seqs == list(range(1, len(seqs) + 1))
    assert events[-1][1]["outputs"]["reply"] == "Hello there friend"


def test_run_records_usage_with_tenancy(client, usage):
    client.post("/products/hello/runs", json={"input": {"message": "hi"}})
    assert {e.kind for e in usage.events} == {"llm.input_tokens", "llm.output_tokens"}
    e = usage.events[0]
    assert (e.tenant_id, e.product_id, e.user_id) == ("dev-tenant", "hello", "dev-user")
    assert e.run_id


def test_unknown_product_404(client):
    assert client.post("/products/nope/runs", json={}).status_code == 404


def test_reconnect_replays_after_last_event_id(client):
    r = client.post("/products/hello/runs", json={"input": {"message": "hi"}})
    events = parse(r.text)
    run_id = events[0][1]["run_id"]
    replay = client.get(f"/runs/{run_id}/events", headers={"Last-Event-ID": "2"})
    assert [d["seq"] for _, d in parse(replay.text)] == [d["seq"] for _, d in events][2:]


def test_other_users_run_is_404(client):
    from uuid import uuid4

    assert client.get(f"/runs/{uuid4()}/events").status_code == 404


class ApproveState(TypedDict, total=False):
    draft: str
    approved: str


def _approve_graph(caps: Any, checkpointer: Any):
    def ask(state: ApproveState) -> ApproveState:
        answer = interrupt({"kind": "approve_draft", "draft": "v1"})
        return {"approved": answer}

    g = StateGraph(ApproveState)
    g.add_node("ask", ask)
    g.add_edge(START, "ask")
    g.add_edge("ask", END)
    return g.compile(checkpointer=checkpointer)


def test_interrupt_and_resume(tmp_path):
    (tmp_path / "approve").mkdir()
    (tmp_path / "approve" / "product.yaml").write_text("id: approve\n")
    registry = GraphRegistry()
    registry.register("approve", _approve_graph)
    app = mem_app(registry, tmp_path, InMemoryUsageRecorder())
    with TestClient(app) as c:
        first = parse(c.post("/products/approve/runs", json={}).text)
        assert first[-1][0] == "interrupt"
        assert first[-1][1]["kind"] == "approve_draft"
        run_id = first[-1][1]["run_id"]
        second = parse(c.post(f"/runs/{run_id}/resume", json={"value": "yes"}).text)
        assert second[-1][0] == "done"
        assert second[-1][1]["outputs"]["approved"] == "yes"
        assert second[0][1]["seq"] == first[-1][1]["seq"] + 1
        assert c.post(f"/runs/{run_id}/resume", json={"value": "x"}).status_code == 409


@pytest.fixture
def media_client(tmp_path, usage):
    from wasifyai_platform_sdk import ScopedStorage, memory_storage, object_key

    d = tmp_path / "hello"
    d.mkdir()
    (d / "product.yaml").write_text(
        "id: hello\ncapabilities:\n"
        '  text.chat: { provider: fake, defaults: { reply: "text only" } }\n'
        '  text.multimodal: { provider: fake, defaults: { reply: "saw it" },\n'
        "                     inputs: [text, image, audio] }\n"
    )
    raw = memory_storage()
    app = mem_app(hello_registry(), tmp_path, usage, storage=ScopedStorage(raw))
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    key = object_key("dev-tenant", "hello", "dev-user", "uploads", "cat.png")
    import asyncio

    asyncio.run(raw.put(key, png, "image/png"))
    with TestClient(app) as c:
        yield c


def test_run_with_stored_image_uses_the_multimodal_capability(media_client, usage):
    r = media_client.post(
        "/products/hello/runs",
        json={"input": {"message": "what is this?", "image_key": "uploads/cat.png"}},
    )
    events = parse(r.text)
    assert events[-1][0] == "done" and events[-1][1]["outputs"]["reply"] == "saw it"
    assert usage.events[0].meta["capability"] == "text.multimodal"
    assert usage.events[0].meta["inputs"] == {"images": 1}


def test_run_without_media_still_uses_plain_chat(media_client, usage):
    r = media_client.post("/products/hello/runs", json={"input": {"message": "hi"}})
    assert parse(r.text)[-1][1]["outputs"]["reply"] == "text only"
    assert usage.events[0].meta["capability"] == "text.chat"


@pytest.mark.parametrize(
    "key", ["uploads/missing.png", "../other-user/cat.png", "uploads/notes.txt"]
)
def test_bad_media_keys_end_in_a_clean_error_event(media_client, key):
    events = parse(
        media_client.post(
            "/products/hello/runs", json={"input": {"message": "x", "image_key": key}}
        ).text
    )
    assert events[-1][0] == "error"
    assert "Traceback" not in json.dumps(events[-1][1])


def test_run_error_ends_the_run_with_its_own_clean_message(tmp_path):
    from wasifyai_platform_sdk import RunError

    def boom_graph(caps, checkpointer):
        def node(state):
            raise RunError(
                "lyrics_failed", "We could not write usable lyrics. Try rephrasing.", True
            )

        g = StateGraph(ApproveState)
        g.add_node("n", node)
        g.add_edge(START, "n")
        g.add_edge("n", END)
        return g.compile(checkpointer=checkpointer)

    (tmp_path / "boom").mkdir()
    (tmp_path / "boom" / "product.yaml").write_text("id: boom\n")
    registry = GraphRegistry()
    registry.register("boom", boom_graph)
    with TestClient(mem_app(registry, tmp_path, InMemoryUsageRecorder())) as c:
        events = parse(c.post("/products/boom/runs", json={}).text)
    code = events[-1][1]
    assert events[-1][0] == "error"
    assert (code["code"], code["retryable"]) == ("lyrics_failed", True)
    assert code["message"] == "We could not write usable lyrics. Try rephrasing."


async def test_a_child_run_yields_the_events_of_another_graph_until_it_ends(tmp_path):
    """The assistant's tools run another product as a child run (ADR-0057): same events, own run."""
    products = tmp_path
    d = products / "hello"
    d.mkdir()
    (d / "product.yaml").write_text(
        "id: hello\ncapabilities:\n"
        '  text.chat: { provider: fake, defaults: { reply: "Hello there friend" } }\n'
    )
    from wasifyai_api.runs import RunManager
    from wasifyai_platform_sdk import (
        InMemoryUsageRecorder,
        ProviderDeps,
        build_capabilities,
        load_product_config,
    )

    caps = build_capabilities(
        load_product_config(products, "hello"),
        ProviderDeps(products_dir=products, usage=InMemoryUsageRecorder()),
    )
    runs = RunManager(
        InMemoryEventLog(), InMemoryRunStore(), {"hello": build_hello(caps, InMemorySaver())}
    )
    events = [e async for e in runs.run_child("hello", "t1", "u1", {"text": "hi"})]
    names = [e["event"] for e in events]
    assert names[-1] == "done" and "token" in names
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    # its own run: owned by the same user, and it is in the store like any other
    await runs.aclose()


async def test_a_child_run_that_takes_too_long_ends_with_a_plain_error(tmp_path):
    import asyncio

    from wasifyai_api.runs import RunManager

    class Never:
        async def astream(self, *a, **k):
            await asyncio.sleep(30)
            yield "custom", {}

        async def aget_state(self, *a, **k): ...

    runs = RunManager(InMemoryEventLog(), InMemoryRunStore(), {"slow": Never()})
    events = [e async for e in runs.run_child("slow", "t1", "u1", {}, timeout_s=0.3)]
    assert events[-1]["event"] == "error" and events[-1]["code"] == "timeout"
    await runs.aclose()


# ---- a run id chosen by the client, and Stop (ADR-0082, stage CU1) ----------------------


def test_a_run_id_chosen_by_the_client_is_the_runs_id(client, usage):
    from uuid import uuid4

    rid = str(uuid4())
    body = {"input": {"message": "hi"}, "run_id": rid}
    events = parse(client.post("/products/hello/runs", json=body).text)
    assert {d["run_id"] for _, d in events} == {rid}
    assert events[-1][0] == "done"


def test_starting_again_under_the_same_run_id_is_the_same_run(client, usage):
    from uuid import uuid4

    rid = str(uuid4())
    body = {"input": {"message": "hi"}, "run_id": rid}
    first = parse(client.post("/products/hello/runs", json=body).text)
    spent = len(usage.events)
    again = parse(client.post("/products/hello/runs", json=body).text)
    # the same events, replayed from the first; no second answer was made or paid for
    assert [d["seq"] for _, d in again] == [d["seq"] for _, d in first]
    assert "".join(d.get("text", "") for _, d in again) == "".join(
        d.get("text", "") for _, d in first
    )
    assert len(usage.events) == spent


def test_a_run_id_must_be_a_uuid(client):
    r = client.post("/products/hello/runs", json={"input": {}, "run_id": "not-a-uuid"})
    assert r.status_code == 422


async def test_a_run_id_that_is_someone_elses_is_a_conflict(tmp_path):
    from uuid import uuid4

    from wasifyai_api.runs import RunIdTaken, RunManager
    from wasifyai_platform_sdk import RunRecord

    mgr = RunManager(InMemoryEventLog(), InMemoryRunStore(), {})
    rid = uuid4()
    mine = RunRecord(
        run_id=str(rid), thread_id=str(uuid4()), product_id="hello", tenant_id="t", user_id="a"
    )
    assert await mgr.store.create(mine) is True
    with pytest.raises(RunIdTaken):
        await mgr.start("hello", "t", "b", None, {}, rid)  # another person
    with pytest.raises(RunIdTaken):
        await mgr.start("other-product", "t", "a", None, {}, rid)  # another product
    again = await mgr.start("hello", "t", "a", None, {}, rid)  # the same person: the same run
    assert again.run_id == str(rid)


def test_stopping_a_run_that_is_over_is_not_an_error(client):
    events = parse(client.post("/products/hello/runs", json={"input": {"message": "hi"}}).text)
    run_id = events[0][1]["run_id"]
    r = client.post(f"/runs/{run_id}/cancel")
    assert r.status_code == 200 and r.json() == {"run_id": run_id, "status": "done"}


def test_stopping_a_run_that_is_not_yours_is_a_404(client):
    from uuid import uuid4

    assert client.post(f"/runs/{uuid4()}/cancel").status_code == 404


class SlowState(TypedDict, total=False):
    said: str


def _slow_graph(started: Any):
    """A graph that writes a word every few milliseconds until it is stopped."""
    import asyncio

    from langgraph.config import get_stream_writer

    def build(caps: Any, checkpointer: Any):
        async def talk(state: SlowState) -> SlowState:
            write = get_stream_writer()
            started.set()
            try:
                for n in range(10_000):
                    write({"type": "token", "node": "talk", "text": f"w{n} "})
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                write({"type": "token", "node": "talk", "text": "(saved)"})
                raise
            return {"said": "never"}

        g = StateGraph(SlowState)
        g.add_node("talk", talk)
        g.add_edge(START, "talk")
        g.add_edge("talk", END)
        return g.compile(checkpointer=checkpointer)

    return build


async def _running_manager(monkeypatch=None):
    import asyncio

    from wasifyai_api.runs import RunManager

    started = asyncio.Event()
    log, store = InMemoryEventLog(), InMemoryRunStore()
    graph = _slow_graph(started)(None, InMemorySaver())
    mgr = RunManager(log, store, {"slow": graph})
    rec = await mgr.start("slow", "t", "u", None, {})
    await asyncio.wait_for(started.wait(), 5)
    await asyncio.sleep(0.05)
    return mgr, log, store, rec


async def test_stop_ends_the_run_where_it_is_and_closes_its_stream():
    mgr, log, store, rec = await _running_manager()
    assert (await mgr.cancel(rec)) == "cancelled"
    events = await log.read("t", rec.run_id, 0, 10)
    assert events[-1]["event"] == "error" and events[-1]["code"] == "cancelled"
    assert events[-1]["retryable"] is False
    assert (await store.get("t", rec.run_id)).status == "cancelled"  # type: ignore[union-attr]
    assert mgr._by_run == {}  # the task is gone
    seen = len(events)
    # a second stop changes nothing, and nothing more is written by the run
    assert (await mgr.cancel(rec)) == "cancelled"
    import asyncio

    await asyncio.sleep(0.1)
    assert len(await log.read("t", rec.run_id, 0, 1000)) == seen
    await mgr.aclose()


async def test_stop_that_reaches_another_replica_is_noticed_by_the_one_running_the_graph(
    monkeypatch,
):
    import asyncio

    from wasifyai_api import runs as runs_module
    from wasifyai_api.runs import RunManager

    monkeypatch.setattr(runs_module, "CANCEL_CHECK_S", 0.05)
    mgr, log, store, rec = await _running_manager()
    elsewhere = RunManager(log, store, {})  # shares the log and the store, runs nothing
    assert (await elsewhere.cancel(rec)) == "cancelled"
    for _ in range(100):
        if not mgr._by_run:
            break
        await asyncio.sleep(0.02)
    assert mgr._by_run == {}, "the run kept going after it was stopped"
    events = await log.read("t", rec.run_id, 0, 10_000)
    assert [e["code"] for e in events if e["event"] == "error"] == ["cancelled"]
    await mgr.aclose()
