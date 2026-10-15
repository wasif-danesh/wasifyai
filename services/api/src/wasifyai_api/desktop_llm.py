"""The local language engine's routes for the window (stage D, D1): is it installed, is a model
running. Choosing and starting a model arrives with the text provider (D2)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from wasifyai_platform_sdk import Identity

from wasifyai_api.identity import get_identity

router = APIRouter(prefix="/desktop", tags=["desktop"])


def _server(request: Request) -> Any:
    server = getattr(request.app.state, "llama_server", None)
    if server is None:
        raise HTTPException(404, "not available in this deployment")
    return server


@router.get("/language-engine")
async def language_engine(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return _server(request).state()


@router.post("/language-engine/stop")
async def stop_language_engine(
    request: Request, _: Identity = Depends(get_identity)
) -> dict[str, bool]:
    return {"stopped": await _server(request).stop()}
