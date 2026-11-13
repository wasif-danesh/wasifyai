"""The approval desk (ADR-0069 decision 8, as spike S1 corrected it): an action a connection
asked for that needs the person's yes waits here, the window shows a card, and the answer runs
the action (as a job when it is long) so the agent can follow it with `approval_status`.

The executor keeps the pending approval and its parameters until it is decided (then drops the
parameters); the desk keeps what is needed to run on a yes: the action, the parameters, who asked
and under which policy. Nothing here runs without `executor.decide_approval` having recorded the
person's answer first."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from wasifyai_platform_sdk import Principal
from wasifyai_platform_sdk.actions import ActionExecutor, ActionResult, ApprovalPolicy

MAX_PENDING = 100
TTL_S = 24 * 3600


@dataclass
class Pending:
    approval_id: str
    action_id: str
    params: dict[str, Any]
    principal: Principal
    policy: ApprovalPolicy
    connection_id: str
    connection_name: str
    title: str
    summary: str
    created: float = field(default_factory=time.monotonic)
    status: str = "pending"  # pending, approved, denied, expired
    result: ActionResult | None = None  # what a yes came to
    done: asyncio.Event = field(default_factory=asyncio.Event)

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "approval_id": self.approval_id, "status": self.status, "action_id": self.action_id,
            "connection": self.connection_name,
        }  # fmt: skip
        if self.result is not None:
            out.update(
                {
                    "result_status": self.result.status,
                    "text": self.result.text,
                    "output": self.result.output,
                    "job_id": self.result.job_id,
                }  # fmt: skip
            )
        return out


class ApprovalDesk:
    def __init__(self, executor: ActionExecutor):
        self._executor = executor
        self._pending: dict[str, Pending] = {}

    def _sweep(self) -> None:
        now = time.monotonic()
        for key, p in list(self._pending.items()):
            if now - p.created > TTL_S:
                del self._pending[key]
        while len(self._pending) > MAX_PENDING:
            oldest = min(self._pending.values(), key=lambda p: p.created)
            del self._pending[oldest.approval_id]

    def ask(self, pending: Pending) -> Pending:
        self._sweep()
        self._pending[pending.approval_id] = pending
        return pending

    def get(self, approval_id: str) -> Pending | None:
        return self._pending.get(approval_id)

    def pending_for(self, tenant_id: str, user_id: str) -> list[Pending]:
        return [
            p
            for p in self._pending.values()
            if p.status == "pending"
            and (p.principal.tenant_id, p.principal.user_id) == (tenant_id, user_id)
        ]

    async def wait(self, approval_id: str, seconds: float) -> Pending | None:
        p = self._pending.get(approval_id)
        if p is None:
            return None
        if p.status == "pending" and seconds > 0:
            try:
                await asyncio.wait_for(p.done.wait(), seconds)
            except TimeoutError:
                pass
        return p

    async def decide(
        self, tenant_id: str, user_id: str, approval_id: str, approved: bool
    ) -> Pending | None:
        """The person's answer from the window. A yes runs the action for the connection, with
        the approval the executor recorded; a long action becomes a job."""
        p = self._pending.get(approval_id)
        if p is None or p.status != "pending":
            return p
        if (p.principal.tenant_id, p.principal.user_id) != (tenant_id, user_id):
            return None
        recorded = await self._executor.decide_approval(
            p.principal.identity, approval_id, approved, by="window"
        )
        if not recorded:
            p.status = "expired"
            p.done.set()
            return p
        if not approved:
            p.status = "denied"
            p.done.set()
            return p
        p.status = "approved"
        p.result = await self._executor.run_action(
            p.action_id, p.params, p.principal.origin, actor=p.principal, policy=p.policy,
            wait_seconds=0, approval_id=approval_id,
        )  # fmt: skip
        p.done.set()
        return p
