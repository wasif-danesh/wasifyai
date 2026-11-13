"""Desktop-profile stores that live in the API package because their interfaces do (users, the
settings and the creation index). Same rules as the Postgres stores (ADR-0030,
ADR-0041) on the SQLite file the desktop profile uses (ADR-0056)."""

import asyncio
import json
import math
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import IndexItem
from wasifyai_platform_sdk.search import MAX_TEXT_CHARS
from wasifyai_platform_sdk.sqlite import Migration, migrate, now_iso

from wasifyai_api.auth import Claims
from wasifyai_api.creation_index import Hit, like_patterns
from wasifyai_api.users import UserRecord

_USERS_DDL = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        email TEXT,
        email_verified INTEGER NOT NULL DEFAULT 0,
        name TEXT,
        image TEXT,
        role TEXT NOT NULL DEFAULT 'user',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_users_tenant_email ON users (tenant_id, lower(email))",
    """
    CREATE TABLE IF NOT EXISTS user_identities (
        tenant_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        provider_account_id TEXT NOT NULL,
        user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, provider, provider_account_id)
    )
    """,
)

# the store's shape before the migration runner (stage J1); a change is a new Migration(2, ...)
_USERS_MIGRATIONS = (Migration(1, _USERS_DDL),)


def _email(claims: Claims) -> str | None:
    return claims.email.lower() if claims.email else None


class SqliteUserStore:
    """The linking rule of ADR-0030, unchanged: a new provider account joins an existing user only
    when both emails are verified and equal."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine
        self._lock = asyncio.Lock()  # one process: first sign-ins are made one at a time

    async def resolve(
        self, tenant_id: str, claims: Claims, admin_emails: frozenset[str]
    ) -> UserRecord:
        await migrate(self._engine, "users", _USERS_MIGRATIONS)
        email = _email(claims)
        verified = claims.email_verified and email is not None
        admin = verified and (email or "") in admin_emails
        params = {
            "tenant": tenant_id,
            "provider": claims.provider,
            "account": claims.account_id,
            "email": email,
            "verified": 1 if verified else 0,
            "name": claims.name,
            "image": claims.image,
            "now": now_iso(),
        }
        async with self._lock, self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT user_id FROM user_identities WHERE tenant_id = :tenant "
                        "AND provider = :provider AND provider_account_id = :account"
                    ),
                    params,
                )
            ).first()
            user_id = row[0] if row else None
            if user_id is None and verified:
                match = (
                    await conn.execute(
                        text(
                            "SELECT id FROM users WHERE tenant_id = :tenant AND email_verified = 1 "
                            "AND lower(email) = :email ORDER BY created_at LIMIT 1"
                        ),
                        params,
                    )
                ).first()
                user_id = match[0] if match else None
            if user_id is None:
                user_id = str(uuid4())
                await conn.execute(
                    text(
                        "INSERT INTO users (id, tenant_id, created_at) VALUES (:id, :tenant, :now)"
                    ),
                    {**params, "id": user_id},
                )
            await conn.execute(
                text(
                    "INSERT INTO user_identities (tenant_id, provider, provider_account_id, "
                    "user_id, created_at) VALUES (:tenant, :provider, :account, :id, :now) "
                    "ON CONFLICT DO NOTHING"
                ),
                {**params, "id": user_id},
            )
            role = (
                await conn.execute(
                    text(
                        "UPDATE users SET email = :email, email_verified = :verified, "
                        "name = :name, image = :image, "
                        "role = CASE WHEN :admin THEN 'admin' ELSE role END "
                        "WHERE id = :id RETURNING role"
                    ),
                    {**params, "id": user_id, "admin": 1 if admin else 0},
                )
            ).scalar_one()
        return UserRecord(str(user_id), role)


_SETTINGS_DDL = (
    """
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    )
    """,
)

# the store's shape before the migration runner (stage J1); a change is a new Migration(2, ...)
_SETTINGS_MIGRATIONS = (Migration(1, _SETTINGS_DDL),)


class SqliteSettingsStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def get(self, key: str) -> object | None:
        await migrate(self._engine, "system_settings", _SETTINGS_MIGRATIONS)
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT value FROM system_settings WHERE key = :k"), {"k": key}
                )
            ).first()
        return None if row is None else json.loads(row[0])

    async def put(self, key: str, value: object, by: str) -> None:
        await migrate(self._engine, "system_settings", _SETTINGS_MIGRATIONS)
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO system_settings (key, value, updated_by, updated_at) "
                    "VALUES (:k, :v, :by, :now) ON CONFLICT (key) DO UPDATE "
                    "SET value = excluded.value, updated_by = excluded.updated_by, "
                    "updated_at = excluded.updated_at"
                ),
                {"k": key, "v": json.dumps(value), "by": by, "now": now_iso()},
            )


_INDEX_DDL = (
    """
    CREATE TABLE IF NOT EXISTS creation_index (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        item_id TEXT NOT NULL,
        text TEXT NOT NULL,
        folded TEXT NOT NULL,
        model TEXT NOT NULL,
        embedding TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_creation_index_item "
    "ON creation_index (tenant_id, product_id, item_id)",
    "CREATE INDEX IF NOT EXISTS ix_creation_index_user "
    "ON creation_index (tenant_id, user_id, kind)",
)

