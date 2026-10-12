"""Which backend runs a product's media capability (ADR-0025), stored in Postgres.

No binding means "use what the product's config says" (local ComfyUI). The API writes bindings; the
media worker reads them for every job, so a change applies to the next job. The secret (an API key)
is stored encrypted and only the worker decrypts it."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class MediaBinding:
    product_id: str
    capability: str
    backend: str
    config: dict[str, Any] = field(default_factory=dict)
    secret_enc: str | None = None  # encrypted; never leaves the server
    updated_by: str | None = None
    updated_at: datetime | None = None

    @property
    def key_set(self) -> bool:
        return self.secret_enc is not None


class MediaBindingStore(Protocol):
    async def get(
        self, tenant_id: str, product_id: str, capability: str
    ) -> MediaBinding | None: ...
    async def list(self, tenant_id: str) -> list[MediaBinding]: ...
    async def put(self, tenant_id: str, binding: MediaBinding) -> None: ...
    async def delete(self, tenant_id: str, product_id: str, capability: str) -> None: ...


class InMemoryMediaBindingStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], MediaBinding] = {}

    async def get(self, tenant_id: str, product_id: str, capability: str) -> MediaBinding | None:
        return self._rows.get((tenant_id, product_id, capability))

    async def list(self, tenant_id: str) -> list[MediaBinding]:
        return [b for (t, _, _), b in self._rows.items() if t == tenant_id]

    async def put(self, tenant_id: str, binding: MediaBinding) -> None:
        self._rows[(tenant_id, binding.product_id, binding.capability)] = binding

    async def delete(self, tenant_id: str, product_id: str, capability: str) -> None:
        self._rows.pop((tenant_id, product_id, capability), None)


class PostgresMediaBindingStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    @staticmethod
    def _row(r) -> MediaBinding:
        config = r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}")
        return MediaBinding(
            product_id=r[0], capability=r[1], backend=r[2], config=config, secret_enc=r[4],
            updated_by=r[5], updated_at=r[6],
        )  # fmt: skip

    _COLUMNS = "product_id, capability, backend, config, secret_enc, updated_by, updated_at"

    async def get(self, tenant_id: str, product_id: str, capability: str) -> MediaBinding | None:
        sql = text(
            f"SELECT {self._COLUMNS} FROM media_bindings "
            "WHERE tenant_id = :t AND product_id = :p AND capability = :c"
        )
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(sql, {"t": tenant_id, "p": product_id, "c": capability})
            ).first()
        return self._row(row) if row else None

    async def list(self, tenant_id: str) -> list[MediaBinding]:
        sql = text(f"SELECT {self._COLUMNS} FROM media_bindings WHERE tenant_id = :t ORDER BY 1, 2")
        async with self._engine.connect() as conn:
            rows = (await conn.execute(sql, {"t": tenant_id})).all()
        return [self._row(r) for r in rows]

    async def put(self, tenant_id: str, binding: MediaBinding) -> None:
        sql = text(
            """
            INSERT INTO media_bindings (tenant_id, product_id, capability, backend, config,
                                        secret_enc, updated_by, updated_at)
            VALUES (:t, :p, :c, :b, CAST(:cfg AS json), :s, :u, now())
            ON CONFLICT (tenant_id, product_id, capability) DO UPDATE
              SET backend = :b, config = CAST(:cfg AS json), secret_enc = :s,
                  updated_by = :u, updated_at = now()
            """
        )
        params = {
            "t": tenant_id, "p": binding.product_id, "c": binding.capability, "b": binding.backend,
            "cfg": json.dumps(binding.config), "s": binding.secret_enc, "u": binding.updated_by,
        }  # fmt: skip
        async with self._engine.begin() as conn:
            await conn.execute(sql, params)

    async def delete(self, tenant_id: str, product_id: str, capability: str) -> None:
        sql = text(
            "DELETE FROM media_bindings "
            "WHERE tenant_id = :t AND product_id = :p AND capability = :c"
        )
        async with self._engine.begin() as conn:
            await conn.execute(sql, {"t": tenant_id, "p": product_id, "c": capability})
