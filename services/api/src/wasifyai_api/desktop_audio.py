"""The speech runtime's routes for the window (ADR-0066, stage V1): is it installed, what would
installing fetch, set it up (after the person saw the size), use a copy found on this computer,
and the
models by task with their state."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity

from wasifyai_api.audio_runtime import AudioEngine, InstallError
from wasifyai_api.identity import get_identity
from wasifyai_api.services import services_of

router = APIRouter(prefix="/desktop/audio", tags=["desktop"])


def _engine(request: Request) -> AudioEngine:
    engine = services_of(request).audio
    if engine is None:
        raise HTTPException(404, "not available in this deployment")
    return engine


class ConfirmInstall(BaseModel):
    """What the person was shown and agreed to: the size of the download."""

    confirm_bytes: int


@router.get("")
async def audio_state(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return _engine(request).state()


@router.get("/models")
async def audio_models(
    request: Request, task: str | None = None, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    engine = _engine(request)
    return {"models": engine.models(task), "runtime": engine.state()}


@router.post("/install", status_code=202)
async def install_audio(
    body: ConfirmInstall, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    engine = _engine(request)
    try:
        engine.installer.start(body.confirm_bytes)
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return engine.state()


@router.post("/use-found")
async def use_found(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    engine = _engine(request)
    try:
        engine.installer.use_found()
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return engine.state()


@router.post("/stop")
async def stop_audio(request: Request, _: Identity = Depends(get_identity)) -> dict[str, bool]:
    return {"stopped": await _engine(request).stop()}