# the store's shape before the migration runner (stage J1); a change is a new Migration(2, ...)
_INDEX_MIGRATIONS = (Migration(1, _INDEX_DDL),)


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / ((math.hypot(*a) * math.hypot(*b)) or 1.0)


class SqliteIndexStore:
    """Vectors are kept as JSON and compared in Python: exact, and fast enough for the thousands
    of creations one person makes. A vector index (sqlite-vec) is a later step if it is measured to
    be needed (ADR-0060)."""

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        await migrate(self._engine, "creation_index", _INDEX_MIGRATIONS)

    async def upsert(self, item: IndexItem, model: str, vector: list[float]) -> None:
        await self._ready()
        body = item.text[:MAX_TEXT_CHARS]
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO creation_index
                        (id, tenant_id, product_id, user_id, kind, item_id, text, folded, model,
                         embedding, created_at)
                    VALUES (:id, :t, :p, :u, :k, :i, :x, :f, :m, :v, :c)
                    ON CONFLICT (tenant_id, product_id, item_id) DO UPDATE SET
                        user_id = excluded.user_id, kind = excluded.kind, text = excluded.text,
                        folded = excluded.folded, model = excluded.model,
                        embedding = excluded.embedding
                    """
                ),
                {
                    "id": str(uuid4()), "t": item.tenant_id, "p": item.product_id,
                    "u": item.user_id, "k": item.kind, "i": item.item_id, "x": body,
                    "f": body.lower(), "m": model, "v": json.dumps(vector), "c": now_iso(),
                },
            )  # fmt: skip

    async def delete(self, tenant_id: str, product_id: str, item_id: str) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM creation_index WHERE tenant_id = :t AND product_id = :p "
                    "AND item_id = :i"
                ),
                {"t": tenant_id, "p": product_id, "i": item_id},
            )

    async def delete_ids(self, product_id: str, item_ids: list[str]) -> None:
        await self._ready()
        async with self._engine.begin() as conn:
            for chunk in _chunks(item_ids):
                marks = ",".join(f":i{n}" for n in range(len(chunk)))
                await conn.execute(
                    text(
                        f"DELETE FROM creation_index WHERE product_id = :p AND item_id IN ({marks})"
                    ),
                    {"p": product_id, **{f"i{n}": v for n, v in enumerate(chunk)}},
                )

    async def nearest(
        self, tenant_id: str, user_id: str, vector: list[float], kind: str | None, limit: int
    ) -> list[Hit]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT product_id, kind, item_id, embedding FROM creation_index "
                        "WHERE tenant_id = :t AND user_id = :u AND (:k IS NULL OR kind = :k)"
                    ),
                    {"t": tenant_id, "u": user_id, "k": kind},
                )
            ).all()
        hits = [Hit(r[1], r[0], r[2], _cosine(vector, json.loads(r[3])), "meaning") for r in rows]
        return sorted(hits, key=lambda h: -h.score)[:limit]

    async def with_words(
        self, tenant_id: str, user_id: str, words: list[str], kind: str | None, limit: int
    ) -> list[Hit]:
        if not words:
            return []
        await self._ready()
        patterns = like_patterns(words)
        clauses = " AND ".join(f"folded LIKE :w{n} ESCAPE '\\'" for n in range(len(patterns)))
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT product_id, kind, item_id FROM creation_index "
                        "WHERE tenant_id = :t AND user_id = :u AND (:k IS NULL OR kind = :k) "
                        f"AND {clauses} ORDER BY created_at DESC LIMIT :n"
                    ),
                    {
                        "t": tenant_id, "u": user_id, "k": kind, "n": limit,
                        **{f"w{n}": p for n, p in enumerate(patterns)},
                    },
                )
            ).all()  # fmt: skip
        return [Hit(r[1], r[0], r[2], 1.0, "words") for r in rows]

    async def models(self, product_id: str, item_ids: list[str]) -> dict[str, str]:
        await self._ready()
        found: dict[str, str] = {}
        async with self._engine.connect() as conn:
            for chunk in _chunks(item_ids):
                marks = ",".join(f":i{n}" for n in range(len(chunk)))
                rows = await conn.execute(
                    text(
                        "SELECT item_id, model FROM creation_index "
                        f"WHERE product_id = :p AND item_id IN ({marks})"
                    ),
                    {"p": product_id, **{f"i{n}": v for n, v in enumerate(chunk)}},
                )
                found.update({r[0]: r[1] for r in rows})
        return found

    async def ids_after(self, product_id: str, after: str | None, limit: int) -> list[str]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT item_id FROM creation_index WHERE product_id = :p "
                    "AND (:a IS NULL OR item_id > :a) ORDER BY item_id LIMIT :n"
                ),
                {"p": product_id, "a": after, "n": limit},
            )
            return [r[0] for r in rows]


def _chunks(items: list[str], size: int = 500) -> list[list[str]]:
    """SQLite caps the number of bound parameters in one statement."""
    return [items[i : i + size] for i in range(0, len(items), size)]
