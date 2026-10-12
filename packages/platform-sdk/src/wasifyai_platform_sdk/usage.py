"""Usage events: every billable action records one (rule 9). Billing reads these later."""

import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field

from wasifyai_platform_sdk.context import RunContext

log = logging.getLogger(__name__)

LLM_INPUT_TOKENS = "llm.input_tokens"
LLM_OUTPUT_TOKENS = "llm.output_tokens"
EMBEDDING_TOKENS = "llm.embedding_tokens"
# Phase 4+: "gpu.seconds", "job.completed"


class UsageEvent(BaseModel):
    tenant_id: str
    product_id: str
    user_id: str | None = None
    run_id: str | None = None
    kind: str
    quantity: float
    unit: str
    meta: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def for_context(
        cls, ctx: RunContext, kind: str, quantity: float, unit: str, **meta: Any
    ) -> "UsageEvent":
        return cls(
            tenant_id=ctx.tenant_id,
            product_id=ctx.product_id,
            user_id=ctx.user_id,
            run_id=ctx.run_id,
            kind=kind,
            quantity=quantity,
            unit=unit,
            meta=meta,
        )


class UsageRecorder(Protocol):
    async def record(self, event: UsageEvent) -> None: ...


class InMemoryUsageRecorder:
    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    async def record(self, event: UsageEvent) -> None:
        self.events.append(event)


async def record_safely(recorder: UsageRecorder, event: UsageEvent) -> None:
    """Recording must never fail a user's request; failures are logged for follow-up."""
    try:
        await recorder.record(event)
    except Exception:
        log.exception("failed to record usage event", extra={"kind": event.kind})
