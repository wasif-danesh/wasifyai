# SPDX-License-Identifier: Apache-2.0
"""What the voice product keeps, on Postgres, for the web profile (docs/phase3-web-parity-plan, W5).

The same store as the desktop's (`VoiceStore`, SQLite): every method, with the same ownership
rules (each row carries its tenant and user and every read and write is scoped by both), runs the
same SQL. Only the connection and the schema are here. The tables live in their own schema (`voice`,
or the one given) so their plain names (`speeches`, `tracks`) cannot meet another product's. The
audio itself is not in the database: its key is, and the file is in object storage.
"""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from wasifyai_platform_sdk.pg import PgDb, check_schema_name, open_pool

from wasifyai_voice.store import (
    _CLIPS,
    _SPEECHES,
    _TRACKS,
    _TRANSCRIPTS,
    _VOICES,
    SCHEMA_VERSION,
    VoiceStore,
)

LOCK_KEY = 0x766F6963  # "voic": the advisory lock that serialises schema creation


def _postgres(ddl: str) -> str:
    """The product's SQLite tables as Postgres has them: full-width numbers."""
    return ddl.replace(" REAL", " DOUBLE PRECISION").replace("seed INTEGER", "seed BIGINT")


class PostgresVoiceStore(VoiceStore):
    """`VoiceStore` on a Postgres connection pool. Synchronous like the SQLite one."""

    def __init__(self, dsn: str, *, schema: str = "voice", max_connections: int = 8):
        check_schema_name(schema)
        self.schema = schema
        # a cloned voice's recording is read from a file by the desktop's runtime; the web offers no
        # cloning yet, so this folder is only where `reference_path` would point
        self.root = Path(tempfile.gettempdir()) / "voice-references"
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
                conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                for ddl in (_SPEECHES, _TRANSCRIPTS, _VOICES, _TRACKS, _CLIPS):
                    conn.execute(_postgres(ddl))  # pyright: ignore[reportArgumentType, reportCallIssue]
                conn.execute("INSERT INTO meta VALUES ('schema', %s)", (str(SCHEMA_VERSION),))
                return
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        version = int(row["value"]) if row else 0
        if version > SCHEMA_VERSION or version < 1:
            raise RuntimeError("the voice tables were made by a newer version of this app")

    def drop_schema(self) -> None:
        """Remove every table of this store (tests, and a deployment that starts over)."""
        with self._pool.connection() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')  # pyright: ignore[reportArgumentType, reportCallIssue]
