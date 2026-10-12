"""Our users and the provider accounts that sign in as them (ADR-0030).

The linking rule is deliberately narrow: a new provider account joins an existing user only when
both emails are verified and equal. Anything else creates a separate user, because an unverified
address could belong to someone else.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_api.auth import Claims


@dataclass(frozen=True)
class UserRecord:
    id: str
    role: str


class UserStore(Protocol):
    async def resolve(
        self, tenant_id: str, claims: Claims, admin_emails: frozenset[str]
    ) -> UserRecord:
        """Find or create the user for these claims, linking identities as described above."""
        ...


def _email(claims: Claims) -> str | None:
    return claims.email.lower() if claims.email else None


def _is_admin(claims: Claims, admin_emails: frozenset[str]) -> bool:
    return claims.email_verified and (_email(claims) or "") in admin_emails


class InMemoryUserStore:
    """Same rules as the Postgres store, for tests."""

    def __init__(self) -> None:
        self._users: dict[str, dict] = {}
        self._identities: dict[tuple[str, str, str], str] = {}

    async def resolve(
        self, tenant_id: str, claims: Claims, admin_emails: frozenset[str]
    ) -> UserRecord:
        key = (tenant_id, claims.provider, claims.account_id)
        email = _email(claims)
        verified = claims.email_verified and email is not None
        user_id = self._identities.get(key)
        if user_id is None:
            if verified:
                user_id = next(
                    (
                        uid
                        for uid, u in self._users.items()
                        if u["tenant"] == tenant_id and u["verified"] and u["email"] == email
                    ),
                    None,
                )
            if user_id is None:
                user_id = str(uuid.uuid4())
                self._users[user_id] = {"tenant": tenant_id, "role": "user"}
            self._identities[key] = user_id
        user = self._users[user_id]
        user.update(email=email, verified=verified, name=claims.name, image=claims.image)
        if _is_admin(claims, admin_emails):
            user["role"] = "admin"
        return UserRecord(user_id, user["role"])


class PostgresUserStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def resolve(
        self, tenant_id: str, claims: Claims, admin_emails: frozenset[str]
    ) -> UserRecord:
        email = _email(claims)
        verified = claims.email_verified and email is not None
        params = {
            "tenant": tenant_id,
            "provider": claims.provider,
            "account": claims.account_id,
            "email": email,
            "verified": verified,
            "name": claims.name,
            "image": claims.image,
        }
        async with self._engine.begin() as conn:
            # One first sign-in at a time per identity, so two requests cannot create two users.
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                {"k": f"{tenant_id}|{claims.provider}|{claims.account_id}"},
            )
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
                            "SELECT id FROM users WHERE tenant_id = :tenant AND email_verified "
                            "AND lower(email) = :email ORDER BY created_at LIMIT 1"
                        ),
                        params,
                    )
                ).first()
                user_id = match[0] if match else None
            if user_id is None:
                user_id = uuid.uuid4()
                await conn.execute(
                    text("INSERT INTO users (id, tenant_id) VALUES (:id, :tenant)"),
                    {**params, "id": user_id},
                )
            await conn.execute(
                text(
                    "INSERT INTO user_identities (tenant_id, provider, provider_account_id, "
                    "user_id) VALUES (:tenant, :provider, :account, :id) ON CONFLICT DO NOTHING"
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
                    {**params, "id": user_id, "admin": _is_admin(claims, admin_emails)},
                )
            ).scalar_one()
        return UserRecord(str(user_id), role)


class CachedUsers:
    """Remembers resolved users briefly so a request does not always cost a database round trip."""

    def __init__(self, store: UserStore, ttl_s: float = 60.0, max_entries: int = 2048):
        self._store = store
        self._ttl = ttl_s
        self._max = max_entries
        self._cache: dict[tuple, tuple[float, UserRecord]] = {}

    async def resolve(
        self, tenant_id: str, claims: Claims, admin_emails: frozenset[str]
    ) -> UserRecord:
        key = (tenant_id, claims, admin_emails)
        hit = self._cache.get(key)
        now = time.monotonic()
        if hit and hit[0] > now:
            return hit[1]
        record = await self._store.resolve(tenant_id, claims, admin_emails)
        if len(self._cache) >= self._max:
            self._cache.clear()
        self._cache[key] = (now + self._ttl, record)
        return record
