"""The Indian-language speech engine's routes for the window (voice languages plan, L5): is it
set up, what would setting it up fetch, set it up (after the person saw the size), stop it. The
model files are in Models."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity

from wasifyai_api.audio_runtime import AudioEngine, InstallError
from wasifyai_api.identity import get_identity
from wasifyai_api.indic_runtime import IndicSidecar
from wasifyai_api.services import services_of

router = APIRouter(prefix="/desktop/indic", tags=["desktop"])


def _sidecar(request: Request) -> IndicSidecar:
    engine: AudioEngine | None = services_of(request).audio
    sidecar = getattr(engine, "indic_sidecar", None) if engine is not None else None
    if sidecar is None:
        raise HTTPException(404, "not available in this deployment")
    return sidecar  # type: ignore[no-any-return]


class ConfirmInstall(BaseModel):
    """What the person was shown and agreed to: the size of the download."""

    confirm_bytes: int


@router.get("")
async def indic_state(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return _sidecar(request).state()


@router.post("/install", status_code=202)
async def install_indic(
    body: ConfirmInstall, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    sidecar = _sidecar(request)
    try:
        sidecar.installer.start(body.confirm_bytes)
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return sidecar.state()


@router.post("/stop")
async def stop_indic(request: Request, _: Identity = Depends(get_identity)) -> dict[str, bool]:
    return {"stopped": await _sidecar(request).stop()}
