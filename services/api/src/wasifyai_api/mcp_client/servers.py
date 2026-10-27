"""A server the person added (ADR-0070 decisions 2, 4, 6, 7, 11), where it is kept, and the rules
its address or command must pass before anything connects."""

import ipaddress
import re
import shlex
import socket
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk.sqlite.engine import ensure_tables, from_iso, is_sqlite, to_iso

Transport = Literal["http", "stdio"]
Trust = Literal["ask", "blocked"]  # `trusted_read_only` arrives with stage C2
TRANSPORTS: tuple[Transport, ...] = ("http", "stdio")
TRUSTS: tuple[Trust, ...] = ("ask", "blocked")
NAME_MAX = 40
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
DEFAULT_TIMEOUT_S = 60
MIN_TIMEOUT_S, MAX_TIMEOUT_S = 5, 600
LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", "[::1]"}
SECRET_AREA = "mcp.client"  # secret names: mcp.client.<server id>.token / .env.<name>


def _now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid4().hex[:16]


def check_name(name: Any) -> str:
    """A short name the model refers to the server by (`call_external("github", ...)`)."""
    name = " ".join(str(name or "").split())
    if not name or len(name) > NAME_MAX:
        raise ValueError(f"give the server a name of up to {NAME_MAX} characters")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$", name):
        raise ValueError("a name is letters, digits, spaces, dots, dashes and underscores")
    return name


