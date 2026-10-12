"""Every request resolves an identity (ADR-0011, ADR-0030)."""

import logging

from fastapi import Depends, HTTPException, Request
from wasifyai_platform_sdk import Identity

from wasifyai_api.auth import AuthError, verify_token
from wasifyai_api.config import get_settings

__all__ = ["Identity", "get_identity", "require_admin"]

log = logging.getLogger("wasifyai_api.identity")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


async def get_identity(request: Request) -> Identity:
    settings = get_settings()
    if settings.auth_mode == "stub":
        # the dev user may use everything, the admin area included (stub mode is local only)
        return Identity(
            tenant_id=settings.default_tenant_id, user_id=settings.dev_user_id, role="admin"
        )
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("sign in required")
    try:
        claims = verify_token(token.strip(), settings.api_auth_secret)
    except AuthError as exc:
        log.warning("rejected token: %s", exc)
        raise _unauthorized("invalid or expired token") from exc
    user = await request.app.state.users.resolve(
        settings.default_tenant_id, claims, settings.admin_email_set
    )
    return Identity(tenant_id=settings.default_tenant_id, user_id=user.id, role=user.role)


async def require_admin(identity: Identity = Depends(get_identity)) -> Identity:
    if identity.role != "admin":
        raise HTTPException(403, "admin only")
    return identity
