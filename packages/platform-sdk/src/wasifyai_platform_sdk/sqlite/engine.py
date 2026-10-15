"""The SQLite engine behind the desktop profile (ADR-0056).

One database file under the app data directory holds everything the web profile keeps in Postgres
and Redis: records, the run event log and the job queue. Timestamps are stored as UTC ISO strings
with microseconds, so they sort and compare as text and need no driver adapters.

Each adapter owns the DDL of its tables and creates them on first use (`ensure_tables`), the way
each Alembic revision owns its own tables in the web profile. Schema changes must stay additive
(`CREATE TABLE IF NOT EXISTS`, then guarded `ALTER TABLE ... ADD COLUMN`) until a migration runner
is added.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from weakref import WeakKeyDictionary

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# the adapters that have created their tables, per engine (gone when the engine is)
_CREATED: WeakKeyDictionary[AsyncEngine, set[str]] = WeakKeyDictionary()


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


async def ensure_tables(engine: AsyncEngine, name: str, statements: Sequence[str]) -> None:
    """Run `statements` once per engine. `name` identifies the adapter that owns them."""
    done = _CREATED.setdefault(engine, set())
    if name in done:
        return
    async with engine.begin() as conn:
        for statement in statements:
            await conn.exec_driver_sql(statement)
    done.add(name)
