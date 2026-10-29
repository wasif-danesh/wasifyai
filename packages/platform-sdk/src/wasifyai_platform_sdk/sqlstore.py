"""One store, two databases (stage J2 of the 2026-10-27 plan).

A product that keeps its own tables (notebooks, 3D, training, voice, Motion graphics) writes one
store class over a `StoreDb`: a SQLite file on the desktop (`SqliteStoreDb`) or its own schema in
the deployment's Postgres on the web (`PostgresStoreDb`). The store writes its SQL once, with `?`
parameters, and asks the database for what differs:

    db.one / db.all / db.exec           a statement in its own short transaction
    with db.connect() as c: c.execute   several statements on one connection (each commits)
    with db.transaction() as c: ...     several statements that stand or fall together
    db.open_tables(ddl, columns=...)    the tables, made the first time and grown later

The DDL is written once in types both databases read the same way: `BIGINT` for a number that can
pass two thousand million, `DOUBLE PRECISION` for a fraction, `TEXT` for times (UTC ISO strings that
sort as text) and JSON. `INSERT ... ON CONFLICT` and `RETURNING` mean the same on both. A row reads
by column name on both (`row["title"]`); a store that reads by position asks for `rows="tuple"`.
"""

import contextlib
import sqlite3
import threading
import zlib
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, Protocol

from wasifyai_platform_sdk.pg import PgDb, check_schema_name, open_pool

Column = tuple[str, str, str]  # (table, column, its definition): a column a later version added


class Cursor(Protocol):
    rowcount: int

    def fetchone(self) -> Any: ...

    def fetchall(self) -> list[Any]: ...

    def __iter__(self) -> Iterator[Any]: ...


class Conn(Protocol):
    """What a block of statements runs on: SQLite's connection, or `PgDb` on Postgres."""

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any: ...


class StoreDb(Protocol):
    dialect: str  # "sqlite" | "postgres"

    def connect(self) -> contextlib.AbstractContextManager[Any]: ...

    def transaction(self) -> contextlib.AbstractContextManager[Any]: ...

    def one(self, sql: str, args: Sequence[Any] = ()) -> Any: ...

    def all(self, sql: str, args: Sequence[Any] = ()) -> list[Any]: ...

    def exec(self, sql: str, args: Sequence[Any] = ()) -> int: ...

    def open_tables(
        self,
        ddl: str,
        columns: Sequence[Column] = (),
        before: Callable[[Any], None] | None = None,
    ) -> None: ...

    def close(self) -> None: ...


def ddl_for(ddl: str, dialect: str) -> str:
    """Shared DDL as `dialect` has it. The one thing written differently: a counting key
    (`INTEGER PRIMARY KEY AUTOINCREMENT` in SQLite, `BIGSERIAL PRIMARY KEY` in Postgres)."""
    if dialect != "postgres":
        return ddl
    return ddl.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")


def _statements(ddl: str) -> list[str]:
    return [s for s in (part.strip() for part in ddl.split(";")) if s]


