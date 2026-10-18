# SPDX-License-Identifier: Apache-2.0
"""The notebooks database on Postgres, for the web profile (docs/phase3-web-parity-plan.md, W4).

It is the same store as the desktop's (`NotebookStore`, SQLite): every method, with the same
ownership rules, runs the same SQL. Only what a database differs in is here: the connection, the
schema, and how passages are kept. The keyword leg keeps each passage's terms (as the same
tokenizer cuts them) in an array with a GIN index, and the semantic leg keeps its vector in a
pgvector column of the passage row, so deleting a passage deletes its vector and a search filters
by notebook and source before it ranks.

The tables live in their own schema (`notebooks`, or the one given) so their plain names
(`documents`, `conversations`) cannot meet another product's; each connection puts it first on the
search path. The product owns its schema (ADR-0065): `PostgresNotebookStore` creates and checks it
when it starts, with an advisory lock so several replicas can start together.
"""

import json
import logging
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from wasifyai_platform_sdk.pg import PgDb, check_schema_name, open_pool, vector_text

from wasifyai_notebooks.chunking import Passage
from wasifyai_notebooks.store import SCHEMA_VERSION, Conflict, NotebookStore
from wasifyai_notebooks.tokenizer import terms

log = logging.getLogger(__name__)
PRODUCT_ID = "wasifyai-notebooks"
LOCK_KEY = 0x6E6F7465  # "note": the advisory lock that serialises schema creation


def _ddl(dimension: int) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS notebooks(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, title TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, opened_at TEXT,
  guide TEXT, guide_key TEXT);
CREATE INDEX IF NOT EXISTS notebooks_owner ON notebooks(tenant_id, user_id, updated_at);

CREATE TABLE IF NOT EXISTS folders(
  id TEXT PRIMARY KEY,
  notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES folders(id) ON DELETE CASCADE,
  name TEXT NOT NULL, name_key TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS folders_name
  ON folders(notebook_id, COALESCE(parent_id, ''), name_key);

CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY,
  notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  folder_id TEXT REFERENCES folders(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('file', 'note')),
  status TEXT NOT NULL,
  error TEXT,
  priority INTEGER NOT NULL DEFAULT 100,
  mime TEXT, suffix TEXT, size_bytes BIGINT, sha256 TEXT, pages INTEGER,
  content TEXT,
  embedder TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS documents_dedup
  ON documents(notebook_id, COALESCE(folder_id, ''), sha256) WHERE sha256 IS NOT NULL;
CREATE INDEX IF NOT EXISTS documents_notebook ON documents(notebook_id, created_at);
CREATE INDEX IF NOT EXISTS documents_queue ON documents(status, priority DESC, created_at);

CREATE TABLE IF NOT EXISTS chunks(
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  position INTEGER NOT NULL, content TEXT NOT NULL, start_line INTEGER, end_line INTEGER,
  terms TEXT[] NOT NULL DEFAULT '{{}}',
  embedding vector({dimension}),
  UNIQUE(document_id, position));
CREATE INDEX IF NOT EXISTS chunks_terms ON chunks USING GIN (terms);

CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY,
  notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS conversations_notebook ON conversations(notebook_id, updated_at);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  text TEXT NOT NULL,
  citations TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  UNIQUE(conversation_id, seq));

