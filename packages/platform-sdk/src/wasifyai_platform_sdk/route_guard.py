"""Safeguards for features that run from routes, not from a graph (ADR-0047 for ADR-0087's P6).

A graph asks its `Capabilities` whether the safeguards are on, counts the day's usage events against
the product's `quotas:` and records what it made. The 3D and Motion graphics screens have no graph:
their routes and job managers do the same through this, from the app's state. Nothing happens while
the safeguards are off (the desktop, tests) except that usage is still recorded, so the numbers are
there the day they are turned on."""

import logging
from typing import Any

from wasifyai_platform_sdk.context import RunContext
from wasifyai_platform_sdk.identity import Identity
from wasifyai_platform_sdk.usage import UsageEvent, record_safely
from wasifyai_platform_sdk.usage_queries import start_of_day_utc, sum_usage

log = logging.getLogger(__name__)

Refusal = tuple[str, str]  # (code, the sentence the person sees)


class RouteGuard:
    def __init__(self, state: Any, product_id: str):
        self._state = state
        self.product_id = product_id

    @property
    def caps(self) -> Any:
        """This product's capabilities (its moderators, config and database), when built."""
        return (self._state.caps or {}).get(self.product_id)

    async def on(self) -> bool:
        guard = getattr(self._state, "safeguards", None)
        return guard is not None and bool(await guard.enabled())

    async def over_quota(
        self, identity: Identity, event: str, quota: str, noun: str, adding: int = 1
    ) -> Refusal | None:
        """A refusal when `adding` more `event`s today would pass the product's `quota`."""
        if not await self.on():
            return None
        caps = self.caps
        limit = (
            caps.config.quotas.get(quota) if caps is not None and caps.config else None
        ) or None
        if not limit or caps is None or caps.db is None:
            return None
        used = await sum_usage(
            caps.db,
            identity.tenant_id,
            self.product_id,
            identity.user_id,
            event,
            start_of_day_utc(),
        )
        if used + max(adding, 1) > limit:
            return (
                "quota_exceeded",
                f"You've reached today's limit of {limit} {noun}. Please try again tomorrow.",
            )
        return None

    async def record(
        self, identity: Identity, event: str, quantity: float, unit: str, **meta: Any
    ) -> None:
        recorder = self._state.usage
        if recorder is None:
            return
        ctx = RunContext(identity.tenant_id, self.product_id, identity.user_id)
        await record_safely(recorder, UsageEvent.for_context(ctx, event, quantity, unit, **meta))
