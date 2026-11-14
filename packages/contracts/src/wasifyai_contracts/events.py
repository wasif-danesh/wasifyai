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


class ReasoningEvent(_Envelope):
    """A model's thinking text, as it streams (ADR-0082 decision 6, ADR-0083). Only a turn that
    asked for thinking has them (or a model that thinks whatever it is asked). It is shown
    collapsed under "Thinking", stored as a `reasoning` part, and never sent back to the model as
    context."""

    event: Literal["reasoning"] = "reasoning"
    node: str
    text: str


class InterruptEvent(_Envelope):
    event: Literal["interrupt"] = "interrupt"
    interrupt_id: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolCallEvent(_Envelope):
    """The assistant is calling a tool (ADR-0057): `id` ties it to its `tool_result`."""

    event: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultEvent(_Envelope):
    """A tool call finished. `output` is a small reference (an image id, search hits), never a
    file: the window fetches the creation itself, with a fresh link."""

    event: Literal["tool_result"] = "tool_result"
    id: str
    name: str
    status: Literal["ok", "refused", "error"]
    output: dict[str, Any] = Field(default_factory=dict)


class JobProgressEvent(_Envelope):
    event: Literal["job_progress"] = "job_progress"
    job_id: str
    capability: str
    status: Literal["queued", "running", "completed", "failed"]
    queue_position: int | None = None
    progress: float | None = Field(default=None, ge=0, le=1)
    preview_url: str | None = None
    # the assistant's tool call this job belongs to, so two jobs in one turn each find their card
    tool_call_id: str | None = None


class ErrorEvent(_Envelope):
    event: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool = False
    job_id: str | None = None


class DoneEvent(_Envelope):
    event: Literal["done"] = "done"
    outputs: dict[str, Any] = Field(default_factory=dict)


class CodeStateEvent(_Envelope):
    """A turn of a coding session changes state (ADR-0101, amendment of 2026-11-14). On a coding
    session's stream `thread_id` is the session and `run_id` the turn; `state: "done"` is the
    turn's end, and the stream stays open for the next turn."""

    event: Literal["code_state"] = "code_state"
    state: Literal["working", "turn_ended", "checking", "done"]
    why: str = ""  # how the turn ended: finished, stopped, step_limit, error, refused, ...
    result: str = ""  # the session's word: passed, failed, not_checked, could_not_check, or none
    detail: str = ""  # a sentence for a person
    cost_usd: float = 0.0
    # with `state: "done"`, in a session that may change files: how many files the turn changed
    changed: int | None = None
    # the check (stage C3). `round`: how many times the check has run in this turn so far (with
    # `checking`: the one that begins). `needs_you`: the turn stopped and a person must decide.
    # `check_why`: why the check has the result it has, when `why` is "finished" (no_change,
    # no_command, rounds_used, time_limit, missing_command, ...)
    round: int | None = None
    needs_you: bool | None = None
    check_why: str = ""


class CodeCheckEvent(_Envelope):
    """One run of the project's check has ended (ADR-0103; stage C3). The check is run by the
    app after a turn that changed files; a failed one goes back to the agent."""

    event: Literal["code_check"] = "code_check"
    id: str  # the check's row: its whole output is read with it
    round: int  # 1, 2, 3; 0 for a check the person ran by hand
    rounds: int  # how many rounds a turn may use
    command: str
    result: Literal["passed", "failed", "not_checked", "could_not_check"]
    why: str = ""  # for could_not_check and not_checked
    exit_code: int | None = None
    seconds: float = 0.0
    changed_tests: list[str] = Field(default_factory=list)  # tests the agent changed or deleted
    tail: str = ""  # the end of the output, cut to 4,000 characters


class CodeMessageEvent(_Envelope):
    """A message of the coding agent is complete. It replaces what the `token` events of that
    message built; those are not kept on a coding session's stream."""

    event: Literal["code_message"] = "code_message"
    text: str


class CodeRefusalEvent(_Envelope):
    """The model declined the request, in its own words. Not an error: the turn then ends with
    `code_state` `done`, `why: "refused"`."""

    event: Literal["code_refusal"] = "code_refusal"
    message: str
    category: str = ""


SseEvent = Annotated[
    NodeEvent
    | TokenEvent
    | ReasoningEvent
    | InterruptEvent
    | ToolCallEvent
    | ToolResultEvent
    | JobProgressEvent
    | ErrorEvent
    | DoneEvent
    | CodeStateEvent
    | CodeCheckEvent
    | CodeMessageEvent
    | CodeRefusalEvent,
    Field(discriminator="event"),
]

TERMINAL_EVENTS = ("done", "error")


class RunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    thread_id: UUID | None = None
    # A run id chosen by the client. A connection that breaks before the first event can then be
    # picked up again, and starting again with the same id attaches to that run, not a second one.
    run_id: UUID | None = None


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