CREATE TABLE IF NOT EXISTS artifacts(
  id TEXT PRIMARY KEY,
  notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  format TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  error TEXT,
  prompt TEXT NOT NULL DEFAULT '',
  source_ids TEXT NOT NULL DEFAULT '[]',
  body TEXT,
  data TEXT,
  file_name TEXT,
  file_mime TEXT,
  request TEXT,
  claimed_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS artifacts_notebook ON artifacts(notebook_id, created_at);
-- a schema made before outputs were queued gets the two columns
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS request TEXT;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS claimed_at TEXT;
"""


class PostgresNotebookStore(NotebookStore):
    """`NotebookStore` on a Postgres connection pool. Synchronous like the SQLite one: the engine
    calls it from a thread."""

    _INTEGRITY = (psycopg.IntegrityError,)

    def __init__(
        self,
        dsn: str,
        *,
        dimension: int,
        embedder_id: str,
        schema: str = "notebooks",
        max_connections: int = 8,
    ):
        """`dsn` is a libpq connection string or URL (`postgresql://...`, not the SQLAlchemy
        `+asyncpg` form). `dimension` and `embedder_id` are what the index is built with; an index
        built with another embedder is refused, not mixed (ADR-0065 decision 8)."""
        check_schema_name(schema)
        self.dimension = dimension
        self.embedder_id = embedder_id
        self.schema = schema
        self._pool = open_pool(dsn, schema, max_connections=max_connections)
        try:
            self._init()
        except BaseException:
            self._pool.close()
            raise

    def close(self) -> None:
        self._pool.close()

    # ---- connection -------------------------------------------------------------------------

    @contextmanager
    def connect(self) -> Iterator[PgDb]:  # type: ignore[override]
        with self._pool.connection() as conn:
            yield PgDb(conn)

    @contextmanager
    def _tx(self) -> Iterator[PgDb]:  # type: ignore[override]
        with self._pool.connection() as conn, conn.transaction():
            yield PgDb(conn)

    def _guard(self, db: Any) -> Any:
        return db.transaction()  # a savepoint: a violated constraint leaves the transaction usable

    # ---- the schema -------------------------------------------------------------------------

    def _init(self) -> None:
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')  # pyright: ignore[reportArgumentType, reportCallIssue]
            have = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
            if have is None:
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            fresh = (
                conn.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = 'meta'",
                    (self.schema,),
                ).fetchone()
                is None
            )
            conn.execute(_ddl(self.dimension))  # pyright: ignore[reportArgumentType, reportCallIssue]
            if fresh:
                conn.execute(
                    "INSERT INTO meta(key, value) "
                    "VALUES ('schema', %s), ('embedder', %s), ('dimension', %s)",
                    (str(SCHEMA_VERSION), self.embedder_id, str(self.dimension)),
                )
                return
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        if meta.get("embedder") != self.embedder_id or meta.get("dimension") != str(self.dimension):
            raise Conflict(
                f"This library was indexed with {meta.get('embedder')}; "
                f"{self.embedder_id} needs the documents read again first."
            )

    # ---- passages ---------------------------------------------------------------------------

    def _replace_chunks(
        self,
        db: Any,
        did: str,
        passages: Sequence[Passage],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        db.execute("DELETE FROM chunks WHERE document_id = ?", (did,))
        for position, (p, v) in enumerate(zip(passages, vectors, strict=True)):
            db.execute(
                "INSERT INTO chunks(document_id, position, content, start_line, end_line, "
                "terms, embedding) VALUES (?,?,?,?,?,?,CAST(? AS vector))",
                (did, position, p.text, p.start_line, p.end_line, terms(p.text), vector_text(v)),
            )

    def record_usage(
        self, tenant: str, user: str, kind: str, quantity: float, unit: str, **meta: Any
    ) -> None:
        """A row in the platform's `usage_events` table (what billing reads); best effort, so a
        failure to note it never fails the work."""
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    "INSERT INTO public.usage_events "
                    "(id, tenant_id, product_id, user_id, kind, quantity, unit, meta) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::json)",
                    (
                        uuid.uuid4(),
                        tenant,
                        PRODUCT_ID,
                        user,
                        kind,
                        quantity,
                        unit,
                        json.dumps(meta),
                    ),
                )
        except Exception:  # noqa: BLE001 - usage is noted, not required
            log.warning("could not record usage", exc_info=True)

    def drop_schema(self) -> None:
        """Remove every table of this store (for tests and for a deployment that starts over)."""
        with self._pool.connection() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')  # pyright: ignore[reportArgumentType, reportCallIssue]
