"""The `/mcp` endpoint (ADR-0069 decisions 1, 4, 5 and 11; spike S1): the SDK's server, stateless,
behind a gate that turns a connection secret into the connection, holds its rate, and logs the
call. Which tools a connection sees is decided per request from its scopes."""

import asyncio
import json
import logging
import time
from collections import deque
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from mcp_types import Tool as MCPTool
from starlette.responses import JSONResponse
from starlette.routing import Route
from wasifyai_platform_sdk.actions import Action, ActionExecutor

from wasifyai_api.auth import AuthError
from wasifyai_api.mcp_server.approvals import ApprovalDesk
from wasifyai_api.mcp_server.calls import run_call
from wasifyai_api.mcp_server.connections import ActivityEntry, Connection, ConnectionsService
from wasifyai_api.mcp_server.tools import scope_needed, tools_of

log = logging.getLogger(__name__)

MAX_BODY = 1 << 20  # 1 MiB (ADR-0069 decision 11); the SDK's default is 4
INSTRUCTIONS = (
    "Wasify AI runs on the person's own computer. Each tool is one thing the app can do; what "
    "takes a while answers with a job_id to follow with job_status or job_wait. Deleting and "
    "anything that needs the person's word is approved in the Wasify AI window, never here: a "
    "needs_approval answer carries an approval_id to follow with approval_status. Results name "
    "creations by id; files stay in the app. Never ask the person for a secret or a path to a "
    "folder the connection may not use."
)
current_connection: ContextVar[Connection | None] = ContextVar("mcp_connection", default=None)
TOUCH_EVERY_S = 60.0


class WasifyMCP(MCPServer):
    """The SDK's server with the catalogue's tools, offered per connection by scope."""

    def __init__(
        self,
        executor: ActionExecutor,
        desk: ApprovalDesk,
        events: Any,
        connections: ConnectionsService | None = None,
    ):
        super().__init__("wasify", instructions=INSTRUCTIONS)
        self.executor = executor
        self.desk = desk
        self.events = events
        self.connections = connections
        self.catalogue: dict[str, Action] = {}

        async def body(action: Action, arguments: dict[str, Any], ctx: Context) -> Any:
            connection = current_connection.get()
            if connection is None:
                raise ToolError("no connection")
            store = self.connections.store if self.connections is not None else None
            return await run_call(executor, desk, events, connection, action, arguments, ctx, store)

        for name, (action, tool) in tools_of(executor.registry, body).items():
            self.catalogue[name] = action
            self._tool_manager._tools[name] = tool  # noqa: SLF001 - a prebuilt Tool; pinned SDK

        async def approval_status(approval_id: str, wait_seconds: int = 0) -> CallToolResult:
            """Follow an approval the person was asked for in the Wasify AI window: pending,
            approved (with what the action came to, or its job_id), denied or expired. Waits up
            to wait_seconds (at most 50) for the answer."""
            connection = current_connection.get()
            p = await desk.wait(approval_id, max(0, min(int(wait_seconds), 50)))
            if p is None or connection is None or p.connection_id != connection.id:
                unknown = {"approval_id": approval_id, "status": "unknown"}
                return CallToolResult(
                    content=[TextContent(text=f"Approval {approval_id}: unknown.")],
                    structured_content=unknown,
                    is_error=False,
                )
            out = p.public()
            # the sentence carries the ids too, for a client that hands its model the text alone
            words = f"Approval {approval_id}: {p.status}."
            if out.get("job_id"):
                words += f" job_id: {out['job_id']}"
            if out.get("text"):
                words += f" {out['text']}"
            return CallToolResult(
                content=[TextContent(text=words)], structured_content=out, is_error=False
            )

        self.add_tool(
            approval_status,
            name="approval_status",
            annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
        )

    def _offered(self, name: str, connection: Connection | None) -> bool:
        if name == "approval_status":
            return True
        action = self.catalogue.get(name)
        if action is None or connection is None:
            return False
        return scope_needed(action) in connection.scopes

    async def list_tools(self) -> list[MCPTool]:
        connection = current_connection.get()
        return [t for t in await super().list_tools() if self._offered(t.name, connection)]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context | None = None
    ) -> Any:
        if not self._offered(name, current_connection.get()):
            raise ToolError(f"{name} is not offered to this connection.")
        result = await super().call_tool(name, arguments, context)
        assert isinstance(result, CallToolResult) or result is not None
        return result


