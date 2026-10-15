"""API tokens minted by the web app's BFF (ADR-0030).

The browser holds an Auth.js session cookie; the BFF turns it into a short-lived HS256 token for
each API call. This module only verifies; it never trusts a claim before the signature, issuer,
audience and expiry have checked out.
"""

from dataclasses import dataclass

import jwt

ISSUER = "wasifyai-web"
AUDIENCE = "wasifyai-api"
MIN_SECRET_BYTES = 32
# `desktop`: the token the desktop shell mints for its own window (ADR-0056)
PROVIDERS = frozenset({"google", "github", "microsoft-entra-id", "desktop"})


class AuthError(Exception):
    """The token cannot be accepted. The message is safe to log, not to show to the caller."""


@dataclass(frozen=True)
class Claims:
    provider: str
    account_id: str
    email: str | None
    email_verified: bool
    name: str | None
    image: str | None


def verify_token(token: str, secret: str) -> Claims:
    if len(secret.encode()) < MIN_SECRET_BYTES:
        raise AuthError("API_AUTH_SECRET is missing or shorter than 32 bytes")
    try:
        data = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],  # never read the algorithm from the token
            issuer=ISSUER,
            audience=AUDIENCE,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            leeway=5,
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"invalid token: {type(exc).__name__}") from exc
    provider, _, account_id = str(data["sub"]).partition(":")
    if provider not in PROVIDERS or not account_id or len(account_id) > 256:
        raise AuthError("invalid token: bad subject")
    email = data.get("email")
    return Claims(
        provider=provider,
        account_id=account_id,
        email=email.strip() if isinstance(email, str) and email.strip() else None,
        email_verified=data.get("email_verified") is True,
        name=data["name"] if isinstance(data.get("name"), str) else None,
        image=data["picture"] if isinstance(data.get("picture"), str) else None,
    )
