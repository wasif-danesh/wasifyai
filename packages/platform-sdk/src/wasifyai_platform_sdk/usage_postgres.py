"""Writes usage events to Postgres (the table billing will read)."""

import json
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.usage import UsageEvent

_INSERT = text(
    """
    INSERT INTO usage_events
        (id, tenant_id, product_id, user_id, run_id, kind, quantity, unit, meta)
    VALUES
        (:id, :tenant_id, :product_id, :user_id, :run_id, :kind, :quantity, :unit,
         CAST(:meta AS json))
    """
)


class PostgresUsageRecorder:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def record(self, event: UsageEvent) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                _INSERT,
                {
                    "id": uuid4(),
                    "tenant_id": event.tenant_id,
                    "product_id": event.product_id,
                    "user_id": event.user_id,
                    "run_id": event.run_id,
                    "kind": event.kind,
                    "quantity": event.quantity,
                    "unit": event.unit,
                    "meta": json.dumps(event.meta),
                },
            )
