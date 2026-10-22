# SPDX-License-Identifier: Apache-2.0
"""What the 3D product keeps, on Postgres, for the web profile (ADR-0087, P3).

The same store as the desktop's (`Model3dStore`, SQLite): every method, with the same ownership
rules (each row carries its tenant and user and every read and write is scoped by both), runs the
same SQL; only the connection and the schema are here. The tables live in their own schema
(`model3d`) and the pictures and models themselves are files in object storage."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.pg import PgDb, check_schema_name, open_pool

from wasifyai_model3d.store import DDL, SCHEMA, Model3dStore

LOCK_KEY = 0x6D336421  # "m3d!": the advisory lock that serialises schema creation


def _postgres(ddl: str) -> str:
    """The SQLite tables as Postgres has them: full-width numbers."""
    return ddl.replace(" REAL", " DOUBLE PRECISION").replace(
        "glb_bytes INTEGER", "glb_bytes BIGINT"
    )


class PostgresModel3dStore(Model3dStore):
    """`Model3dStore` on a Postgres connection pool. Synchronous like the SQLite one."""

    def __init__(self, dsn: str, *, schema: str = "model3d", max_connections: int = 8):
        check_schema_name(schema)
        self.schema = schema
        self._pool = open_pool(dsn, schema, max_connections=max_connections, dict_rows=True)
        try:
            self._init()
        except BaseException:
            self._pool.close()
            raise

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def _connect(self) -> Iterator[PgDb]:
        with self._pool.connection() as conn:
            yield PgDb(conn)

    def _init(self) -> None:
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')  # pyright: ignore[reportArgumentType, reportCallIssue]
            for statement in _postgres(DDL).split(";"):
                if statement.strip():
                    conn.execute(statement)  # pyright: ignore[reportArgumentType, reportCallIssue]
            conn.execute(
                "INSERT INTO meta VALUES ('schema', %s) ON CONFLICT DO NOTHING", (str(SCHEMA),)
            )

    # ---- the three calls every query goes through -----------------------------------------

    def _one(self, sql: str, args: tuple[Any, ...]) -> Any:
        with self._connect() as db:
            return db.execute(sql, args).fetchone()

    def _all(self, sql: str, args: tuple[Any, ...] = ()) -> list[Any]:
        with self._connect() as db:
            return list(db.execute(sql, args).fetchall())

    def _exec(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        with self._connect() as db:
            return int(db.execute(sql, args).rowcount)

    def folder_of(self, tenant: str, user: str, kind: str, item_id: str) -> Path:
        raise NotImplementedError("the web keeps these files in object storage")

    def drop_schema(self) -> None:
        """Remove every table of this store (tests)."""
        with self._pool.connection() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')  # pyright: ignore[reportArgumentType, reportCallIssue]
