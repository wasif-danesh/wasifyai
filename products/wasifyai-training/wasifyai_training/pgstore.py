# ruff: noqa: E501
# SPDX-License-Identifier: Apache-2.0
"""What the training product keeps, on Postgres, for the web profile (ADR-0073 amendment 2026-10-27, `docs/train-web-plan.md`).

The same store as the desktop's (`TrainingStore`, SQLite): every method, with the same ownership rules
(each row carries its tenant and user and every read and write is scoped by both), runs the same SQL; only
the connection and the schema are here. The tables live in their own schema (`training`); the pictures,
clips, samples, adapters and models themselves are files in object storage (`files.py`)."""

import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.pg import PgDb, check_schema_name, open_pool

from wasifyai_training.store import DDL, SCHEMA, TrainingStore, _slug, new_id, now

LOCK_KEY = 0x74726E21  # "trn!": the advisory lock that serialises schema creation
LEFT_RUNNING_WEB = "It was stopped when the service restarted. Start it again."

# what a later version added to a table an older one made: Postgres says it in one statement
COLUMNS = (
    ("datasets", "family", "TEXT NOT NULL DEFAULT 'image'"),
    ("items", "media", "TEXT NOT NULL DEFAULT 'picture'"),
    ("items", "seconds", "DOUBLE PRECISION"),
    ("items", "frames", "INTEGER"),
)


def _postgres(ddl: str) -> str:
    """The SQLite tables as Postgres has them: full-width numbers."""
    return ddl.replace(" REAL", " DOUBLE PRECISION").replace(
        "adapter_bytes INTEGER", "adapter_bytes BIGINT"
    )


class PostgresTrainingStore(TrainingStore):
    """`TrainingStore` on a Postgres connection pool. Synchronous like the SQLite one."""

    def __init__(
        self, dsn: str, *, schema: str = "training", max_connections: int = 8,
        cache: Path | None = None,
    ):  # fmt: skip
        check_schema_name(schema)
        self.schema = schema
        # the API's working folders; the files themselves are in object storage (`files.py`)
        self.folder = cache or Path(tempfile.gettempdir()) / "wasifyai-training"
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
            for table, column, ddl in COLUMNS:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")  # pyright: ignore[reportArgumentType, reportCallIssue]
            conn.execute(
                "INSERT INTO meta VALUES ('schema', %s) ON CONFLICT DO NOTHING", (str(SCHEMA),)
            )

    def runs_left_working(self) -> list[dict[str, Any]]:
        """Runs a service that is gone left going: the web has no checkpoint to pick up (a worker's
        job is cancelled by the caller), so each is failed with a sentence."""
        rows = self._all("SELECT id, tenant_id, user_id FROM runs WHERE status = 'working'")
        for r in rows:
            self._exec(
                "UPDATE runs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                (LEFT_RUNNING_WEB, now(), r["id"]),
            )
        self._exec("UPDATE items SET caption_state = 'none' WHERE caption_state = 'writing'")
        return [dict(r) for r in rows]

    # ---- the plumbing every query goes through -----------------------------------------------

    def _one(self, sql: str, args: tuple[Any, ...]) -> Any:
        with self._connect() as db:
            return db.execute(sql, args).fetchone()

    def _all(self, sql: str, args: tuple[Any, ...] = ()) -> list[Any]:
        with self._connect() as db:
            return list(db.execute(sql, args).fetchall())

    def _exec(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        with self._connect() as db:
            return int(db.execute(sql, args).rowcount)

    def _replace_rows(
        self,
        delete_sql: str,
        delete_args: tuple[Any, ...],
        insert_sql: str,
        rows: list[tuple[Any, ...]],
    ) -> None:
        with self._pool.connection() as conn, conn.transaction():
            db = PgDb(conn)
            db.execute(delete_sql, delete_args)
            for row in rows:
                db.execute(insert_sql, row)

    def folder_of(self, tenant: str, user: str, kind: str, item_id: str) -> Path:
        """A working folder on this computer for the item; its truth is in object storage."""
        if not re.fullmatch(r"[0-9a-f]{32}", item_id):
            raise ValueError("not an id")
        return self.folder / "files" / _slug(tenant) / _slug(user) / kind / item_id

    def drop_schema(self) -> None:
        """Remove every table of this store (tests)."""
        with self._pool.connection() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')  # pyright: ignore[reportArgumentType, reportCallIssue]


__all__ = ["PostgresTrainingStore", "new_id"]