class RateLimiter:
    """Calls per minute per connection, in memory (one engine process)."""

    def __init__(self) -> None:
        self._calls: dict[str, deque[float]] = {}

    def allow(self, key: str, per_minute: int) -> bool:
        now = time.monotonic()
        q = self._calls.setdefault(key, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= per_minute:
            return False
        q.append(now)
        return True


def _json(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class ConnectionGate:
    """Pure ASGI around the SDK's app: bearer to connection, rate, body size, activity."""

    def __init__(self, inner: Any, connections: ConnectionsService, server: WasifyMCP) -> None:
        self.inner = inner
        self.connections = connections
        self.server = server
        self.limiter = RateLimiter()
        self._touched: dict[str, float] = {}

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth = headers.get(b"authorization", b"").decode()
        scheme, _, credential = auth.partition(" ")
        if scheme.lower() != "bearer" or not credential.strip():
            return await _json(401, "a connection secret is required")(scope, receive, send)
        try:
            connection = await self.connections.verify(credential.strip())
        except AuthError as exc:
            log.warning("mcp: rejected credential: %s", exc)
            return await _json(401, "this connection secret is not accepted")(scope, receive, send)
        if not self.limiter.allow(connection.id, connection.rate_per_minute):
            return await _json(429, "too many calls for this connection; wait a minute")(
                scope, receive, send
            )
        chunks: list[dict[str, Any]] = []
        size = 0
        method, tool = scope.get("method", ""), ""
        if scope["method"] == "POST":
            more = True
            while more:
                m = await receive()
                chunks.append(m)
                size += len(m.get("body", b""))
                if size > MAX_BODY:
                    return await _json(413, "the request is larger than 1 MiB")(
                        scope, receive, send
                    )
                more = m.get("more_body", False)
            raw = b"".join(c.get("body", b"") for c in chunks)
            try:
                body = json.loads(raw)
                if isinstance(body, dict):
                    method = str(body.get("method") or method)
                    params = body.get("params") or {}
                    if isinstance(params, dict) and isinstance(params.get("name"), str):
                        tool = params["name"]
            except ValueError:
                pass
        it = iter(chunks)

        async def replay() -> dict[str, Any]:
            try:
                return next(it)
            except StopIteration:
                return await receive()

        status = {"code": 0, "bytes": 0}

        async def watch(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
            elif message["type"] == "http.response.body":
                status["bytes"] += len(message.get("body", b""))
            await send(message)

        started = time.monotonic()
        token = current_connection.set(connection)
        try:
            await self.inner(scope, replay, watch)
        finally:
            current_connection.reset(token)
            entry = ActivityEntry(
                connection_id=connection.id, method=method, tool=tool,
                status="ok" if status["code"] < 400 else str(status["code"]),
                duration_ms=int((time.monotonic() - started) * 1000), bytes=status["bytes"],
            )  # fmt: skip
            asyncio.create_task(self._record(connection, entry))

    async def _record(self, connection: Connection, entry: ActivityEntry) -> None:
        try:
            await self.connections.store.record(entry)
            now = time.monotonic()
            if now - self._touched.get(connection.id, 0.0) > TOUCH_EVERY_S:
                self._touched[connection.id] = now
                await self.connections.touch(connection)
        except Exception:
            log.exception("mcp: could not record the call")


def build_server(
    executor: ActionExecutor,
    desk: ApprovalDesk,
    events: Any,
    connections: ConnectionsService | None = None,
) -> WasifyMCP:
    server = WasifyMCP(executor, desk, events, connections)
    # the SDK's own Starlette app is not mounted (FastAPI would not run its lifespan); this call
    # builds the session manager the gate wraps, with the loopback Host/Origin checks on
    server.streamable_http_app(
        stateless_http=True, json_response=False, max_request_body_size=MAX_BODY
    )
    return server


class LazyGate:
    """The route is registered when the app is made; the server exists once the lifespan built
    the executor. Until then the endpoint says so."""

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        services = getattr(scope["app"].state, "services", None)
        gate = services.mcp_gate if services is not None else None
        if gate is None:
            return await _json(503, "the engine is still starting")(scope, receive, send)
        await gate(scope, receive, send)


def mount(app: FastAPI) -> None:
    app.router.routes.append(Route("/mcp", endpoint=LazyGate(), methods=["POST", "GET", "DELETE"]))


def attach(services: Any, server: WasifyMCP, connections: ConnectionsService) -> None:
    """Put the built server and its gate into the engine's services (`ApiServices`)."""
    services.mcp = server
    services.mcp_gate = ConnectionGate(
        StreamableHTTPASGIApp(server.session_manager), connections, server
    )
