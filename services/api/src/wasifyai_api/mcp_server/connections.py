"""Connections (ADR-0069 decisions 3, 5 and 11; ADR-0092): who may call the MCP endpoint.

A connection is one client the person allowed ("Codex on my laptop"): a secret shown once and
stored hashed, the scopes it may use (the catalogue's groups), its approval setting (with the
floor of ADR-0068: deleting and consent always ask), the folders it may read and write, a rate
limit, when it was last used, and whether it was revoked. A call under a connection acts as the
person who made it, with the connection's scopes, from the origin `mcp:<name>`."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import USER_SCOPES, AllowedFolders, Principal
from wasifyai_platform_sdk.actions import ApprovalPolicy, PolicyError
from wasifyai_platform_sdk.sqlite.engine import (
    Migration,
    from_iso,
    is_sqlite,
    migrate,
    to_iso,
)

from wasifyai_api.auth import AuthError

SECRET_PREFIX = "wsc_"
SECRET_PATTERN = re.compile(r"^wsc_([a-f0-9]{16})_([A-Za-z0-9_-]{20,64})$")
NAME_MAX = 60
DEFAULT_SCOPES: tuple[str, ...] = ("make", "models", "read")  # decision 5, sorted
DEFAULT_RATE = 60  # calls per minute
DEFAULT_DAILY = 1000  # tool calls per day (ADR-0069 decision 10; stage M3)


def default_export_folder() -> str:
    """Where a new connection may write (ADR-0069 decision 6; spike S2): a folder of the app's
    own under Documents, made when the connection is, so the system's folder prompt (macOS)
    comes in Settings, not in the middle of an agent's call."""
    folder = Path.home() / "Documents" / "Wasify AI exports"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return str(Path.home() / "Wasify AI exports")
    return str(folder)


Kind = Literal["client", "launcher"]


def _now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid4().hex[:16]


def new_secret(connection_id: str) -> str:
    """`wsc_<connection id>_<random>`: the id lets the gate find the row, the random part is
    what is checked (hashed with a salt of its own)."""
    return f"{SECRET_PREFIX}{connection_id}_{secrets.token_urlsafe(30)}"


