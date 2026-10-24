# SPDX-License-Identifier: Apache-2.0
"""What Motion graphics keeps, on Postgres, for the web profile (ADR-0087, P4).

The same store as the desktop's (`BuilderStore`, SQLite): every method, with the same ownership
rules, runs the same SQL through `_connect`; only the connection and the schema are here. The
tables live in their own schema (`builder`). A composition is its template and its slots: the page
is made from them whenever it is drawn, so no project files are kept; the finished videos are
clips of the video library, in object storage."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from wasifyai_platform_sdk.pg import PgDb, check_schema_name, open_pool

from wasifyai_video.builder.store import _SCHEMA, SCHEMA_VERSION, BuilderStore, now

LOCK_KEY = 0x62646C72  # "bdlr": the advisory lock that serialises schema creation


def _postgres(ddl: str) -> str:
    """The SQLite tables as Postgres has them: serial keys, full-width numbers."""
    return (
        ddl.replace("BEGIN;", "")
        .replace("COMMIT;", "")
        .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        .replace(" REAL", " DOUBLE PRECISION")
    )


class PostgresBuilderStore(BuilderStore):
    """`BuilderStore` on a Postgres connection pool. Synchronous like the SQLite one."""

    def __init__(self, dsn: str, *, schema: str = "builder", max_connections: int = 8):
        check_schema_name(schema)
        self.schema = schema
        self.root = Path(tempfile.gettempdir())  # nothing is kept in files
        self.path = self.root / "builder.unused"
        self._pool = open_pool(dsn, schema, max_connections=max_connections, dict_rows=True)
        try:
            self._init()
        except BaseException:
            self._pool.close()
            raise

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def _connect(self) -> Iterator[PgDb]:  # type: ignore[override]
        with self._pool.connection() as conn:
            yield PgDb(conn)

    def _init(self) -> None:
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')  # pyright: ignore[reportArgumentType, reportCallIssue]
            fresh = (
                conn.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = 'meta'",
                    (self.schema,),
                ).fetchone()
                is None
            )
            if fresh:
                for statement in _postgres(_SCHEMA).split(";"):
                    if statement.strip():
                        conn.execute(statement)  # pyright: ignore[reportArgumentType, reportCallIssue]
                conn.execute("INSERT INTO meta VALUES ('schema', %s)", (str(SCHEMA_VERSION),))
                return
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        if not row or int(row["value"]) > SCHEMA_VERSION:
            raise RuntimeError(
                "the Motion graphics tables were made by a newer version of this app"
            )

    def fail_stale(self, before: str, message: str) -> int:
        """Fail renders still working since before `before`: nobody is working on them."""
        with self._connect() as db:
            return int(
                db.execute(
                    "UPDATE renders SET status = 'failed', error = ?, finished_at = ? "
                    "WHERE status = 'working' AND started_at < ?",
                    (message, now(), before),
                ).rowcount
            )

    def drop_schema(self) -> None:
        """Remove every table of this store (tests)."""
        with self._pool.connection() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')  # pyright: ignore[reportArgumentType, reportCallIssue]
