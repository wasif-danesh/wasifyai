"""The admin area (ADR-0025): who the caller is, users, usage and the audit log.

Every route under /admin needs the admin role; everything an admin does that changes state, or reads
personal data, is written to the audit log (never with secrets)."""

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import need

from wasifyai_api.identity import Identity, get_identity, require_admin
from wasifyai_api.services import services_of


class Me(BaseModel):
    user_id: str
    tenant_id: str
    role: str


class AdminUser(BaseModel):
    id: str
    email: str | None
    email_verified: bool
    name: str | None
    role: str
    providers: list[str]
    created_at: datetime


class AdminUserPage(BaseModel):
    users: list[AdminUser]
    next_before: datetime | None


class UsageTotal(BaseModel):
    kind: str
    unit: str
    events: int
    quantity: float


class UsageDay(BaseModel):
    day: date
    kind: str
    events: int


class UsageReport(BaseModel):
    days: int
    totals: list[UsageTotal]
    daily: list[UsageDay]


class AuditEntry(BaseModel):
    id: str
    actor_user_id: str
    action: str
    target_type: str | None = None
    target_id: str | None = None
    detail: dict[str, Any] = {}
    created_at: datetime | None = None


class AuditPage(BaseModel):
    entries: list[AuditEntry]


class AdminStore(Protocol):
    async def users(
        self, tenant_id: str, limit: int, before: datetime | None
    ) -> list[AdminUser]: ...
    async def usage(self, tenant_id: str, days: int) -> UsageReport: ...
    async def audit(self, tenant_id: str, entry: AuditEntry) -> None: ...
    async def audit_log(self, tenant_id: str, limit: int) -> list[AuditEntry]: ...


class InMemoryAdminStore:
    """For tests: rows are set by the test; the audit log is real."""

    def __init__(self) -> None:
        self.user_rows: list[AdminUser] = []
        self.usage_report = UsageReport(days=7, totals=[], daily=[])
        self.entries: list[AuditEntry] = []

    async def users(self, tenant_id: str, limit: int, before: datetime | None) -> list[AdminUser]:
        rows = [u for u in self.user_rows if before is None or u.created_at < before]
        return sorted(rows, key=lambda u: u.created_at, reverse=True)[:limit]

    async def usage(self, tenant_id: str, days: int) -> UsageReport:
        return self.usage_report.model_copy(update={"days": days})

    async def audit(self, tenant_id: str, entry: AuditEntry) -> None:
        self.entries.append(entry.model_copy(update={"created_at": datetime.now(UTC)}))

    async def audit_log(self, tenant_id: str, limit: int) -> list[AuditEntry]:
        return list(reversed(self.entries))[:limit]


class PostgresAdminStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def users(self, tenant_id: str, limit: int, before: datetime | None) -> list[AdminUser]:
        where = "u.tenant_id = :tenant" + (" AND u.created_at < :before" if before else "")
        sql = text(
            f"""
            SELECT u.id, u.email, u.email_verified, u.name, u.role, u.created_at,
                   COALESCE(array_agg(i.provider ORDER BY i.provider)
                            FILTER (WHERE i.provider IS NOT NULL), '{{}}')
            FROM users u LEFT JOIN user_identities i ON i.user_id = u.id
            WHERE {where} GROUP BY u.id ORDER BY u.created_at DESC LIMIT :limit
            """
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(sql, _params(tenant_id, limit, before))).all()
        return [
            AdminUser(
                id=str(r[0]), email=r[1], email_verified=r[2], name=r[3], role=r[4],
                created_at=r[5], providers=list(r[6]),
            )
            for r in rows
        ]  # fmt: skip

    async def usage(self, tenant_id: str, days: int) -> UsageReport:
        since = "tenant_id = :tenant AND created_at >= now() - make_interval(days => :days)"
        totals = text(
            f"SELECT kind, unit, count(*), COALESCE(sum(quantity), 0) FROM usage_events "
            f"WHERE {since} GROUP BY kind, unit ORDER BY kind"
        )
        daily = text(
            f"SELECT date_trunc('day', created_at)::date, kind, count(*) FROM usage_events "
            f"WHERE {since} GROUP BY 1, 2 ORDER BY 1 DESC, 2"
        )
        p = {"tenant": tenant_id, "days": days}
        async with self._engine.connect() as conn:
            t = (await conn.execute(totals, p)).all()
            d = (await conn.execute(daily, p)).all()
        return UsageReport(
            days=days,
            totals=[UsageTotal(kind=r[0], unit=r[1], events=r[2], quantity=float(r[3])) for r in t],
            daily=[UsageDay(day=r[0], kind=r[1], events=r[2]) for r in d],
        )

    async def audit(self, tenant_id: str, entry: AuditEntry) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO audit_log (id, tenant_id, actor_user_id, action, target_type, "
                    "target_id, detail) VALUES (:id, :tenant, :actor, :action, :tt, :tid, "
                    "CAST(:detail AS json))"
                ),
                {
                    "id": uuid.uuid4(), "tenant": tenant_id, "actor": entry.actor_user_id,
                    "action": entry.action, "tt": entry.target_type, "tid": entry.target_id,
                    "detail": json.dumps(entry.detail),
                },
            )  # fmt: skip

    async def audit_log(self, tenant_id: str, limit: int) -> list[AuditEntry]:
        sql = text(
            "SELECT id, actor_user_id, action, target_type, target_id, detail, created_at "
            "FROM audit_log WHERE tenant_id = :tenant ORDER BY created_at DESC LIMIT :limit"
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(sql, {"tenant": tenant_id, "limit": limit})).all()
        return [
            AuditEntry(
                id=str(r[0]), actor_user_id=r[1], action=r[2], target_type=r[3], target_id=r[4],
                detail=r[5] or {}, created_at=r[6],
            )
            for r in rows
        ]  # fmt: skip


def _params(tenant_id: str, limit: int, before: datetime | None) -> dict[str, Any]:
    p: dict[str, Any] = {"tenant": tenant_id, "limit": limit}
    if before:
        p["before"] = before
    return p


def _store(request: Request) -> AdminStore:
    return need(services_of(request).admin, "the admin store")


me_router = APIRouter(tags=["admin"])
router = APIRouter(prefix="/admin", tags=["admin"])


@me_router.get("/me", response_model=Me)
async def me(identity: Identity = Depends(get_identity)) -> Me:
    return Me(user_id=identity.user_id, tenant_id=identity.tenant_id, role=identity.role)


@router.get("/users", response_model=AdminUserPage)
async def list_users(
    request: Request,
    limit: int = Query(25, ge=1, le=100),
    before: datetime | None = None,
    identity: Identity = Depends(require_admin),
) -> AdminUserPage:
    store = _store(request)
    users = await store.users(identity.tenant_id, limit, before)
    # Reading other people's email addresses is itself recorded.
    await store.audit(
        identity.tenant_id,
        AuditEntry(
            id="", actor_user_id=identity.user_id, action="admin.users.list",
            detail={"limit": limit, "returned": len(users)},
        ),
    )  # fmt: skip
    return AdminUserPage(
        users=users, next_before=users[-1].created_at if len(users) == limit else None
    )


@router.get("/usage", response_model=UsageReport)
async def usage_report(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    identity: Identity = Depends(require_admin),
) -> UsageReport:
    return await _store(request).usage(identity.tenant_id, days)


@router.get("/audit", response_model=AuditPage)
async def audit_log(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    identity: Identity = Depends(require_admin),
) -> AuditPage:
    return AuditPage(entries=await _store(request).audit_log(identity.tenant_id, limit))
