"""Who is calling, and what they may do (stage F3 of the 2026-10-27 plan; ADR-0092).

`Identity` is the tenant-and-user pair product code works with. A `Principal` is what the request
edge resolves: the same pair plus the kind of caller, its scopes and its origin. A person in the
window is a principal with every scope; an MCP connection or an API key is one with the scopes it
was given. Product code keeps reading `Identity`; only the request edge, the executor and the
audit log look at the principal.

Scopes are the catalogue's groups plus `read` (`scope_of` in `actions.model` says which an action
needs). A principal outside a scope is refused with a sentence, never with a stack trace."""

import re
from dataclasses import dataclass, field
from typing import Literal

from wasifyai_platform_sdk.identity import Identity

Kind = Literal["person", "connection", "api_key"]
Scope = Literal["read", "make", "library", "notebooks", "voices", "models", "admin"]

SCOPES: tuple[Scope, ...] = ("read", "make", "library", "notebooks", "voices", "models", "admin")
# what each scope lets a caller do, in the words a screen or a 403 uses
SCOPE_WORDS: dict[str, str] = {
    "read": "see what this app can do and follow jobs",
    "make": "make pictures, videos, speech and music, and start training",
    "library": "list, open and delete creations",
    "notebooks": "read and change notebooks",
    "voices": "list, add and delete voices",
    "models": "list and download models",
    "admin": "manage the service",
}
ALL_SCOPES: frozenset[str] = frozenset(SCOPES)
USER_SCOPES: frozenset[str] = ALL_SCOPES - {"admin"}
KIND_WORDS: dict[str, str] = {"person": "person", "connection": "connection", "api_key": "key"}

# who is asking: the person in the window, the assistant, an MCP connection, an API key
ORIGIN_PATTERN = re.compile(
    r"^(window|assistant|mcp:[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}|api:[A-Za-z0-9][A-Za-z0-9._-]{0,63})$"
)


def parse_origin(origin: str) -> str:
    """`window`, `assistant`, `mcp:<connection>` or `api:<key id>`. Anything else is a bug."""
    if not ORIGIN_PATTERN.match(origin):
        raise ValueError(
            f"origin must be window, assistant, mcp:<connection> or api:<key>, not {origin!r}"
        )
    return origin


@dataclass(frozen=True)
class Principal:
    kind: Kind
    tenant_id: str
    user_id: str
    role: str = "user"  # "user" or "admin" (ADR-0030): the person's role, never widened by a key
    scopes: frozenset[str] = field(default_factory=frozenset)
    origin: str = "window"
    connection_id: str | None = None  # the connection or key this credential belongs to

    def __post_init__(self) -> None:
        unknown = set(self.scopes) - ALL_SCOPES
        if unknown:
            raise ValueError(f"unknown scopes: {sorted(unknown)}")
        parse_origin(self.origin)
        if self.kind == "person" and self.origin != "window":
            raise ValueError("a person's origin is the window")
        if self.kind != "person" and self.origin == "window":
            raise ValueError(f"a {KIND_WORDS[self.kind]} does not come through the window")
        if "admin" in self.scopes and self.role != "admin":
            raise ValueError("the admin scope needs the admin role")

    @classmethod
    def person(cls, tenant_id: str, user_id: str, role: str = "user") -> "Principal":
        """The person signed in to the window: everything their role allows."""
        scopes = ALL_SCOPES if role == "admin" else USER_SCOPES
        return cls("person", tenant_id, user_id, role, scopes, "window")

    @property
    def identity(self) -> Identity:
        return Identity(self.tenant_id, self.user_id, self.role)

    @property
    def noun(self) -> str:
        """`person`, `connection` or `key`: for a sentence."""
        return KIND_WORDS[self.kind]

    def may(self, scope: str) -> bool:
        return scope in self.scopes

    def refusal(self, scope: str) -> str:
        """Why a call outside `scope` is refused, as one sentence for the caller."""
        return f"This {self.noun} may not {SCOPE_WORDS.get(scope, scope)} (the {scope} scope)."
