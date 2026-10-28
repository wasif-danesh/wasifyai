"""Every request resolves a principal, and from it an identity (ADR-0011, ADR-0030, ADR-0092).

    get_principal     who is calling: a person (an HS256 token), or a connection or an API key
                      (a credential one of `app.state.credential_verifiers` knows by its prefix)
    get_identity      the tenant-and-user pair product code works with (unchanged)
    require_scope     a route that only principals with this scope may call
    require_admin     admin role and the admin scope

Stub mode (local development) is one admin person with every scope. A credential nobody can
verify is a 401 with a sentence; a principal outside a scope is a 403 with a sentence."""

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from fastapi import Depends, HTTPException, Request
from wasifyai_platform_sdk import Identity, Principal

from wasifyai_api.auth import AuthError, verify_token
from wasifyai_api.config import get_settings
from wasifyai_api.services import services_of

__all__ = [
    "CredentialVerifier",
    "Identity",
    "Principal",
    "get_identity",
    "get_principal",
    "require_admin",
    "require_scope",
]

log = logging.getLogger("wasifyai_api.identity")


class CredentialVerifier(Protocol):
    """Turns a bearer credential that starts with `prefix` into a principal, or raises
    `AuthError`. Registered in `app.state.credential_verifiers` by prefix (none is registered yet;
    a connection secret of the MCP server would be one)."""

    async def verify(self, credential: str, request: Request) -> Principal: ...


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


async def _person(token: str, request: Request) -> Principal:
    settings = get_settings()
    try:
        claims = verify_token(token, settings.api_auth_secret)
    except AuthError as exc:
        log.warning("rejected token: %s", exc)
        raise _unauthorized("invalid or expired token") from exc
    user = await services_of(request).users.resolve(
        settings.default_tenant_id, claims, settings.admin_email_set
    )
    return Principal.person(settings.default_tenant_id, user.id, user.role)


async def get_principal(request: Request) -> Principal:
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached
    settings = get_settings()
    if settings.auth_mode == "stub":
        # the dev user may use everything, the admin area included (stub mode is local only)
        principal = Principal.person(settings.default_tenant_id, settings.dev_user_id, "admin")
    else:
        scheme, _, credential = request.headers.get("authorization", "").partition(" ")
        credential = credential.strip()
        if scheme.lower() != "bearer" or not credential:
            raise _unauthorized("sign in required")
        verifiers: dict[str, CredentialVerifier] = services_of(request).credential_verifiers
        verifier = next((v for p, v in verifiers.items() if credential.startswith(p)), None)
        if verifier is None:
            principal = await _person(credential, request)
        else:
            try:
                principal = await verifier.verify(credential, request)
            except AuthError as exc:
                log.warning("rejected credential: %s", exc)
                raise _unauthorized("this connection is not accepted") from exc
    request.state.principal = principal
    return principal


async def get_identity(request: Request) -> Identity:
    return (await get_principal(request)).identity


def _principal_of(request: Request, identity: Identity) -> Principal:
    """The principal behind an identity. `require_scope` and `require_admin` go through
    `get_identity`, so a test or a host that overrides it (one person, every scope) keeps
    working; when `get_principal` resolved the request, its principal is the answer."""
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal) and principal.identity == identity:
        return principal
    return Principal.person(identity.tenant_id, identity.user_id, identity.role)


def require_scope(scope: str) -> Callable[..., Awaitable[Principal]]:
    """A dependency: the principal, when it has `scope`; otherwise 403 with the reason."""

    async def dependency(request: Request, identity: Identity = Depends(get_identity)) -> Principal:
        principal = _principal_of(request, identity)
        if not principal.may(scope):
            raise HTTPException(403, principal.refusal(scope))
        return principal

    return dependency


async def require_person(request: Request, identity: Identity = Depends(get_identity)) -> Identity:
    """The person themself (a token from the window or the web app), never a connection or an
    API key: what Settings that add outside software or spend the person's trust need
    (ADR-0070 decision 2)."""
    principal = _principal_of(request, identity)
    if principal.kind != "person":
        raise HTTPException(403, "only the person can change this, in the app")
    return identity


async def require_admin(request: Request, identity: Identity = Depends(get_identity)) -> Identity:
    principal = _principal_of(request, identity)
    if principal.role != "admin":
        raise HTTPException(403, "admin only")
    if not principal.may("admin"):
        raise HTTPException(403, principal.refusal("admin"))
    return identity
