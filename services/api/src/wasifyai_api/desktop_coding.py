"""The coding engine's routes for the window (stage C1a of the coding agent's plan): is it set up,
is it running, and start and stop, the way `/desktop/language-engine` does for the language
engine. Nothing here reaches the Agent Server's own API or gives out its session key (ADR-0101,
decision 4): from stage C1b the window calls the coding product's actions, and the product starts
the server when a session needs it."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from wasifyai_platform_sdk import Identity

from wasifyai_api.coding_server import CodingError, CodingServer
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


@router.post("/coding-engine/start")
async def start_coding_engine(
    request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    server = _server(request)
    try:
        await server.ensure_running()
    except CodingError as e:
        raise HTTPException(409, e.message) from None
    return await _state(server)


@router.post("/coding-engine/stop")
async def stop_coding_engine(
    request: Request, _: Identity = Depends(get_identity)
) -> dict[str, bool]:
    return {"stopped": await _server(request).stop()}
