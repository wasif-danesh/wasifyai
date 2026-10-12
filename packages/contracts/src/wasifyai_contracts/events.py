"""SSE event models. Source of truth for docs/contracts/sse-events.md."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(UTC).isoformat()


class _Envelope(BaseModel):
    run_id: UUID
    thread_id: UUID
    seq: int
    ts: str = Field(default_factory=_now)


class NodeEvent(_Envelope):
    event: Literal["node"] = "node"
    node: str
    status: Literal["started", "completed"]
    label: str = ""


class TokenEvent(_Envelope):
    event: Literal["token"] = "token"
    node: str
    text: str


class InterruptEvent(_Envelope):
    event: Literal["interrupt"] = "interrupt"
    interrupt_id: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class JobProgressEvent(_Envelope):
    event: Literal["job_progress"] = "job_progress"
    job_id: str
    capability: str
    status: Literal["queued", "running", "completed", "failed"]
    queue_position: int | None = None
    progress: float | None = Field(default=None, ge=0, le=1)
    preview_url: str | None = None


class ErrorEvent(_Envelope):
    event: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool = False
    job_id: str | None = None


class DoneEvent(_Envelope):
    event: Literal["done"] = "done"
    outputs: dict[str, Any] = Field(default_factory=dict)


SseEvent = Annotated[
    NodeEvent | TokenEvent | InterruptEvent | JobProgressEvent | ErrorEvent | DoneEvent,
    Field(discriminator="event"),
]

TERMINAL_EVENTS = ("done", "error")


class RunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    thread_id: UUID | None = None


class ResumeRequest(BaseModel):
    interrupt_id: str | None = None
    value: Any = None


def format_sse(event: _Envelope) -> str:
    """Serialise an event as one SSE message (id = seq)."""
    name = getattr(event, "event")  # noqa: B009
    return f"id: {event.seq}\nevent: {name}\ndata: {event.model_dump_json(exclude={'event'})}\n\n"


def format_sse_dict(event: dict[str, Any]) -> str:
    """Serialise a stored event (a dict with `event` and `seq`) as one SSE message."""
    import json

    body = {k: v for k, v in event.items() if k != "event"}
    return f"id: {event['seq']}\nevent: {event['event']}\ndata: {json.dumps(body)}\n\n"
