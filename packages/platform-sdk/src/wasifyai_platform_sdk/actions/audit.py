"""The audit log and the pending approvals (ADR-0068 decisions 2 and 4).

An audit entry says who asked (`origin`), which action, how it ended, and how long it took. It
holds no content: no prompt, no text, no file name (ADR-0069 decision 11). A pending approval
holds the parameters the person is asked about until it is decided, then they are dropped.

Both stores speak SQL that runs on Postgres (the web profile, Alembic revision 0020) and SQLite
(the desktop profile, tables created on first use)."""

import json
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.sqlite.engine import Migration, from_iso, is_sqlite, migrate, to_iso

AuditStatus = Literal["ok", "refused", "needs_setup", "needs_approval", "running", "error"]
Approver = Literal["none", "auto", "person"]  # how the go-ahead came: not needed, setting, a person
ApprovalStatus = Literal["pending", "approved", "denied", "used", "expired"]


def _now() -> datetime:
    return datetime.now(UTC)


class AuditEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    product_id: str
    user_id: str
    action_id: str
    origin: str
    effect: str = ""
    status: AuditStatus
    code: str = ""
    approval: Approver = "none"
    job_id: str | None = None
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=_now)


class AuditStore(Protocol):
    async def record(self, entry: AuditEntry) -> None: ...

    async def recent(self, tenant_id: str, user_id: str, limit: int = 50) -> list[AuditEntry]: ...

    async def last_for_job(
        self, tenant_id: str, user_id: str, job_id: str
    ) -> AuditEntry | None: ...


class InMemoryAuditStore:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    async def recent(self, tenant_id: str, user_id: str, limit: int = 50) -> list[AuditEntry]:
        mine = [e for e in self.entries if (e.tenant_id, e.user_id) == (tenant_id, user_id)]
        return list(reversed(mine))[:limit]

    async def last_for_job(self, tenant_id: str, user_id: str, job_id: str) -> AuditEntry | None:
        for e in reversed(self.entries):
            if e.job_id == job_id and (e.tenant_id, e.user_id) == (tenant_id, user_id):
                return e
        return None


class ApprovalRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    product_id: str
    user_id: str
    action_id: str
    origin: str
    params_hash: str  # the approval is for exactly these parameters
    summary: str = ""  # one line for the card ("Make a 30 second song")
    params: dict[str, Any] | None = None  # shown while pending, dropped once decided
    status: ApprovalStatus = "pending"
    decided_by: str = ""
    created_at: datetime = Field(default_factory=_now)
    decided_at: datetime | None = None


class ApprovalStore(Protocol):
    async def create(self, record: ApprovalRecord) -> None: ...

    async def get(
        self, tenant_id: str, user_id: str, approval_id: str
    ) -> ApprovalRecord | None: ...

    async def pending(self, tenant_id: str, user_id: str) -> list[ApprovalRecord]: ...

    async def decide(
        self, tenant_id: str, user_id: str, approval_id: str, approved: bool, by: str
    ) -> ApprovalRecord | None:
        """Approve or deny a pending approval. `None` when it is not there or already decided."""
        ...

    async def consume(self, tenant_id: str, user_id: str, approval_id: str) -> bool:
        """Spend an approved approval (it works once). False when it was not approved or was
        already spent."""
        ...


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self.records: dict[str, ApprovalRecord] = {}

    def _mine(self, tenant_id: str, user_id: str, approval_id: str) -> ApprovalRecord | None:
        r = self.records.get(approval_id)
        return r if r and (r.tenant_id, r.user_id) == (tenant_id, user_id) else None

    async def create(self, record: ApprovalRecord) -> None:
        self.records[record.id] = record

    async def get(self, tenant_id: str, user_id: str, approval_id: str) -> ApprovalRecord | None:
        return self._mine(tenant_id, user_id, approval_id)

    async def pending(self, tenant_id: str, user_id: str) -> list[ApprovalRecord]:
        return sorted(
            (
                r
                for r in self.records.values()
                if r.status == "pending" and (r.tenant_id, r.user_id) == (tenant_id, user_id)
            ),
            key=lambda r: r.created_at,
        )

    async def decide(
        self, tenant_id: str, user_id: str, approval_id: str, approved: bool, by: str
    ) -> ApprovalRecord | None:
        r = self._mine(tenant_id, user_id, approval_id)
        if r is None or r.status != "pending":
            return None
        updated = r.model_copy(
            update={
                "status": "approved" if approved else "denied", "params": None,
                "decided_by": by, "decided_at": _now(),
            }
        )  # fmt: skip
        self.records[r.id] = updated
        return updated

    async def consume(self, tenant_id: str, user_id: str, approval_id: str) -> bool:
        r = self._mine(tenant_id, user_id, approval_id)
        if r is None or r.status != "approved":
            return False
        self.records[r.id] = r.model_copy(update={"status": "used"})
        return True


# ---- SQL (Postgres and SQLite) ----------------------------------------------------------------

