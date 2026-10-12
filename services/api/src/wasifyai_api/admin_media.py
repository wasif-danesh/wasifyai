"""Admin routes for media access (ADR-0025): which backend runs each product's media capability.

API keys are write-only: they arrive in a request body, are encrypted, and appear nowhere else."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from wasifyai_api.admin import AuditEntry
from wasifyai_api.identity import Identity, require_admin
from wasifyai_api.media_access import (
    MediaAccess,
    MediaAccessError,
    MediaBindingIn,
    MediaList,
    MediaView,
)

router = APIRouter(prefix="/admin/media", tags=["admin"])


class MediaTestOutcome(BaseModel):
    ok: bool
    message: str
    latency_ms: int


def _media(request: Request) -> MediaAccess:
    return request.app.state.media


async def _audit(request: Request, who: Identity, action: str, target: str, **detail) -> None:
    await request.app.state.admin.audit(
        who.tenant_id,
        AuditEntry(
            id="", actor_user_id=who.user_id, action=action, target_type="media_capability",
            target_id=target, detail=detail,
        ),
    )  # fmt: skip


def _describe(b: MediaBindingIn) -> dict:
    """What goes in the audit log: the settings, never the key."""
    return {"backend": b.backend, "config": b.config, "key_provided": bool(b.api_key)}


@router.get("", response_model=MediaList)
async def list_media(request: Request, who: Identity = Depends(require_admin)) -> MediaList:
    return await _media(request).list(who.tenant_id)


@router.put("/{product_id}/{capability}", response_model=MediaView)
async def set_media(
    product_id: str,
    capability: str,
    binding: MediaBindingIn,
    request: Request,
    who: Identity = Depends(require_admin),
) -> MediaView:
    try:
        view = await _media(request).set(
            who.tenant_id, product_id, capability, binding, who.user_id
        )
    except MediaAccessError as exc:
        raise HTTPException(422, str(exc)) from exc
    await _audit(
        request, who, "admin.media.update", f"{product_id}/{capability}", **_describe(binding)
    )
    return view


@router.post("/{product_id}/{capability}/test", response_model=MediaTestOutcome)
async def test_media(
    product_id: str,
    capability: str,
    request: Request,
    binding: MediaBindingIn | None = None,
    who: Identity = Depends(require_admin),
) -> MediaTestOutcome:
    try:
        outcome = await _media(request).test(who.tenant_id, product_id, capability, binding)
    except MediaAccessError as exc:
        raise HTTPException(422, str(exc)) from exc
    await _audit(
        request, who, "admin.media.test", f"{product_id}/{capability}",
        ok=outcome.ok, candidate=_describe(binding) if binding else None,
    )  # fmt: skip
    return MediaTestOutcome(ok=outcome.ok, message=outcome.message, latency_ms=outcome.latency_ms)


@router.post("/{product_id}/{capability}/reset", response_model=MediaView)
async def reset_media(
    product_id: str, capability: str, request: Request, who: Identity = Depends(require_admin)
) -> MediaView:
    try:
        view = await _media(request).reset(who.tenant_id, product_id, capability)
    except MediaAccessError as exc:
        raise HTTPException(422, str(exc)) from exc
    await _audit(request, who, "admin.media.reset", f"{product_id}/{capability}")
    return view
