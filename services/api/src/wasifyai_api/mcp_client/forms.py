"""Elicitation as a form card in the window (ADR-0070 decision 10, stage C3). A tool of an outside
server may ask the person something mid-call (`elicitation/create`, form mode); the engine raises
an `elicitation` event on the window's stream, the window shows the message and a form drawn
from the requested schema, and the answer (accept with the values, decline, cancel) goes back to
the server. The assistant never answers for the person; a form nobody answers is a cancel."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import jsonschema

log = logging.getLogger(__name__)

FORM_WAIT_S = 300  # how long a tool call may wait for the person's answer
MAX_PENDING = 20
ACTIONS = ("accept", "decline", "cancel")


@dataclass
class Form:
    server_id: str
    server_name: str
    tenant_id: str
    user_id: str
    message: str
    schema: dict[str, Any]
    id: str = field(default_factory=lambda: uuid4().hex[:16])
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    answered: asyncio.Future[tuple[str, dict[str, Any] | None]] = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
    )

    def public(self) -> dict[str, Any]:
        return {
            "form_id": self.id, "server": self.server_name, "message": self.message[:2000],
            "schema": self.schema, "created_at": self.created_at.isoformat(),
        }  # fmt: skip


class FormDesk:
    def __init__(self, events: Any):
        self._events = events  # the window's event bus (`publish(kind, **data)`)
        self._pending: dict[str, Form] = {}

    def ask(self, form: Form) -> Form:
        if len(self._pending) >= MAX_PENDING:
            raise RuntimeError("too many forms are waiting")
        self._pending[form.id] = form
        if self._events is not None:
            self._events.publish(
                "elicitation", form_id=form.id, server=form.server_name, message=form.message
            )
        return form

    def pending_for(self, tenant_id: str, user_id: str) -> list[Form]:
        return [
            f
            for f in self._pending.values()
            if (f.tenant_id, f.user_id) == (tenant_id, user_id) and not f.answered.done()
        ]

    def answer(
        self, tenant_id: str, user_id: str, form_id: str, action: str, content: Any
    ) -> Form | None:
        """The person's answer. Raises ValueError when the values do not fit the schema."""
        form = self._pending.get(form_id)
        if form is None or (form.tenant_id, form.user_id) != (tenant_id, user_id):
            return None
        if action not in ACTIONS:
            raise ValueError("the answer is accept, decline or cancel")
        values: dict[str, Any] | None = None
        if action == "accept":
            values = content if isinstance(content, dict) else {}
            try:
                jsonschema.validate(values, form.schema)
            except jsonschema.ValidationError as e:
                raise ValueError(f"the values do not fit the form: {e.message}") from None
            except jsonschema.SchemaError:
                pass
        if not form.answered.done():
            form.answered.set_result((action, values))
        return form

    async def wait(
        self, form: Form, seconds: float | None = None
    ) -> tuple[str, dict[str, Any] | None]:
        wait_s = FORM_WAIT_S if seconds is None else seconds  # read when called (tests shorten it)
        try:
            return await asyncio.wait_for(asyncio.shield(form.answered), wait_s)
        except TimeoutError:
            return "cancel", None
        finally:
            self._pending.pop(form.id, None)
