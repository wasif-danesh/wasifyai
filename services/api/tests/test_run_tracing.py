# pyright: reportOptionalMemberAccess=false, reportOptionalSubscript=false
"""Traces in the engine (stage O1): a run started with the BFF's `traceparent` is one trace: the
request's span, the run's span and a span per node under it. Langfuse stores no content unless its
capture is on, and knows a person only by a hash."""

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from wasifyai_api.assemble import Injected
from wasifyai_api.graphs.hello import build_hello
from wasifyai_api.main import create_app
from wasifyai_api.run_tracing import NOT_CAPTURED, Langfuse, _hide
from wasifyai_platform_sdk import (
    GraphRegistry,
    InMemoryEventLog,
    InMemoryRunStore,
    InMemoryUsageRecorder,
    tracing,
)

MEMORY = InMemorySpanExporter()
tracing.add_exporter(MEMORY)

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = f"00-{TRACE}-00f067aa0ba902b7-01"


@pytest.fixture
def products(tmp_path):
    d = tmp_path / "hello"
    d.mkdir()
    (d / "product.yaml").write_text(
        "id: hello\ncapabilities:\n"
        '  text.chat: { provider: fake, defaults: { reply: "Hello there friend" } }\n'
    )
    return tmp_path


def hello_app(products):
    registry = GraphRegistry()
    registry.register("hello", build_hello)
    return create_app(
        Injected(
            registry=registry, products_dir=products, checkpointer=InMemorySaver(),
            usage=InMemoryUsageRecorder(), heartbeat_s=0.05, event_log=InMemoryEventLog(),
            run_store=InMemoryRunStore(),
        )
    )  # fmt: skip


def test_a_run_from_the_bff_is_one_trace_with_a_span_per_node(products):
    MEMORY.clear()
    app = hello_app(products)
    with TestClient(app) as c:
        r = c.post(
            "/products/hello/runs", json={"input": {"message": "hi"}},
            headers={"traceparent": PARENT},
        )  # fmt: skip
        assert r.status_code == 200 and "event: done" in r.text
    spans = MEMORY.get_finished_spans()
    assert {format(s.context.trace_id, "032x") for s in spans} == {TRACE}
    servers = [s for s in spans if s.kind == SpanKind.SERVER]
    assert len(servers) == 1  # ours only: FastAPI's own telemetry is off (it records raw paths)
    by_name = {s.name: s for s in spans}
    request = by_name["POST /products/{product_id}/runs"]
    assert request.kind == SpanKind.SERVER and request.attributes["http.status_code"] == 200
    assert format(request.parent.span_id, "016x") == "00f067aa0ba902b7"
    run = by_name["run"]
    assert run.attributes["product"] == "hello" and run.attributes["outcome"] == "done"
    nodes = [s for s in spans if s.name.startswith("node ")]
    assert nodes and all(n.parent.span_id == run.context.span_id for n in nodes)
    # nothing a person wrote is on any span
    assert not any("hi" == v for s in spans for v in (s.attributes or {}).values())


def test_health_checks_are_not_traced(products):
    MEMORY.clear()
    with TestClient(hello_app(products)) as c:
        c.get("/health")
    assert MEMORY.get_finished_spans() == ()


def test_langfuse_is_off_without_its_keys_and_hides_content_unless_captured():
    off = Langfuse("", "", "", capture=True)
    assert not off.on and off.callbacks("t", "u", "p") == ([], {})
    assert _hide(data="a red fox") == NOT_CAPTURED and _hide(data=None) is None


def test_langfuse_knows_a_person_only_by_a_hash():
    lf = Langfuse("pk-lf-test", "sk-lf-test", "http://127.0.0.1:9", capture=False)
    callbacks, meta = lf.callbacks("tenant-1", "person@example.com", "images")
    assert len(callbacks) == 1 and meta["langfuse_tags"] == ["images"]
    assert "person" not in meta["langfuse_user_id"] and len(meta["langfuse_user_id"]) == 24
    assert meta == lf.callbacks("tenant-1", "person@example.com", "images")[1]  # the same each run