def hash_secret(secret: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{secret}".encode()).hexdigest()
    return f"sha256${salt}${digest}"


def secret_matches(secret: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    return hmac.compare_digest(hash_secret(secret, salt).split("$", 2)[2], digest)


def connection_id_of(secret: str) -> str | None:
    m = SECRET_PATTERN.match(secret or "")
    return m.group(1) if m else None


def check_scopes(scopes: Any) -> tuple[str, ...]:
    """The scopes a connection may hold: a person's scopes minus `admin`, always with `read`."""
    if not isinstance(scopes, list | tuple):
        raise ValueError("scopes must be a list of words")
    out = {str(s) for s in scopes} | {"read"}
    unknown = out - USER_SCOPES
    if unknown:
        raise ValueError(f"unknown scopes: {sorted(unknown)}")
    return tuple(sorted(out))


def check_policy(policy: Any) -> dict[str, str]:
    """A connection's approval setting, held to the floor (`ApprovalPolicy.from_settings`)."""
    if policy is None:
        return {}
    if not isinstance(policy, dict):
        raise ValueError("the approval setting must be an object")
    try:
        ApprovalPolicy.from_settings(policy)
    except PolicyError as e:
        raise ValueError(str(e)) from None
    return {str(k): str(v) for k, v in policy.items()}


def check_name(name: Any) -> str:
    name = " ".join(str(name or "").split())
    if not name or len(name) > NAME_MAX:
        raise ValueError(f"give the connection a name of up to {NAME_MAX} characters")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$", name):
        raise ValueError("a name is letters, digits, spaces, dots, dashes and underscores")
    return name


@dataclass(frozen=True)
class Connection:
    id: str
    tenant_id: str
    user_id: str
    name: str
    secret_hash: str
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    policy: dict[str, str] = field(default_factory=dict)
    read_folders: tuple[str, ...] = ()
    write_folders: tuple[str, ...] = ()
    rate_per_minute: int = DEFAULT_RATE
    calls_per_day: int = DEFAULT_DAILY
    kind: Kind = "client"
    created_at: datetime = field(default_factory=_now)
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def approval(self) -> ApprovalPolicy:
        return ApprovalPolicy.from_settings(self.policy)

    @property
    def folders(self) -> AllowedFolders:
        return AllowedFolders.of(self.read_folders, self.write_folders)

    @property
    def origin(self) -> str:
        return f"mcp:{self.name}"

    def principal(self, role: str = "user") -> Principal:
        return Principal(
            "connection", self.tenant_id, self.user_id, role,
            frozenset(self.scopes), self.origin, self.id, self.folders,
        )  # fmt: skip

    def public(self) -> dict[str, Any]:
        """What Settings shows: never the hash."""
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "scopes": list(self.scopes),
            "approval": dict(self.policy), "read_folders": list(self.read_folders),
            "write_folders": list(self.write_folders), "rate_per_minute": self.rate_per_minute,
            "calls_per_day": self.calls_per_day,
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "revoked": self.revoked,
        }  # fmt: skip


@dataclass(frozen=True)
class ActivityEntry:
    """One call at the endpoint: no content, no parameters (ADR-0069 decision 11)."""

    connection_id: str
    method: str
    tool: str = ""
    status: str = ""  # ok, refused, error, needs_approval, running, unauthorized ...
    duration_ms: int = 0
    bytes: int = 0
    created_at: datetime = field(default_factory=_now)

    def public(self) -> dict[str, Any]:
        return {
            "method": self.method, "tool": self.tool, "status": self.status,
            "duration_ms": self.duration_ms, "bytes": self.bytes,
            "created_at": self.created_at.isoformat(),
        }  # fmt: skip


class ConnectionStore(Protocol):
    async def create(self, connection: Connection) -> None: ...

    async def get(self, connection_id: str) -> Connection | None: ...

    async def for_person(self, tenant_id: str, user_id: str) -> list[Connection]: ...

    async def save(self, connection: Connection) -> None: ...

    async def record(self, entry: ActivityEntry) -> None: ...

    async def activity(self, connection_id: str, limit: int = 50) -> list[ActivityEntry]: ...

    async def calls_since(self, connection_id: str, since: datetime) -> int:
        """How many tool calls the connection made since `since` (the daily quota)."""
        ...


class InMemoryConnectionStore:
    def __init__(self) -> None:
        self.rows: dict[str, Connection] = {}
        self.entries: list[ActivityEntry] = []

    async def create(self, connection: Connection) -> None:
        self.rows[connection.id] = connection

    async def get(self, connection_id: str) -> Connection | None:
        return self.rows.get(connection_id)

    async def for_person(self, tenant_id: str, user_id: str) -> list[Connection]:
        mine = [c for c in self.rows.values() if (c.tenant_id, c.user_id) == (tenant_id, user_id)]
        return sorted(mine, key=lambda c: c.created_at)

    async def save(self, connection: Connection) -> None:
        self.rows[connection.id] = connection

    async def record(self, entry: ActivityEntry) -> None:
        self.entries.append(entry)

    async def activity(self, connection_id: str, limit: int = 50) -> list[ActivityEntry]:
        mine = [e for e in self.entries if e.connection_id == connection_id]
        return list(reversed(mine))[:limit]

    async def calls_since(self, connection_id: str, since: datetime) -> int:
        return sum(
            1
            for e in self.entries
            if e.connection_id == connection_id
            and e.method == "tools/call"
            and e.created_at >= since
        )


_DDL = (
    """
    CREATE TABLE IF NOT EXISTS mcp_connections (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        secret_hash TEXT NOT NULL,
        scopes TEXT NOT NULL,
        policy TEXT NOT NULL,
        read_folders TEXT NOT NULL,
        write_folders TEXT NOT NULL,
        rate_per_minute INTEGER NOT NULL,
        calls_per_day INTEGER NOT NULL DEFAULT 1000,
        kind TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_mcp_connections_user ON mcp_connections (tenant_id, user_id)",
    """
    CREATE TABLE IF NOT EXISTS mcp_activity (
        id TEXT PRIMARY KEY,
        connection_id TEXT NOT NULL,
        method TEXT NOT NULL,
        tool TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT '',
        duration_ms INTEGER NOT NULL DEFAULT 0,
        bytes INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_mcp_activity_connection "
    "ON mcp_activity (connection_id, created_at)",
)
COLUMNS = (
    "id, tenant_id, user_id, name, secret_hash, scopes, policy, read_folders, write_folders, "
    "rate_per_minute, calls_per_day, kind, created_at, last_used_at, revoked_at"
)
# columns added after the table first shipped (SQLite files from before get them on first use)
LATER_COLUMNS = {"calls_per_day": "INTEGER NOT NULL DEFAULT 1000"}

# the store's shape before the migration runner (stage J1); a change is a new Migration(2, ...)
_MIGRATIONS = (Migration(1, _DDL, columns={"mcp_connections": LATER_COLUMNS}),)


def _split(value: Any) -> tuple[str, ...]:
    return tuple(s for s in str(value or "").split("\n") if s)


class SqlConnectionStore:
    """SQLite (created on first use) and Postgres (Alembic 0023). Lists are kept as one line
    per item; the policy as `key=value` lines."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        if is_sqlite(self._engine):
            await migrate(self._engine, "mcp_connections", _MIGRATIONS)

    def _stamp(self, when: datetime | None) -> Any:
        if when is None:
            return None
        return to_iso(when) if is_sqlite(self._engine) else when

    @staticmethod
    def _moment(value: Any) -> datetime | None:
        if value is None:
            return None
        return from_iso(value) if isinstance(value, str) else value

    def _params(self, c: Connection) -> dict[str, Any]:
        return {
            "id": c.id, "tenant_id": c.tenant_id, "user_id": c.user_id, "name": c.name,
            "secret_hash": c.secret_hash, "scopes": "\n".join(c.scopes),
            "policy": "\n".join(f"{k}={v}" for k, v in c.policy.items()),
            "read_folders": "\n".join(c.read_folders), "write_folders": "\n".join(c.write_folders),
            "rate_per_minute": c.rate_per_minute, "calls_per_day": c.calls_per_day, "kind": c.kind,
            "created_at": self._stamp(c.created_at), "last_used_at": self._stamp(c.last_used_at),
            "revoked_at": self._stamp(c.revoked_at),
        }  # fmt: skip

    def _row(self, r: Any) -> Connection:
        m = dict(r._mapping)
        policy = dict(line.split("=", 1) for line in _split(m["policy"]) if "=" in line)
        return Connection(
            id=m["id"], tenant_id=m["tenant_id"], user_id=m["user_id"], name=m["name"],
            secret_hash=m["secret_hash"], scopes=_split(m["scopes"]), policy=policy,
            read_folders=_split(m["read_folders"]), write_folders=_split(m["write_folders"]),
            rate_per_minute=int(m["rate_per_minute"]), calls_per_day=int(m["calls_per_day"]),
            kind=m["kind"],
            created_at=self._moment(m["created_at"]) or _now(),
            last_used_at=self._moment(m["last_used_at"]),
            revoked_at=self._moment(m["revoked_at"]),
        )  # fmt: skip

    async def create(self, connection: Connection) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    f"INSERT INTO mcp_connections ({COLUMNS}) VALUES (:id, :tenant_id, :user_id, "
                    ":name, :secret_hash, :scopes, :policy, :read_folders, :write_folders, "
                    ":rate_per_minute, :calls_per_day, :kind, :created_at, :last_used_at, "
                    ":revoked_at)"
                ),
                self._params(connection),
            )

    async def get(self, connection_id: str) -> Connection | None:
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(f"SELECT {COLUMNS} FROM mcp_connections WHERE id = :id"),
                    {"id": connection_id},
                )
            ).first()
        return self._row(row) if row else None

    async def for_person(self, tenant_id: str, user_id: str) -> list[Connection]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    f"SELECT {COLUMNS} FROM mcp_connections WHERE tenant_id = :t AND user_id = :u "
                    "ORDER BY created_at"
                ),
                {"t": tenant_id, "u": user_id},
            )
            return [self._row(r) for r in rows]

    async def save(self, connection: Connection) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE mcp_connections SET name = :name, secret_hash = :secret_hash, "
                    "scopes = :scopes, policy = :policy, read_folders = :read_folders, "
                    "write_folders = :write_folders, rate_per_minute = :rate_per_minute, "
                    "calls_per_day = :calls_per_day, "
                    "last_used_at = :last_used_at, revoked_at = :revoked_at WHERE id = :id"
                ),
                self._params(connection),
            )

    async def record(self, entry: ActivityEntry) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO mcp_activity (id, connection_id, method, tool, status, "
                    "duration_ms, bytes, created_at) VALUES (:id, :c, :m, :tool, :s, :d, :b, :at)"
                ),
                {
                    "id": uuid4().hex,
                    "c": entry.connection_id,
                    "m": entry.method,
                    "tool": entry.tool,
                    "s": entry.status,
                    "d": entry.duration_ms,
                    "b": entry.bytes,
                    "at": self._stamp(entry.created_at),
                },  # fmt: skip
            )

    async def activity(self, connection_id: str, limit: int = 50) -> list[ActivityEntry]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT connection_id, method, tool, status, duration_ms, bytes, created_at "
                    "FROM mcp_activity WHERE connection_id = :c ORDER BY created_at DESC LIMIT :n"
                ),
                {"c": connection_id, "n": max(1, min(limit, 500))},
            )
            return [
                ActivityEntry(
                    connection_id=r.connection_id,
                    method=r.method,
                    tool=r.tool,
                    status=r.status,
                    duration_ms=int(r.duration_ms),
                    bytes=int(r.bytes),
                    created_at=self._moment(r.created_at) or _now(),
                )  # fmt: skip
                for r in rows
            ]

    async def calls_since(self, connection_id: str, since: datetime) -> int:
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM mcp_activity WHERE connection_id = :c "
                        "AND method = 'tools/call' AND created_at >= :s"
                    ),
                    {"c": connection_id, "s": self._stamp(since)},
                )
            ).first()
        return int(row[0]) if row else 0


class ConnectionsService:
    """What Settings does with connections, and what the gate asks."""

    def __init__(self, store: ConnectionStore):
        self.store = store

    async def create(
        self,
        tenant_id: str,
        user_id: str,
        name: str,
        *,
        scopes: Any = None,
        policy: Any = None,
        read_folders: list[str] | None = None,
        write_folders: list[str] | None = None,
        calls_per_day: int | None = None,
        kind: Kind = "client",
    ) -> tuple[Connection, str]:
        """A new connection and its secret, which is shown once and never stored in the open."""
        cid = new_id()
        secret = new_secret(cid)
        if calls_per_day is not None and not 1 <= calls_per_day <= 100_000:
            raise ValueError("the daily quota is 1 to 100,000 calls")
        connection = Connection(
            id=cid, tenant_id=tenant_id, user_id=user_id, name=check_name(name),
            secret_hash=hash_secret(secret),
            scopes=check_scopes(scopes) if scopes is not None else DEFAULT_SCOPES,
            policy=check_policy(policy), read_folders=tuple(read_folders or ()),
            write_folders=(
                tuple(write_folders) if write_folders is not None else (default_export_folder(),)
            ),
            calls_per_day=calls_per_day if calls_per_day is not None else DEFAULT_DAILY,
            kind=kind,
        )  # fmt: skip
        await self.store.create(connection)
        return connection, secret

    async def mine(self, tenant_id: str, user_id: str, connection_id: str) -> Connection:
        c = await self.store.get(connection_id)
        if c is None or (c.tenant_id, c.user_id) != (tenant_id, user_id):
            raise KeyError(connection_id)
        return c

    async def update(
        self, tenant_id: str, user_id: str, connection_id: str, changes: dict[str, Any]
    ) -> Connection:
        c = await self.mine(tenant_id, user_id, connection_id)
        fields: dict[str, Any] = {}
        if "name" in changes:
            fields["name"] = check_name(changes["name"])
        if "scopes" in changes:
            fields["scopes"] = check_scopes(changes["scopes"])
        if "approval" in changes:
            fields["policy"] = check_policy(changes["approval"])
        for key in ("read_folders", "write_folders"):
            if key in changes:
                value = changes[key]
                if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
                    raise ValueError(f"{key} must be a list of folder paths")
                fields[key] = tuple(value)
        if "calls_per_day" in changes:
            daily = int(changes["calls_per_day"])
            if not 1 <= daily <= 100_000:
                raise ValueError("the daily quota is 1 to 100,000 calls")
            fields["calls_per_day"] = daily
        if "rate_per_minute" in changes:
            rate = int(changes["rate_per_minute"])
            if not 1 <= rate <= 600:
                raise ValueError("the rate is 1 to 600 calls a minute")
            fields["rate_per_minute"] = rate
        updated = replace(c, **fields)
        await self.store.save(updated)
        return updated

    async def rotate(
        self, tenant_id: str, user_id: str, connection_id: str
    ) -> tuple[Connection, str]:
        c = await self.mine(tenant_id, user_id, connection_id)
        secret = new_secret(c.id)
        updated = replace(c, secret_hash=hash_secret(secret), revoked_at=None)
        await self.store.save(updated)
        return updated, secret

    async def revoke(self, tenant_id: str, user_id: str, connection_id: str) -> Connection:
        c = await self.mine(tenant_id, user_id, connection_id)
        updated = replace(c, revoked_at=_now())
        await self.store.save(updated)
        return updated

    async def verify(self, credential: str) -> Connection:
        """The connection a bearer belongs to, or `AuthError` (safe to log, not to show)."""
        cid = connection_id_of(credential)
        if cid is None:
            raise AuthError("not a connection secret")
        c = await self.store.get(cid)
        if c is None or not secret_matches(credential, c.secret_hash):
            raise AuthError("unknown connection or wrong secret")
        if c.revoked:
            raise AuthError("the connection was revoked")
        return c

    async def touch(self, connection: Connection) -> None:
        await self.store.save(replace(connection, last_used_at=_now()))
