"""The coding engine's routes for the window: is it set up, is it running, and stop it (which gives
its memory back; the next message of a coding session starts it again). Nothing here reaches the
Agent Server's own API or gives out its session key (ADR-0101, decision 4).

There is no route that starts it. The coding product starts it when a session needs it, with the
folders that session may reach (stage C1b). A start from outside would have to guess those
folders, and a start with other folders than the running server has starts it again and cuts off
every session in the middle of its turn (`docs/spikes/coding-c1b.md`, "Decided")."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from wasifyai_platform_sdk import Identity

from wasifyai_api.coding_server import CodingServer
from wasifyai_api.identity import get_identity
from wasifyai_api.services import services_of

router = APIRouter(prefix="/desktop", tags=["desktop"])


def _server(request: Request) -> CodingServer:
    server = services_of(request).coding_server
    if server is None:
        raise HTTPException(404, "not available in this deployment")
    return server


async def _state(server: CodingServer) -> dict[str, Any]:
    return {**server.state(), "memory_bytes": await server.memory_bytes()}


@router.get("/coding-engine")
async def coding_engine(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return await _state(_server(request))


@router.post("/coding-engine/stop")
async def stop_coding_engine(
    request: Request, _: Identity = Depends(get_identity)
) -> dict[str, bool]:
    server = _server(request)
    sessions = services_of(request).code_sessions
    if sessions is not None:  # turns in flight end as "stopped", not as a lost connection
        await sessions.stop_all()
    return {"stopped": await server.stop()}
