"""The SQLite engine behind the desktop profile (ADR-0056).

One database file under the app data directory holds everything the web profile keeps in Postgres
and Redis: records, the run event log and the job queue. Timestamps are stored as UTC ISO strings
with microseconds, so they sort and compare as text and need no driver adapters.

Each store owns its tables and brings them up to date on first use with `migrate`: a list of
numbered migrations, the way Alembic revisions own the web profile's tables (stage J1 of the
2026-10-27 plan). The file keeps one version per store in `schema_versions` (the stores share one
file, so `PRAGMA user_version`, one number per file, cannot say it). Migration 1 of every store is
the shape it had before the runner existed, written so it is safe on a file that already has it
(`CREATE TABLE IF NOT EXISTS`, columns added when missing). A later migration may change anything,
renames and dropped columns included: before a store that already has a version is changed, a copy
of the file is put in `backups/` beside it, and the store's migrations run in one transaction.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

log = logging.getLogger("wasifyai_platform_sdk.sqlite")

# the stores that are up to date, per engine (gone when the engine is)
_CREATED: WeakKeyDictionary[AsyncEngine, set[str]] = WeakKeyDictionary()
# the migrations under way, per engine and store, so a cancel never cuts one off
_RUNNING: WeakKeyDictionary[AsyncEngine, dict[str, "asyncio.Task[None]"]] = WeakKeyDictionary()
BACKUPS_KEPT = 5  # copies of a database file kept in backups/, newest first
LOCK_TRIES = 8  # a refused write lock is asked for again this many times
WAL_TRIES = 100  # and the switch of a new file to WAL (0.05 s apart)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def to_iso(value: datetime) -> str:
    """UTC text with a fixed width, so string order is time order. A naive value means UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def from_iso(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def create_sqlite_engine(path: Path | str) -> AsyncEngine:
    """An async engine on a database file (created with its folder when missing). WAL keeps readers
    from blocking the one writer; `busy_timeout` makes a second writer wait instead of failing."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{file}", connect_args={"timeout": 30})

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_connection, _record) -> None:
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA busy_timeout=30000")
        _wal(cur)
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def _wal(cur: Any) -> None:
    """WAL, which a file keeps once set. Only the first connection to a new file switches it, and
    SQLite refuses the switch at once, without waiting, while another connection has the file
    open: the switch is tried again for a moment."""
    cur.execute("PRAGMA journal_mode")
    if str(cur.fetchone()[0]).lower() == "wal":
        return
    for attempt in range(WAL_TRIES):
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            return
        except Exception as e:  # the driver's own OperationalError, wrapped or not
            if "locked" not in str(e) or attempt == WAL_TRIES - 1:
                raise
            time.sleep(0.05)


def is_sqlite(engine: AsyncEngine) -> bool:
    return engine.dialect.name == "sqlite"


_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_versions (
    store TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class Migration:
    """One step of a store's schema: its statements, then the columns an older file may lack
    (`columns`: table -> {column: definition}, added only when missing), then `run` for anything
    that is not a statement (copying data over). Steps run in order inside one transaction."""

    version: int
    statements: Sequence[str] = ()
    columns: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    run: Callable[[AsyncConnection], Awaitable[None]] | None = None


class SchemaTooNew(RuntimeError):
    """The file was brought up to date by a newer version of the app than this one."""


async def migrate(engine: AsyncEngine, store: str, migrations: Sequence[Migration]) -> None:
    """Bring `store` up to its last migration, once per engine. Safe with two processes on one
    file: the write lock is taken before the version is read for the last time."""
    done = _CREATED.setdefault(engine, set())
    if store in done:
        return
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"the migrations of {store} must be numbered 1, 2, 3 ... in order")
    latest = len(migrations)
    # A migration is never stopped half-way: a cancel (the app stopping) waits for it to end. A
    # transaction cut off by a cancel left its connection being torn down while it still held the
    # file's write lock, and every other store waited behind it. Callers at the same time share it.
    running = _RUNNING.setdefault(engine, {})
    task = running.get(store)
    if task is None or task.done():
        task = asyncio.ensure_future(_migrate(engine, store, migrations, latest))
        running[store] = task
    await asyncio.shield(task)
    done.add(store)


async def _migrate(
    engine: AsyncEngine, store: str, migrations: Sequence[Migration], latest: int
) -> None:
    async with engine.connect() as conn:
        # the usual case, every start: the store is current, which a read says without a lock
        have = await _version(conn, store)
        await conn.commit()
        _not_newer(store, have, latest)
        if have == latest:
            return
        if have > 0:  # a store with data is about to change: keep a copy first
            await _back_up(conn, engine, store, have)
        await _apply(conn, store, migrations, latest)


def _not_newer(store: str, have: int, latest: int) -> None:
    if have > latest:
        raise SchemaTooNew(
            f"The {store} data was made by a newer version of Wasify AI. Update the app."
        )


async def _version(conn: AsyncConnection, store: str) -> int:
    """The store's version; 0 for a file that has no versions yet."""
    try:
        row = (
            await conn.exec_driver_sql(
                "SELECT version FROM schema_versions WHERE store = ?", (store,)
            )
        ).first()
    except OperationalError as e:
        if "no such table" not in str(e):
            raise
        await conn.rollback()
        return 0
    return int(row[0]) if row else 0


async def _begin_immediate(conn: AsyncConnection) -> None:
    """Take the file's write lock. SQLite waits for another writer (busy_timeout), but refuses at
    once in a few cases (two connections that both read first); those are tried again briefly."""
    for attempt in range(LOCK_TRIES):
        try:
            await conn.exec_driver_sql("BEGIN IMMEDIATE")
            return
        except OperationalError as e:
            if "locked" not in str(e) or attempt == LOCK_TRIES - 1:
                raise
            await asyncio.sleep(0.1 * (attempt + 1))


async def _apply(
    conn: AsyncConnection, store: str, migrations: Sequence[Migration], latest: int
) -> None:
    # SQLite runs DDL inside a transaction; it is begun here by hand, because the driver begins one
    # only before a change of rows, so a failed step would leave the steps before it in place
    await _begin_immediate(conn)
    try:
        await conn.exec_driver_sql(_VERSIONS_DDL)
        have = await _version(conn, store)  # another process may have done it meanwhile
        _not_newer(store, have, latest)
        for m in migrations[have:]:
            for statement in m.statements:
                await conn.exec_driver_sql(statement)
            for table, columns in m.columns.items():
                rows = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
                present = {str(r._mapping["name"]) for r in rows}
                for column, definition in columns.items():
                    if column not in present:
                        await conn.exec_driver_sql(
                            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                        )
            if m.run is not None:
                await m.run(conn)
        if have < latest:
            await conn.exec_driver_sql(
                "INSERT INTO schema_versions (store, version, applied_at) VALUES (?, ?, ?) "
                "ON CONFLICT (store) DO UPDATE SET version = excluded.version, "
                "applied_at = excluded.applied_at",
                (store, latest, now_iso()),
            )
            log.info("%s: schema version %d to %d", store, have, latest)
        await conn.exec_driver_sql("COMMIT")
    except BaseException:
        # the original error (a cancel above all) must come out, never one from the rollback: a
        # cancel that arrives while BEGIN still waits for the lock has no transaction to roll back,
        # and a loop that retries on any error would then never stop
        with contextlib.suppress(Exception):
            await conn.exec_driver_sql("ROLLBACK")
        raise


async def _back_up(conn: AsyncConnection, engine: AsyncEngine, store: str, version: int) -> None:
    """A whole copy of the database file in `backups/` beside it (`VACUUM INTO` is consistent while
    others write). Only the newest `BACKUPS_KEPT` copies of a file are kept."""
    name = engine.url.database
    if not name or name == ":memory:" or name.startswith("file:"):
        return
    file = Path(name)
    folder = file.parent / "backups"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    copy = folder / f"{file.stem}-{stamp}-{store}-v{version}.db"
    quoted = str(copy).replace("'", "''")
    await conn.exec_driver_sql(f"VACUUM INTO '{quoted}'")
    await conn.commit()
    log.info("%s: copied %s to %s before changing it", store, file.name, copy)
    for old in sorted(folder.glob(f"{file.stem}-*.db"), reverse=True)[BACKUPS_KEPT:]:
        old.unlink(missing_ok=True)
