"""Usage of features that run from routes, not from a graph (ADR-0087's P6).

A graph records what it made through its `Capabilities`. The 3D, Motion graphics and Train screens
have no graph: their routes and job managers record the same usage events through this, from the
app's state."""

from typing import Any

from wasifyai_platform_sdk.context import RunContext
from wasifyai_platform_sdk.identity import Identity
from wasifyai_platform_sdk.usage import UsageEvent, record_safely


class RouteUsage:
    def __init__(self, state: Any, product_id: str):
        self._state = state
        self.product_id = product_id

    @property
    def caps(self) -> Any:
        """This product's capabilities (its config and database), when built."""
        return (self._state.caps or {}).get(self.product_id)

    async def record(
        self, identity: Identity, event: str, quantity: float, unit: str, **meta: Any
    ) -> None:
        recorder = self._state.usage
        if recorder is None:
            return
        ctx = RunContext(identity.tenant_id, self.product_id, identity.user_id)
        await record_safely(recorder, UsageEvent.for_context(ctx, event, quantity, unit, **meta))
