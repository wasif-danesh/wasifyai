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

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from weakref import WeakKeyDictionary

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

log = logging.getLogger("wasifyai_platform_sdk.sqlite")

# the stores that are up to date, per engine (gone when the engine is)
_CREATED: WeakKeyDictionary[AsyncEngine, set[str]] = WeakKeyDictionary()
BACKUPS_KEPT = 5  # copies of a database file kept in backups/, newest first


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
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    return engine


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
    async with engine.connect() as conn:
        await conn.exec_driver_sql(_VERSIONS_DDL)
        await conn.commit()
        have = await _version(conn, store)
        if have > latest:
            raise SchemaTooNew(
                f"The {store} data was made by a newer version of Wasify AI. Update the app."
            )
        if have < latest:
            if have > 0:  # a store with data is about to change: keep a copy first
                await _back_up(conn, engine, store, have)
            await _apply(conn, store, migrations, latest)
    done.add(store)


async def _version(conn: AsyncConnection, store: str) -> int:
    row = (
        await conn.exec_driver_sql("SELECT version FROM schema_versions WHERE store = ?", (store,))
    ).first()
    return int(row[0]) if row else 0


async def _apply(
    conn: AsyncConnection, store: str, migrations: Sequence[Migration], latest: int
) -> None:
    # SQLite runs DDL inside a transaction; it is begun here by hand, because the driver begins one
    # only before a change of rows, so a failed step would leave the steps before it in place
    await conn.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        have = await _version(conn, store)  # another process may have done it meanwhile
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
