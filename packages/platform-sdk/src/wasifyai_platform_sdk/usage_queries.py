"""Reads over `usage_events`: what quotas and (later) billing roll-ups are built on."""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_SUM = text(
    """
    SELECT COALESCE(SUM(quantity), 0) FROM usage_events
    WHERE tenant_id = :tenant_id AND product_id = :product_id AND user_id = :user_id
      AND kind = :kind AND created_at >= :since
    """
)


def start_of_day_utc(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def sum_usage(
    engine: AsyncEngine,
    tenant_id: str,
    product_id: str,
    user_id: str,
    kind: str,
    since: datetime,
) -> float:
    """Total quantity of `kind` events for one user since `since`."""
    async with engine.connect() as conn:
        row = await conn.execute(
            _SUM,
            {
                "tenant_id": tenant_id,
                "product_id": product_id,
                "user_id": user_id,
                "kind": kind,
                "since": since,
            },
        )
        return float(row.scalar_one())
