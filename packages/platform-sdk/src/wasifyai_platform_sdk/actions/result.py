"""What `run_action` answers (ADR-0068 decision 2)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from wasifyai_platform_sdk.actions.model import Readiness

Status = Literal["ok", "refused", "needs_setup", "needs_approval", "running", "error"]


class ActionResult(BaseModel):
    """A sentence for the model (`text`) and a small structured `output` (ids, kinds, seconds,
    references: never bytes). The other fields say what to do next when `status` is not `ok`."""

    status: Status
    action_id: str
    text: str = ""
    output: dict[str, Any] = Field(default_factory=dict)
    code: str = ""  # refused and error: a stable code ("invalid_input", "denied", "unavailable")
    job_id: str | None = None  # running (and a finished job): the handle
    approval_id: str | None = (
        None  # needs_approval: what the window shows and the caller retries with
    )
    setup: Readiness | None = None  # needs_setup: the step that fixes it, and the screen

    @property
    def ok(self) -> bool:
        return self.status == "ok"