def is_private_address(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast


def check_url(raw: Any) -> str:
    """Decision 6: `https` only, except loopback; no credentials in the address; a private or
    link-local address only when the person typed exactly that address (not a name that
    resolves to one: that is checked again when connecting, `resolve_host`)."""
    url = str(raw or "").strip()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise ValueError("the address must start with https:// and name a host")
    if parts.username or parts.password:
        raise ValueError("put a token in the token field, not in the address")
    if "\n" in url or "\r" in url or " " in url:
        raise ValueError("the address holds a character that is not allowed")
    loopback = host in LOOPBACK_NAMES
    if parts.scheme == "http" and not loopback:
        raise ValueError("a server on another computer must be reached over https")
    return url


def typed_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def resolve_host(url: str) -> None:
    """Refuse an address whose name resolves to a private or link-local address unless the person
    typed that address itself (the SSRF rule of decision 6). Raises ValueError."""
    host = (urlsplit(url).hostname or "").lower()
    if host in LOOPBACK_NAMES or typed_ip(host):
        return
    try:
        found = socket.getaddrinfo(host, None)
    except OSError as e:
        raise ValueError(f"{host} could not be found: {e}") from None
    for info in found:
        ip = str(info[4][0]).split("%", 1)[0]
        if is_private_address(ip):
            raise ValueError(
                f"{host} points at a private address ({ip}); type that address itself if "
                "you mean it"
            )


def check_command(raw: Any) -> str:
    cmd = str(raw or "").strip()
    if not cmd or "\0" in cmd or "\n" in cmd:
        raise ValueError("give the command that starts the server")
    return cmd


def check_args(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = shlex.split(raw)
    if not isinstance(raw, list) or not all(isinstance(a, str) for a in raw):
        raise ValueError("the arguments are a list of words")
    return tuple(a for a in raw if "\0" not in a)


def check_env_names(raw: Any) -> tuple[str, ...]:
    names = tuple(str(n).strip() for n in (raw or ()) if str(n).strip())
    for n in names:
        if not ENV_NAME.match(n):
            raise ValueError(f"{n} is not an environment variable name (upper case, no spaces)")
    return names


def check_tools(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = raw.replace(",", "\n").split("\n")
    if not isinstance(raw, list):
        raise ValueError("the allowed tools are a list of tool names")
    return tuple(sorted({str(t).strip() for t in raw if str(t).strip()}))


def check_timeout(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise ValueError("the timeout is a number of seconds") from None
    if not MIN_TIMEOUT_S <= n <= MAX_TIMEOUT_S:
        raise ValueError(f"the timeout is {MIN_TIMEOUT_S} to {MAX_TIMEOUT_S} seconds")
    return n


def env_secret_name(server_id: str, env_name: str) -> str:
    return f"{SECRET_AREA}.{server_id}.env.{env_name.lower()}"


def token_secret_name(server_id: str) -> str:
    return f"{SECRET_AREA}.{server_id}.token"


@dataclass(frozen=True)
class Server:
    id: str
    tenant_id: str
    user_id: str
    name: str
    transport: Transport
    url: str = ""  # http
    command: str = ""  # stdio
    args: tuple[str, ...] = ()
    env_names: tuple[str, ...] = ()  # the values live in the secret store
    has_token: bool = False  # a bearer token in the secret store (http)
    trust: Trust = "ask"
    allowed_tools: tuple[str, ...] = ()  # () means every tool the server lists
    timeout_s: int = DEFAULT_TIMEOUT_S
    keep_content: bool = False  # decision 11: arguments and results in the activity log
    created_at: datetime = field(default_factory=_now)
    last_used_at: datetime | None = None
    calls: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    failures: int = 0  # in a row; three mark the server unhealthy (decision 9)
    last_error: str = ""

    @property
    def host(self) -> str:
        """What the egress card shows (decision 6): the host, or the command's first word."""
        if self.transport == "http":
            return (urlsplit(self.url).hostname or "").lower()
        return self.command.split("/")[-1]

    @property
    def unhealthy(self) -> bool:
        return self.failures >= 3

    def allows(self, tool: str) -> bool:
        return not self.allowed_tools or tool in self.allowed_tools

    def public(self) -> dict[str, Any]:
        """What Settings shows and what the model is told about: never a secret."""
        return {
            "id": self.id, "name": self.name, "transport": self.transport, "url": self.url,
            "command": self.command, "args": list(self.args), "host": self.host,
            "env_names": list(self.env_names), "has_token": self.has_token,
            "trust": self.trust, "allowed_tools": list(self.allowed_tools),
            "timeout_s": self.timeout_s, "keep_content": self.keep_content,
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "calls": self.calls, "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received, "failures": self.failures,
            "unhealthy": self.unhealthy, "last_error": self.last_error,
        }  # fmt: skip


@dataclass(frozen=True)
class ClientActivity:
    server_id: str
    tool: str
    status: str  # ok, error, timeout, refused
    duration_ms: int
    bytes_sent: int
    bytes_received: int
    content: str = ""  # "" unless the server's `keep_content` is on
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=_now)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d


class ServerStore(Protocol):
    async def create(self, server: Server) -> None: ...

    async def get(self, server_id: str) -> Server | None: ...

    async def for_person(self, tenant_id: str, user_id: str) -> list[Server]: ...

    async def save(self, server: Server) -> None: ...

    async def delete(self, server_id: str) -> None: ...

    async def record(self, entry: ClientActivity) -> None: ...

    async def activity(self, server_id: str, limit: int = 50) -> list[ClientActivity]: ...


class InMemoryServerStore:
    def __init__(self) -> None:
        self.rows: dict[str, Server] = {}
        self.entries: list[ClientActivity] = []

    async def create(self, server: Server) -> None:
        self.rows[server.id] = server

    async def get(self, server_id: str) -> Server | None:
        return self.rows.get(server_id)

    async def for_person(self, tenant_id: str, user_id: str) -> list[Server]:
        mine = [s for s in self.rows.values() if (s.tenant_id, s.user_id) == (tenant_id, user_id)]
        return sorted(mine, key=lambda s: s.created_at)

    async def save(self, server: Server) -> None:
        self.rows[server.id] = server

    async def delete(self, server_id: str) -> None:
        self.rows.pop(server_id, None)
        self.entries = [e for e in self.entries if e.server_id != server_id]

    async def record(self, entry: ClientActivity) -> None:
        self.entries.append(entry)

    async def activity(self, server_id: str, limit: int = 50) -> list[ClientActivity]:
        mine = [e for e in self.entries if e.server_id == server_id]
        return list(reversed(mine))[:limit]


_DDL = (
    """
    CREATE TABLE IF NOT EXISTS mcp_servers (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        transport TEXT NOT NULL,
        url TEXT NOT NULL DEFAULT '',
        command TEXT NOT NULL DEFAULT '',
        args TEXT NOT NULL DEFAULT '',
        env_names TEXT NOT NULL DEFAULT '',
        has_token INTEGER NOT NULL DEFAULT 0,
        trust TEXT NOT NULL DEFAULT 'ask',
        allowed_tools TEXT NOT NULL DEFAULT '',
        timeout_s INTEGER NOT NULL DEFAULT 60,
        keep_content INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        calls INTEGER NOT NULL DEFAULT 0,
        bytes_sent INTEGER NOT NULL DEFAULT 0,
        bytes_received INTEGER NOT NULL DEFAULT 0,
        failures INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_mcp_servers_user ON mcp_servers (tenant_id, user_id)",
    """
    CREATE TABLE IF NOT EXISTS mcp_client_activity (
        id TEXT PRIMARY KEY,
        server_id TEXT NOT NULL,
        tool TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT '',
        duration_ms INTEGER NOT NULL DEFAULT 0,
        bytes_sent INTEGER NOT NULL DEFAULT 0,
        bytes_received INTEGER NOT NULL DEFAULT 0,
        content TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_mcp_client_activity_server "
    "ON mcp_client_activity (server_id, created_at)",
)
COLUMNS = (
    "id, tenant_id, user_id, name, transport, url, command, args, env_names, has_token, trust, "
    "allowed_tools, timeout_s, keep_content, created_at, last_used_at, calls, bytes_sent, "
    "bytes_received, failures, last_error"
)


def _split(value: Any) -> tuple[str, ...]:
    return tuple(s for s in str(value or "").split("\n") if s)


class SqlServerStore:
    """SQLite (created on first use) and Postgres (Alembic 0025)."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        if is_sqlite(self._engine):
            await ensure_tables(self._engine, "mcp_servers", _DDL)

    def _stamp(self, when: datetime | None) -> Any:
        if when is None:
            return None
        return to_iso(when) if is_sqlite(self._engine) else when

    @staticmethod
    def _moment(value: Any) -> datetime | None:
        if value is None:
            return None
        return from_iso(value) if isinstance(value, str) else value

    def _params(self, s: Server) -> dict[str, Any]:
        return {
            "id": s.id, "tenant_id": s.tenant_id, "user_id": s.user_id, "name": s.name,
            "transport": s.transport, "url": s.url, "command": s.command,
            "args": "\n".join(s.args), "env_names": "\n".join(s.env_names),
            "has_token": int(s.has_token), "trust": s.trust,
            "allowed_tools": "\n".join(s.allowed_tools), "timeout_s": s.timeout_s,
            "keep_content": int(s.keep_content), "created_at": self._stamp(s.created_at),
            "last_used_at": self._stamp(s.last_used_at), "calls": s.calls,
            "bytes_sent": s.bytes_sent, "bytes_received": s.bytes_received,
            "failures": s.failures, "last_error": s.last_error,
        }  # fmt: skip

    def _row(self, r: Any) -> Server:
        m = dict(r._mapping)
        return Server(
            id=m["id"], tenant_id=m["tenant_id"], user_id=m["user_id"], name=m["name"],
            transport=m["transport"], url=m["url"], command=m["command"],
            args=_split(m["args"]), env_names=_split(m["env_names"]),
            has_token=bool(m["has_token"]), trust=m["trust"],
            allowed_tools=_split(m["allowed_tools"]), timeout_s=int(m["timeout_s"]),
            keep_content=bool(m["keep_content"]),
            created_at=self._moment(m["created_at"]) or _now(),
            last_used_at=self._moment(m["last_used_at"]), calls=int(m["calls"]),
            bytes_sent=int(m["bytes_sent"]), bytes_received=int(m["bytes_received"]),
            failures=int(m["failures"]), last_error=m["last_error"] or "",
        )  # fmt: skip

    async def create(self, server: Server) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    f"INSERT INTO mcp_servers ({COLUMNS}) VALUES (:id, :tenant_id, :user_id, "
                    ":name, :transport, :url, :command, :args, :env_names, :has_token, :trust, "
                    ":allowed_tools, :timeout_s, :keep_content, :created_at, :last_used_at, "
                    ":calls, :bytes_sent, :bytes_received, :failures, :last_error)"
                ),
                self._params(server),
            )

    async def get(self, server_id: str) -> Server | None:
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(f"SELECT {COLUMNS} FROM mcp_servers WHERE id = :id"), {"id": server_id}
                )
            ).first()
        return self._row(row) if row else None

    async def for_person(self, tenant_id: str, user_id: str) -> list[Server]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    f"SELECT {COLUMNS} FROM mcp_servers WHERE tenant_id = :t AND user_id = :u "
                    "ORDER BY created_at"
                ),
                {"t": tenant_id, "u": user_id},
            )
            return [self._row(r) for r in rows]

    async def save(self, server: Server) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE mcp_servers SET name = :name, url = :url, command = :command, "
                    "args = :args, env_names = :env_names, has_token = :has_token, "
                    "trust = :trust, allowed_tools = :allowed_tools, timeout_s = :timeout_s, "
                    "keep_content = :keep_content, last_used_at = :last_used_at, calls = :calls, "
                    "bytes_sent = :bytes_sent, bytes_received = :bytes_received, "
                    "failures = :failures, last_error = :last_error WHERE id = :id"
                ),
                self._params(server),
            )

    async def delete(self, server_id: str) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM mcp_client_activity WHERE server_id = :id"), {"id": server_id}
            )
            await conn.execute(text("DELETE FROM mcp_servers WHERE id = :id"), {"id": server_id})

    async def record(self, entry: ClientActivity) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO mcp_client_activity (id, server_id, tool, status, duration_ms, "
                    "bytes_sent, bytes_received, content, created_at) VALUES (:id, :s, :tool, "
                    ":status, :d, :bs, :br, :content, :at)"
                ),
                {
                    "id": entry.id,
                    "s": entry.server_id,
                    "tool": entry.tool,
                    "status": entry.status,
                    "d": entry.duration_ms,
                    "bs": entry.bytes_sent,
                    "br": entry.bytes_received,
                    "content": entry.content,
                    "at": self._stamp(entry.created_at),
                },  # fmt: skip
            )

    async def activity(self, server_id: str, limit: int = 50) -> list[ClientActivity]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, server_id, tool, status, duration_ms, bytes_sent, bytes_received, "
                    "content, created_at FROM mcp_client_activity WHERE server_id = :s "
                    "ORDER BY created_at DESC LIMIT :n"
                ),
                {"s": server_id, "n": max(1, min(limit, 500))},
            )
            return [
                ClientActivity(
                    id=r.id,
                    server_id=r.server_id,
                    tool=r.tool,
                    status=r.status,
                    duration_ms=int(r.duration_ms),
                    bytes_sent=int(r.bytes_sent),
                    bytes_received=int(r.bytes_received),
                    content=r.content or "",
                    created_at=self._moment(r.created_at) or _now(),
                )  # fmt: skip
                for r in rows
            ]


class ServersService:
    """What Settings does with servers. Values (a token, an environment variable) go to the
    secret store under the server's id and never into a row (decision 7)."""

    def __init__(self, store: ServerStore, secrets: Any):
        self.store = store
        self.secrets = secrets

    async def create(
        self,
        tenant_id: str,
        user_id: str,
        name: str,
        transport: str,
        *,
        url: str = "",
        command: str = "",
        args: Any = None,
        env: Mapping[str, str] | None = None,
        token: str | None = None,
        trust: str = "ask",
        allowed_tools: Any = None,
        timeout_s: Any = DEFAULT_TIMEOUT_S,
    ) -> Server:
        if transport not in TRANSPORTS:
            raise ValueError("the transport is http or stdio")
        if trust not in TRUSTS:
            raise ValueError("trust is ask or blocked")
        env = dict(env or {})
        env_names = check_env_names(list(env))
        sid = new_id()
        server = Server(
            id=sid, tenant_id=tenant_id, user_id=user_id, name=check_name(name),
            transport=transport,  # type: ignore[arg-type]
            url=check_url(url) if transport == "http" else "",
            command=check_command(command) if transport == "stdio" else "",
            args=check_args(args) if transport == "stdio" else (),
            env_names=env_names if transport == "stdio" else (),
            has_token=bool(token) and transport == "http",
            trust=trust,  # type: ignore[arg-type]
            allowed_tools=check_tools(allowed_tools), timeout_s=check_timeout(timeout_s),
        )  # fmt: skip
        if server.transport == "http":
            resolve_host(server.url)
        for n in server.env_names:
            await self.secrets.put(env_secret_name(sid, n), str(env[n]))
        if server.has_token and token:
            await self.secrets.put(token_secret_name(sid), token.strip())
        await self.store.create(server)
        return server

    async def mine(self, tenant_id: str, user_id: str, server_id: str) -> Server:
        s = await self.store.get(server_id)
        if s is None or (s.tenant_id, s.user_id) != (tenant_id, user_id):
            raise KeyError(server_id)
        return s

    async def by_name(self, tenant_id: str, user_id: str, name: str) -> Server | None:
        wanted = " ".join(str(name).split()).lower()
        for s in await self.store.for_person(tenant_id, user_id):
            if s.name.lower() == wanted or s.id == name:
                return s
        return None

    async def update(self, s: Server, changes: Mapping[str, Any]) -> Server:
        fields: dict[str, Any] = {}
        if "name" in changes:
            fields["name"] = check_name(changes["name"])
        if "trust" in changes:
            if changes["trust"] not in TRUSTS:
                raise ValueError("trust is ask or blocked")
            fields["trust"] = changes["trust"]
        if "allowed_tools" in changes:
            fields["allowed_tools"] = check_tools(changes["allowed_tools"])
        if "timeout_s" in changes:
            fields["timeout_s"] = check_timeout(changes["timeout_s"])
        if "keep_content" in changes:
            fields["keep_content"] = bool(changes["keep_content"])
        if "url" in changes and s.transport == "http":
            fields["url"] = check_url(changes["url"])
            resolve_host(fields["url"])
        if "command" in changes and s.transport == "stdio":
            fields["command"] = check_command(changes["command"])
        if "args" in changes and s.transport == "stdio":
            fields["args"] = check_args(changes["args"])
        if "env" in changes and s.transport == "stdio":
            env = dict(changes["env"] or {})
            names = check_env_names(list(env))
            for n in names:  # a value given replaces; an empty value removes
                if str(env[n]):
                    await self.secrets.put(env_secret_name(s.id, n), str(env[n]))
                else:
                    await self.secrets.delete(env_secret_name(s.id, n))
            kept = [n for n in s.env_names if n not in names] + [n for n in names if env[n]]
            fields["env_names"] = tuple(dict.fromkeys(kept))
        if "token" in changes and s.transport == "http":
            token = str(changes["token"] or "").strip()
            if token:
                await self.secrets.put(token_secret_name(s.id), token)
            else:
                await self.secrets.delete(token_secret_name(s.id))
            fields["has_token"] = bool(token)
        if "reset" in changes and changes["reset"]:
            fields["failures"], fields["last_error"] = 0, ""
        updated = replace(s, **fields)
        await self.store.save(updated)
        return updated

    async def delete(self, s: Server) -> None:
        """Decision 11: deleting a server deletes its secrets and its entries."""
        for n in s.env_names:
            await self.secrets.delete(env_secret_name(s.id, n))
        await self.secrets.delete(token_secret_name(s.id))
        await self.store.delete(s.id)

    async def env_of(self, s: Server) -> dict[str, str]:
        out: dict[str, str] = {}
        for n in s.env_names:
            v = await self.secrets.get(env_secret_name(s.id, n))
            if v is not None:
                out[n] = v
        return out

    async def token_of(self, s: Server) -> str | None:
        return await self.secrets.get(token_secret_name(s.id)) if s.has_token else None

    async def note_call(
        self, s: Server, *, ok: bool, error: str, sent: int, received: int
    ) -> Server:
        """The counters of decision 6 and the health of decision 9, after a call."""
        fresh = await self.store.get(s.id) or s
        updated = replace(
            fresh, calls=fresh.calls + 1, bytes_sent=fresh.bytes_sent + sent,
            bytes_received=fresh.bytes_received + received, last_used_at=_now(),
            failures=0 if ok else fresh.failures + 1, last_error="" if ok else error[:300],
        )  # fmt: skip
        await self.store.save(updated)
        return updated
