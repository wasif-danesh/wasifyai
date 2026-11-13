"""`/components`: one route family for every optional component (stage F2). The window's tray and
every "set up" card read and drive components through it; a status change is also sent on
`/desktop/events` as a `component` event, so a screen follows an install without asking."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk.installer import Component, InstallError, Registry

from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.services import services_of

router = APIRouter(prefix="/components", tags=["components"])


def _registry(request: Request) -> Registry:
    found = services_of(request).components
    if found is None:
        raise HTTPException(404, "There are no components to set up here.")
    return found


def _component(request: Request, component_id: str) -> Component:
    found = _registry(request).components.get(component_id)
    if found is None:
        raise HTTPException(404, "There is no such component.")
    return found


def _view(c: Component) -> dict[str, Any]:
    # what the person may ask of it besides setting it up: a part whose service cannot yet stop,
    # repair or remove it says so, and the window offers only what works
    can = {k: bool(getattr(c, f"can_{k}", True)) for k in ("stop", "repair", "remove")}
    return {"id": c.id, "title": c.title, "status": c.status(), "can": can}


@router.get("")
async def list_components(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return {"components": [_view(c) for c in _registry(request).components.values()]}


@router.get("/{component_id}")
async def get_component(
    component_id: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    return _view(_component(request, component_id))


class InstallIn(BaseModel):
    confirm_bytes: int | None = None  # the size the person saw; None only for a repair
    repair: bool = False


@router.post("/{component_id}/install")
async def install_component(
    component_id: str, body: InstallIn, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    c = _component(request, component_id)
    if body.confirm_bytes is None and not body.repair:
        raise HTTPException(422, "Say the size you were shown, to set it up.")
    try:
        c.install(body.confirm_bytes, repair=body.repair)
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return _view(c)


@router.post("/{component_id}/cancel")
async def cancel_component(
    component_id: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    c = _component(request, component_id)
    c.cancel()
    await c.wait()
    return _view(c)


@router.post("/{component_id}/uninstall")
async def uninstall_component(
    component_id: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    c = _component(request, component_id)
    try:
        freed = c.uninstall()
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return {**_view(c), "freed_bytes": freed}
