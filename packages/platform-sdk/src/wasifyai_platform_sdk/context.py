"""Per-run request context (tenant, product, user, run). Set once by the runtime; read by
capabilities so usage events, job payloads and storage keys always carry tenancy (ADR-0011)."""

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class RunContext:
    tenant_id: str
    product_id: str
    user_id: str
    run_id: str | None = None
    thread_id: str | None = None
    role: str = "user"  # the person's role (ADR-0030): an admin's jobs are not held to the limit


_current: ContextVar[RunContext | None] = ContextVar("wasifyai_run_context", default=None)


def set_context(ctx: RunContext) -> Token:
    return _current.set(ctx)


def reset_context(token: Token) -> None:
    _current.reset(token)


def current_context() -> RunContext | None:
    return _current.get()


def require_context() -> RunContext:
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError("no RunContext: capabilities must be called inside a run")
    return ctx
