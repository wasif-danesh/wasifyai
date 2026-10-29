"""Traces (stage O1): spans carry only bounded words and ids, a job carries its trace to the
worker, and the desktop's file holds one JSON line per span."""

import json

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from wasifyai_platform_sdk import tracing
from wasifyai_platform_sdk.engine_jobs import EngineJob
from wasifyai_platform_sdk.jobs import JobRequest

MEMORY = InMemorySpanExporter()
tracing.add_exporter(MEMORY)


@pytest.fixture
def spans():
    MEMORY.clear()
    yield MEMORY
    MEMORY.clear()


def test_a_span_keeps_only_the_words_it_may_carry(spans):
    with tracing.span(
        "run", {"product": "images", "prompt": "a red fox", "user_id": "u1", "run_id": "r1"}
    ) as s:
        tracing.set_attrs(s, outcome="done", email="a@b.c")
    (got,) = spans.get_finished_spans()
    assert dict(got.attributes or {}) == {"product": "images", "run_id": "r1", "outcome": "done"}


def test_a_failure_is_its_type_or_code_never_its_message(spans):
    with pytest.raises(ValueError), tracing.span("action"):
        raise ValueError("the person's secret words")
    with tracing.span("engine job") as s:
        tracing.fail(s, "timeout")
    failed, coded = spans.get_finished_spans()
    assert failed.status.status_code == StatusCode.ERROR
    assert failed.status.description == "ValueError" and not failed.events
    assert coded.status.description == "timeout" and coded.attributes["code"] == "timeout"


def test_a_job_made_in_a_run_carries_the_trace_to_its_worker(spans):
    with tracing.span("run") as run:
        job = EngineJob(kind="speech.speak", tenant_id="t", product_id="p", user_id="u", prefix="x")
        media = JobRequest(
            tenant_id="t", product_id="p", user_id="u", capability="image.generate",
            workflow="w", prompt={}, outputs={},
        )  # fmt: skip
    assert job.trace["traceparent"] == media.trace["traceparent"]
    # the worker, in another process, reads the job back and continues the trace
    again = EngineJob.model_validate_json(job.model_dump_json())
    with tracing.span("engine job", parent=again.trace):
        pass
    worker, _ = sorted(spans.get_finished_spans(), key=lambda s: s.name)
    assert worker.context.trace_id == run.get_span_context().trace_id
    assert worker.parent.span_id == run.get_span_context().span_id


def test_a_job_made_outside_a_trace_carries_nothing():
    job = EngineJob(kind="k", tenant_id="t", product_id="p", user_id="u", prefix="x")
    assert job.trace == {}


def test_an_incoming_traceparent_is_continued(spans):
    parent = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    with tracing.continued({"traceparent": parent}), tracing.span("POST /x"):
        assert tracing.trace_id() == "0af7651916cd43dd8448eb211c80319c"
    (got,) = spans.get_finished_spans()
    assert format(got.parent.span_id, "016x") == "b7ad6b7169203331"


def test_the_file_holds_one_json_line_per_span_and_starts_again_when_full(spans, tmp_path):
    with tracing.span("run", {"product": "voice"}):
        pass
    path = tmp_path / "logs" / "traces.jsonl"
    exporter = tracing.JsonLinesExporter(path, limit_bytes=10)
    exporter.export(spans.get_finished_spans())
    line = json.loads(path.read_text())
    assert line["name"] == "run" and line["attributes"] == {"product": "voice"}
    assert len(line["trace_id"]) == 32 and line["parent_id"] is None and line["ms"] >= 0
    exporter.export(spans.get_finished_spans())  # past the limit: the old file moves aside
    assert (tmp_path / "logs" / "traces.1.jsonl").exists()
    assert len(path.read_text().splitlines()) == 1
