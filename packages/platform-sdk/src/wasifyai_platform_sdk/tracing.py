"""Traces (stage O1 of the 2026-10-27 plan; ADR-0048 amended 2026-10-29).

One span per run, per graph node, per action and per engine or media job, joined into one trace from
the request that started it (a `traceparent` header from the web app's BFF) to the worker that did
the work (the trace context travels in the job, `EngineJob.trace` and `JobRequest.trace`).

Where spans go is configuration, read once at start by `setup(service)`:

    OTEL_EXPORTER_OTLP_ENDPOINT or
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT   OTLP over HTTP (Tempo in the monitoring stack, on the web)
    WASIFYAI_TRACES_FILE                 one JSON line per span (desktop: <data>/logs/traces.jsonl)
    neither                              no tracing: every call here costs next to nothing

What a span may carry follows ADR-0048's rule for labels, loosened only for ids: a product, a node,
an action, a job kind, an outcome, an error code, and the run's or job's id. Never a user's id, an
e-mail address, a prompt, a file name or content. `span()` drops any other attribute.
"""

import contextlib
import json
import logging
import os
import threading
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

log = logging.getLogger(__name__)

TRACER = "wasifyai"
FILE_LIMIT_BYTES = 20_000_000  # then the file moves to traces.1.jsonl and a new one starts
# what a span may carry (anything else is dropped, so a careless call cannot leak content)
ALLOWED = frozenset(
    {
        "product", "node", "action", "origin", "effect", "kind", "outcome", "code", "run_id",
        "job_id", "worker", "queue", "http.method", "http.route", "http.status_code", "service",
    }
)  # fmt: skip

_set_up = False
_lock = threading.Lock()


class JsonLinesExporter(SpanExporter):
    """Spans as JSON lines in a file the person can open (and Save diagnostics can carry)."""

    def __init__(self, path: Path, limit_bytes: int = FILE_LIMIT_BYTES):
        self.path, self.limit = path, limit_bytes
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        lines = "".join(json.dumps(_line(s), separators=(",", ":")) + "\n" for s in spans)
        try:
            with self._lock:
                if self.path.exists() and self.path.stat().st_size > self.limit:
                    self.path.replace(self.path.with_suffix(".1.jsonl"))
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(lines)
        except OSError:
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def _line(s: ReadableSpan) -> dict[str, Any]:
    ctx = s.get_span_context()
    parent = s.parent
    start, end = s.start_time or 0, s.end_time or 0
    return {
        "trace_id": format(ctx.trace_id, "032x") if ctx else "",
        "span_id": format(ctx.span_id, "016x") if ctx else "",
        "parent_id": format(parent.span_id, "016x") if parent else None,
        "name": s.name,
        "service": s.resource.attributes.get("service.name", ""),
        "start_ns": start,
        "ms": round((end - start) / 1e6, 3),
        "status": s.status.status_code.name.lower(),
        "attributes": dict(s.attributes or {}),
    }


def setup(service: str, env: Mapping[str, str] | None = None) -> bool:
    """Send spans where the environment says (see the module's words); False when nowhere. Called
    once per process; a second call changes nothing."""
    global _set_up
    env = os.environ if env is None else env
    endpoint = env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or env.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    file = env.get("WASIFYAI_TRACES_FILE")
    with _lock:
        if _set_up:
            return True
        if not endpoint and not file:
            return False
        provider = TracerProvider(
            resource=Resource.create({"service.name": env.get("OTEL_SERVICE_NAME", service)})
        )
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            # the exporter reads OTEL_EXPORTER_OTLP_* itself (endpoint, headers, timeout)
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        if file:
            provider.add_span_processor(BatchSpanProcessor(JsonLinesExporter(Path(file))))
        trace.set_tracer_provider(provider)
        _set_up = True
    return True


def add_exporter(exporter: SpanExporter) -> None:
    """Send spans to one more place as they end (tests read them from memory). Sets up a provider
    first when `setup` found nowhere to send them."""
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    global _set_up
    with _lock:
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider(resource=Resource.create({"service.name": "wasifyai"}))
            trace.set_tracer_provider(provider)
            _set_up = True
        provider.add_span_processor(SimpleSpanProcessor(exporter))


def flush() -> None:
    """Send what is waiting (an app or a worker is stopping). The provider itself shuts down when
    the process exits, so another app in the same process (tests) keeps tracing."""
    provider = trace.get_tracer_provider()
    with contextlib.suppress(Exception):
        provider.force_flush()  # pyright: ignore[reportAttributeAccessIssue]


def _clean(attrs: Mapping[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (attrs or {}).items():
        if k in ALLOWED and v is not None and isinstance(v, str | int | float | bool):
            out[k] = v
    return out


@contextlib.contextmanager
def span(
    name: str,
    attrs: Mapping[str, Any] | None = None,
    *,
    parent: Mapping[str, str] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Iterator[Span]:
    """A span around a block. `parent` is a carried trace context (a job's `trace`), for work that
    goes on in another process; without it the span is a child of the current one. An exception
    marks the span as an error with its type (never its message, which may hold content)."""
    ctx = extract(dict(parent)) if parent else None
    tracer = trace.get_tracer(TRACER)
    with tracer.start_as_current_span(
        name, context=ctx, kind=kind, attributes=_clean(attrs), record_exception=False,
        set_status_on_exception=False,
    ) as current:  # fmt: skip
        try:
            yield current
        except BaseException as e:
            current.set_status(Status(StatusCode.ERROR, type(e).__name__))
            raise


def set_attrs(current: Span, **attrs: Any) -> None:
    """Add attributes to a span after it started (an outcome, a code), by the same rule."""
    for k, v in _clean(attrs).items():
        current.set_attribute(k, v)


def fail(current: Span, code: str) -> None:
    """Mark a span as failed with a code (bounded, from the errors' list)."""
    current.set_status(Status(StatusCode.ERROR, code))
    set_attrs(current, code=code)


def carrier() -> dict[str, str]:
    """The current trace context, to carry in a job (empty when nothing is traced)."""
    out: dict[str, str] = {}
    inject(out)
    return out


@contextlib.contextmanager
def continued(headers: Mapping[str, str]) -> Iterator[None]:
    """Make an incoming request's trace context (`traceparent`) the current one."""
    token = otel_context.attach(extract(dict(headers)))
    try:
        yield
    finally:
        otel_context.detach(token)


def trace_id() -> str:
    """The current trace's id as hex, for log lines; "-" when there is none."""
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else "-"