class SqliteStoreDb:
    """One SQLite file. By default one connection shared by the store's threads behind a lock (the
    stores are called from worker threads as well as the event loop); with `shared=False` a new
    connection for each block, in autocommit, so readers do not wait for a long write (WAL lets
    them read alongside it). `on_open` prepares each connection (an extension to load)."""

    dialect = "sqlite"

    def __init__(
        self,
        path: Path,
        rows: str = "mapping",
        timeout_s: float = 10.0,
        *,
        shared: bool = True,
        on_open: Callable[[sqlite3.Connection], None] | None = None,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._rows, self._timeout, self._on_open = rows, timeout_s, on_open
        self._lock = threading.RLock()
        self._db = self._open(autocommit=False) if shared else None

    def _open(self, autocommit: bool) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, check_same_thread=False, timeout=self._timeout)
        if autocommit:
            db.isolation_level = None  # each statement commits; BEGIN starts a transaction
        if self._rows == "mapping":
            db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA foreign_keys = ON")
        if self._on_open is not None:
            self._on_open(db)
        return db

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if self._db is None:  # a connection of its own, each statement committed as it runs
            db = self._open(autocommit=True)
            try:
                yield db
            finally:
                db.close()
            return
        with self._lock:
            try:
                yield self._db
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as db:
            if self._db is not None:
                db.commit()  # nothing may be pending before the explicit transaction
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    def one(self, sql: str, args: Sequence[Any] = ()) -> Any:
        with self.connect() as c:
            return c.execute(sql, tuple(args)).fetchone()

    def all(self, sql: str, args: Sequence[Any] = ()) -> list[Any]:
        with self.connect() as c:
            return list(c.execute(sql, tuple(args)).fetchall())

    def exec(self, sql: str, args: Sequence[Any] = ()) -> int:
        with self.connect() as c:
            return int(c.execute(sql, tuple(args)).rowcount)

    def open_tables(
        self,
        ddl: str,
        columns: Sequence[Column] = (),
        before: Callable[[Any], None] | None = None,
    ) -> None:
        """Make the tables a new file lacks and add the columns an older file lacks. `before` runs
        first, for a change a file made by an older version needs (a table rebuilt)."""
        with self.connect() as db:
            if before is not None:
                before(db)
            db.executescript(ddl)
        if not columns:
            return
        # under SQLite's write lock (BEGIN IMMEDIATE), as Postgres does under its advisory lock:
        # replicas starting together would otherwise each see a column missing and each add it
        with self.transaction() as db:
            for table, column, definition in columns:
                have = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                if column not in have:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def close(self) -> None:
        if self._db is not None:
            with self._lock:
                self._db.close()


class PostgresStoreDb:
    """The store's own schema in the deployment's Postgres, on a connection pool whose connections
    look at that schema first. Synchronous, like the SQLite one."""

    dialect = "postgres"

    def __init__(self, dsn: str, schema: str, *, rows: str = "mapping", max_connections: int = 8):
        self.schema = check_schema_name(schema)
        self._pool = open_pool(
            dsn, schema, max_connections=max_connections, dict_rows=rows == "mapping"
        )

    @contextlib.contextmanager
    def connect(self) -> Iterator[PgDb]:
        with self._pool.connection() as conn:
            yield PgDb(conn)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[PgDb]:
        with self._pool.connection() as conn, conn.transaction():
            yield PgDb(conn)

    def one(self, sql: str, args: Sequence[Any] = ()) -> Any:
        with self.connect() as c:
            return c.execute(sql, args).fetchone()

    def all(self, sql: str, args: Sequence[Any] = ()) -> list[Any]:
        with self.connect() as c:
            return list(c.execute(sql, args).fetchall())

    def exec(self, sql: str, args: Sequence[Any] = ()) -> int:
        with self.connect() as c:
            return int(c.execute(sql, args).rowcount)

    def open_tables(
        self,
        ddl: str,
        columns: Sequence[Column] = (),
        before: Callable[[Any], None] | None = None,
    ) -> None:
        """The schema and its tables, made once whatever the number of replicas starting at the
        same time (an advisory lock per schema), and the columns a later version added. `before` is
        for SQLite files of older versions and is not run here."""
        lock = zlib.crc32(self.schema.encode())  # one lock per schema, the same on every replica
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')  # pyright: ignore[reportArgumentType, reportCallIssue]
            for statement in _statements(ddl):
                conn.execute(statement)  # pyright: ignore[reportArgumentType, reportCallIssue]
            for table, column, definition in columns:
                conn.execute(  # pyright: ignore[reportCallIssue]
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"  # pyright: ignore[reportArgumentType]
                )

    def drop(self) -> None:
        """Remove the schema and every table in it (tests)."""
        with self._pool.connection() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')  # pyright: ignore[reportArgumentType, reportCallIssue]

    def close(self) -> None:
        self._pool.close()
