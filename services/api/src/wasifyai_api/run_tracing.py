"""The engine's traces (stage O1): a span per request, continued from the BFF's `traceparent`, a
span per run and per graph node, and Langfuse's LLM traces behind its keys (ADR-0050).

The spans themselves go where `wasifyai_platform_sdk.tracing.setup` sent them (Tempo on the web, a
file on the desktop). Langfuse has a tracer provider of its own, so prompts it may hold never reach
Tempo or the file; its traces share the run's trace id, so one run can be followed from one to the
other.
"""

import hashlib
import logging
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from wasifyai_platform_sdk import tracing

log = logging.getLogger(__name__)

NOT_CAPTURED = "[not captured]"
SKIP_PATHS = frozenset({"/health", "/health/ready", "/metrics"})


class TracingMiddleware:
    """One server span per request, named by its route template (`POST /products/{id}/runs`), a
    child of the caller's span when the request carries a `traceparent` (the web app's BFF)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in SKIP_PATHS:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        method = scope.get("method", "GET")
        status = 500

        async def tap(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        with (
            tracing.continued(headers),
            tracing.span(method, {"http.method": method}, kind=SpanKind.SERVER) as current,
        ):
            try:
                await self.app(scope, receive, tap)
            finally:
                route = getattr(scope.get("route"), "path", None) or "unmatched"
                current.update_name(f"{method} {route}")
                tracing.set_attrs(current, **{"http.route": route, "http.status_code": status})
                if status >= 500:
                    current.set_status(Status(StatusCode.ERROR, str(status)))


class NodeSpans(BaseCallbackHandler):
    """A span per graph node, under the run's span (LangGraph calls back as each node starts and
    ends). Node names come from the graphs' code, so they are bounded."""

    run_inline = True  # called in the graph's own task, in order

    def __init__(self, run_span: Span):
        self._parent = trace.set_span_in_context(run_span)
        self._open: dict[UUID, Span] = {}

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        node = (metadata or {}).get("langgraph_node")
        if not node or kwargs.get("name") != node:
            return  # the graph itself, or a step inside a node
        above = self._open.get(parent_run_id) if parent_run_id else None
        ctx = trace.set_span_in_context(above) if above is not None else self._parent
        self._open[run_id] = trace.get_tracer(tracing.TRACER).start_span(
            f"node {node}", context=ctx, attributes={"node": str(node)[:80]}
        )

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        if (s := self._open.pop(run_id, None)) is not None:
            s.end()

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        if (s := self._open.pop(run_id, None)) is not None:
            # an interrupt (waiting for a job or an answer) is how a graph pauses, not a failure
            if type(error).__name__ != "GraphInterrupt":
                s.set_status(Status(StatusCode.ERROR, type(error).__name__))
            s.end()


class Langfuse:
    """Langfuse's LangChain callback for each run, when the deployment has Langfuse's keys
    (ADR-0050). Off on the desktop and wherever the keys are not set. With content capture off
    (the default) prompts and outputs are replaced before they leave; a person is a one-way hash."""

    def __init__(self, public_key: str, secret_key: str, base_url: str, capture: bool):
        self.on = bool(public_key and secret_key and base_url)
        self.capture = capture
        if not self.on:
            return
        from langfuse import Langfuse as Client
        from opentelemetry.sdk.trace import TracerProvider

        self.client = Client(
            public_key=public_key, secret_key=secret_key, base_url=base_url,
            tracer_provider=TracerProvider(),  # its own: prompts stay out of Tempo and the file
            mask=None if capture else _hide,
        )  # fmt: skip
        self.public_key = public_key
        log.info("Langfuse traces on (content %s)", "captured" if capture else "not captured")

    def callbacks(self, tenant_id: str, user_id: str, product_id: str) -> tuple[list[Any], dict]:
        """The run's callback and the metadata Langfuse reads (person, tags)."""
        if not self.on:
            return [], {}
        from langfuse.langchain import CallbackHandler

        person = hashlib.sha256(f"{tenant_id}:{user_id}".encode()).hexdigest()[:24]
        meta = {"langfuse_user_id": person, "langfuse_tags": [product_id]}
        return [CallbackHandler(public_key=self.public_key)], meta

    def flush(self) -> None:
        if self.on:
            self.client.flush()


def _hide(*, data: Any, **_: Any) -> Any:
    """What Langfuse stores in place of an input or output when content is not captured."""
    return NOT_CAPTURED if data is not None else None


OFF = Langfuse("", "", "", False)
