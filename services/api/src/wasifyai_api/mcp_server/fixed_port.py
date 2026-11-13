"""The opt-in fixed HTTP port (ADR-0069 decision 2, stage M3): for a client that cannot run the
stdio launcher. Off by default. When the person turns it on, the engine listens on one more
loopback port that serves nothing but `/mcp` through the same gate; the port is remembered in the
settings store and opened again at the next launch. The client holds a connection secret of its
own (the HTTP snippets name a variable for it)."""

import asyncio
import logging
import socket
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route

log = logging.getLogger(__name__)

KEY = "mcp.fixed_port"
MIN_PORT, MAX_PORT = 1024, 65535


class FixedPort:
    def __init__(self, gate: Any, settings: Any):
        self._gate = gate  # the `/mcp` ASGI gate the main app uses
        self._settings = settings
        self.port: int | None = None
        self._server: Any = None
        self._task: asyncio.Task[Any] | None = None

    async def saved(self) -> int | None:
        value = await self._settings.get(KEY)
        return int(value) if isinstance(value, int) and MIN_PORT <= value <= MAX_PORT else None

    async def start_if_saved(self) -> None:
        try:
            port = await self.saved()
        except Exception as e:  # noqa: BLE001 - a database not migrated yet must not stop the engine
            log.warning("the fixed MCP port's setting could not be read: %s", e)
            return
        if port is not None:
            try:
                await self.start(port, remember=False)
            except OSError as e:
                log.warning("the fixed MCP port %s could not be opened: %s", port, e)

    async def start(self, port: int, *, remember: bool = True) -> None:
        if not MIN_PORT <= port <= MAX_PORT:
            raise ValueError(f"choose a port between {MIN_PORT} and {MAX_PORT}")
        import uvicorn

        await self.stop(forget=False)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))  # loopback only, as the engine's own port
        except OSError:
            sock.close()
            raise
        app = Starlette(
            routes=[Route("/mcp", endpoint=self._gate, methods=["POST", "GET", "DELETE"])]
        )
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
        self._server = server
        self._task = asyncio.create_task(server.serve(sockets=[sock]))
        for _ in range(200):  # wait until it listens, so Settings can say so
            if server.started:
                break
            await asyncio.sleep(0.01)
        self.port = port
        if remember:
            await self._settings.put(KEY, port, "window")

    async def stop(self, *, forget: bool = True) -> None:
        if self._server is not None:
            self._server.should_exit = True
            if self._task is not None:
                try:
                    await asyncio.wait_for(self._task, 5)
                except (TimeoutError, asyncio.CancelledError):
                    self._task.cancel()
            self._server, self._task = None, None
        self.port = None
        if forget:
            await self._settings.put(KEY, None, "window")

    def state(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "url": f"http://127.0.0.1:{self.port}/mcp" if self.port else None,
        }
