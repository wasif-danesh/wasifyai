"""Prometheus metrics for the API (ADR-0048).

Served on a separate port (`METRICS_PORT`, default 9464) that only the cluster's Prometheus reaches:
the public API keeps its rule that every endpoint resolves an identity. Labels are bounded and
carry no user data: a product id, an outcome, an error or refusal code, an HTTP route template.
Never a user id, a prompt or text."""

import logging
import time

from prometheus_client import Counter, Histogram, start_http_server
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger(__name__)

HTTP_REQUESTS = Counter("wdai_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_SECONDS = Histogram(
    "wdai_http_request_seconds",
    "HTTP request duration",
    ["route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300),
)
RUNS = Counter(
    "wdai_runs_total", "Runs that stopped, by product and outcome", ["product", "outcome"]
)
RUN_ERRORS = Counter("wdai_run_errors_total", "Runs that ended in an error", ["product", "code"])
REFUSALS = Counter(
    "wdai_refusals_total", "Requests refused by a safeguard or a rule", ["product", "category"]
)
UPLOADS = Counter("wdai_uploads_total", "Uploads", ["kind", "outcome"])


def record_run(product: str, outcome: str, code: str = "", refusal: str = "") -> None:
    """One run stopped: `done`, `refused` or `error`."""
    RUNS.labels(product, outcome).inc()
    if outcome == "error":
        RUN_ERRORS.labels(product, code or "unknown").inc()
    if outcome == "refused":
        REFUSALS.labels(product, refusal or "unknown").inc()


class MetricsMiddleware:
    """Counts and times requests by route template (`/products/{id}/runs`), not by path."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def tap(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, tap)
        finally:
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            HTTP_REQUESTS.labels(scope["method"], route, str(status)).inc()
            HTTP_SECONDS.labels(route).observe(time.perf_counter() - started)


def serve(port: int) -> None:
    """Start the metrics listener (a no-op when the port is 0)."""
    if port <= 0:
        return
    try:
        start_http_server(port)
        log.info("metrics on :%d", port)
    except OSError:
        log.warning("metrics port %d is busy: no metrics from this process", port)
