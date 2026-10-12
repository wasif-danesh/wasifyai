"""Who is making a request. Resolved on every request (ADR-0011)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    tenant_id: str
    user_id: str
    role: str = "user"  # "user" or "admin" (ADR-0030)
