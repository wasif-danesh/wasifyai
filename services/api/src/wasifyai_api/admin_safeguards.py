"""Admin routes for the safeguards switch (ADR-0047)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import need

from wasifyai_api.admin import AuditEntry
from wasifyai_api.identity import Identity, require_admin
from wasifyai_api.safeguards import ForcedOn, Safeguards, SafeguardsStatus
from wasifyai_api.services import services_of

router = APIRouter(prefix="/admin/safeguards", tags=["admin"])


class SafeguardsIn(BaseModel):
    enabled: bool


def _safeguards(request: Request) -> Safeguards:
    return need(services_of(request).safeguards, "the safeguards")


@router.get("", response_model=SafeguardsStatus)
async def get_safeguards(
    request: Request, who: Identity = Depends(require_admin)
) -> SafeguardsStatus:
    return await _safeguards(request).status()


@router.put("", response_model=SafeguardsStatus)
async def set_safeguards(
    body: SafeguardsIn, request: Request, who: Identity = Depends(require_admin)
) -> SafeguardsStatus:
    guard = _safeguards(request)
    before = await guard.enabled()
    try:
        status = await guard.set(body.enabled, who.user_id)
    except ForcedOn:
        raise HTTPException(409, "The safeguards are forced on by this deployment.") from None
    await need(services_of(request).admin, "the admin store").audit(
        who.tenant_id,
        AuditEntry(
            id="", actor_user_id=who.user_id, action="admin.safeguards.update",
            target_type="system", target_id="safeguards",
            detail={"from": before, "to": status.enabled},
        ),
    )  # fmt: skip
    return status