_AUDIT_DDL = (
    """
    CREATE TABLE IF NOT EXISTS action_audit (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        action_id TEXT NOT NULL,
        origin TEXT NOT NULL,
        effect TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        code TEXT NOT NULL DEFAULT '',
        approval TEXT NOT NULL DEFAULT 'none',
        job_id TEXT,
        duration_ms INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_action_audit_user_time "
    "ON action_audit (tenant_id, user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_action_audit_job ON action_audit (tenant_id, user_id, job_id)",
)

# the store's shape before the migration runner (stage J1); a change is a new Migration(2, ...)
_AUDIT_MIGRATIONS = (Migration(1, _AUDIT_DDL),)

_APPROVAL_DDL = (
    """
    CREATE TABLE IF NOT EXISTS action_approvals (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        action_id TEXT NOT NULL,
        origin TEXT NOT NULL,
        params_hash TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        params TEXT,
        status TEXT NOT NULL,
        decided_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        decided_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_action_approvals_user_status "
    "ON action_approvals (tenant_id, user_id, status)",
)

# the store's shape before the migration runner (stage J1); a change is a new Migration(2, ...)
_APPROVAL_MIGRATIONS = (Migration(1, _APPROVAL_DDL),)


def _stamp(engine: AsyncEngine, value: datetime | None) -> Any:
    """SQLite keeps time as UTC text; Postgres takes the datetime (its columns are timestamptz)."""
    if value is None:
        return None
    return to_iso(value) if is_sqlite(engine) else value


def _moment(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return from_iso(str(value))


class SqlAuditStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        if is_sqlite(self._engine):
            await migrate(self._engine, "action_audit", _AUDIT_MIGRATIONS)

    async def record(self, entry: AuditEntry) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO action_audit (id, tenant_id, product_id, user_id, action_id, "
                    "origin, effect, status, code, approval, job_id, duration_ms, created_at) "
                    "VALUES (:id, :tenant_id, :product_id, :user_id, :action_id, :origin, "
                    ":effect, :status, :code, :approval, :job_id, :duration_ms, :created_at)"
                ),
                entry.model_dump(exclude={"created_at"})
                | {"created_at": _stamp(self._engine, entry.created_at)},
            )

    @staticmethod
    def _entry(r: Any) -> AuditEntry:
        m = dict(r._mapping)
        m["created_at"] = _moment(m["created_at"])
        return AuditEntry.model_validate(m)

    async def recent(self, tenant_id: str, user_id: str, limit: int = 50) -> list[AuditEntry]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT * FROM action_audit WHERE tenant_id = :t AND user_id = :u "
                    "ORDER BY created_at DESC LIMIT :n"
                ),
                {"t": tenant_id, "u": user_id, "n": max(1, min(limit, 500))},
            )
            return [self._entry(r) for r in rows]

    async def last_for_job(self, tenant_id: str, user_id: str, job_id: str) -> AuditEntry | None:
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT * FROM action_audit WHERE tenant_id = :t AND user_id = :u "
                        "AND job_id = :j ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"t": tenant_id, "u": user_id, "j": job_id},
                )
            ).first()
            return self._entry(row) if row else None


class SqlApprovalStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        if is_sqlite(self._engine):
            await migrate(self._engine, "action_approvals", _APPROVAL_MIGRATIONS)

    def _record(self, r: Any) -> ApprovalRecord:
        m = dict(r._mapping)
        m["created_at"] = _moment(m["created_at"])
        m["decided_at"] = _moment(m["decided_at"])
        m["params"] = json.loads(m["params"]) if m["params"] else None
        return ApprovalRecord.model_validate(m)

    async def create(self, record: ApprovalRecord) -> None:
        await self._ready()
        values = record.model_dump(exclude={"created_at", "decided_at", "params"})
        values["params"] = json.dumps(record.params) if record.params is not None else None
        values["created_at"] = _stamp(self._engine, record.created_at)
        values["decided_at"] = _stamp(self._engine, record.decided_at)
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO action_approvals (id, tenant_id, product_id, user_id, action_id, "
                    "origin, params_hash, summary, params, status, decided_by, created_at, "
                    "decided_at) VALUES (:id, :tenant_id, :product_id, :user_id, :action_id, "
                    ":origin, :params_hash, :summary, :params, :status, :decided_by, "
                    ":created_at, :decided_at)"
                ),
                values,
            )

    async def get(self, tenant_id: str, user_id: str, approval_id: str) -> ApprovalRecord | None:
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT * FROM action_approvals "
                        "WHERE tenant_id = :t AND user_id = :u AND id = :i"
                    ),
                    {"t": tenant_id, "u": user_id, "i": approval_id},
                )
            ).first()
        return self._record(row) if row else None

    async def pending(self, tenant_id: str, user_id: str) -> list[ApprovalRecord]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT * FROM action_approvals WHERE tenant_id = :t AND user_id = :u "
                    "AND status = 'pending' ORDER BY created_at"
                ),
                {"t": tenant_id, "u": user_id},
            )
            return [self._record(r) for r in rows]

    async def decide(
        self, tenant_id: str, user_id: str, approval_id: str, approved: bool, by: str
    ) -> ApprovalRecord | None:
        await self._ready()
        async with self._engine.begin() as conn:
            done = await conn.execute(
                text(
                    "UPDATE action_approvals SET status = :s, params = NULL, decided_by = :by, "
                    "decided_at = :at WHERE tenant_id = :t AND user_id = :u AND id = :i "
                    "AND status = 'pending'"
                ),
                {
                    "s": "approved" if approved else "denied", "by": by,
                    "at": _stamp(self._engine, _now()), "t": tenant_id, "u": user_id,
                    "i": approval_id,
                },
            )  # fmt: skip
            if done.rowcount != 1:
                return None
        return await self.get(tenant_id, user_id, approval_id)

    async def consume(self, tenant_id: str, user_id: str, approval_id: str) -> bool:
        await self._ready()
        async with self._engine.begin() as conn:
            done = await conn.execute(
                text(
                    "UPDATE action_approvals SET status = 'used' WHERE tenant_id = :t "
                    "AND user_id = :u AND id = :i AND status = 'approved'"
                ),
                {"t": tenant_id, "u": user_id, "i": approval_id},
            )
            return done.rowcount == 1
