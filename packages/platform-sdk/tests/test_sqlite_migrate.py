"""The SQLite migration runner (stage J1 of the 2026-10-27 plan): a store's numbered migrations,
its version in `schema_versions`, a copy of the file before a store with data changes, one
transaction per run, and a file from before the runner brought up to date."""

import asyncio
from pathlib import Path

import pytest
from wasifyai_platform_sdk.sqlite import (
    Migration,
    SchemaTooNew,
    create_sqlite_engine,
    migrate,
)
from wasifyai_platform_sdk.sqlite.engine import BACKUPS_KEPT

NOTES_V1 = Migration(
    1,
    ("CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, body TEXT NOT NULL)",),
    columns={"notes": {"pinned": "INTEGER NOT NULL DEFAULT 0"}},
)
# a change the runner exists for: a rename, which additive DDL could not do
NOTES_V2 = Migration(2, ("ALTER TABLE notes RENAME COLUMN body TO text",))


async def rows(engine, sql: str) -> list[tuple]:
    async with engine.connect() as conn:
        return [tuple(r) for r in (await conn.exec_driver_sql(sql)).all()]


async def version(engine, store: str) -> int | None:
    got = await rows(engine, f"SELECT version FROM schema_versions WHERE store = '{store}'")
    return got[0][0] if got else None


async def columns(engine, table: str) -> list[str]:
    return [r[1] for r in await rows(engine, f"PRAGMA table_info({table})")]


async def test_a_new_file_gets_the_store_at_its_last_version_and_no_backup(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "app.db")
    await migrate(engine, "notes", [NOTES_V1, NOTES_V2])
    assert await version(engine, "notes") == 2
    assert await columns(engine, "notes") == ["id", "text", "pinned"]
    assert not (tmp_path / "backups").exists()
    await engine.dispose()


async def test_a_file_from_before_the_runner_is_brought_to_version_1_without_losing_rows(
    tmp_path: Path,
):
    """Last week's data folder: the table as the old helper made it, an older shape, no versions."""
    engine = create_sqlite_engine(tmp_path / "app.db")
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE notes (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        await conn.exec_driver_sql("INSERT INTO notes VALUES ('n1', 'buy milk')")
    await migrate(engine, "notes", [NOTES_V1])
    assert await version(engine, "notes") == 1
    assert await rows(engine, "SELECT id, body, pinned FROM notes") == [("n1", "buy milk", 0)]
    assert not (tmp_path / "backups").exists()  # migration 1 only adds what is missing
    await engine.dispose()


async def test_a_rename_keeps_the_data_and_a_copy_of_the_file_is_kept_first(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "app.db")
    await migrate(engine, "notes", [NOTES_V1])
    async with engine.begin() as conn:
        await conn.exec_driver_sql("INSERT INTO notes (id, body) VALUES ('n1', 'buy milk')")
    await engine.dispose()

    engine = create_sqlite_engine(tmp_path / "app.db")  # the next release of the app
    await migrate(engine, "notes", [NOTES_V1, NOTES_V2])
    assert await version(engine, "notes") == 2
    assert await rows(engine, "SELECT id, text FROM notes") == [("n1", "buy milk")]
    copies = list((tmp_path / "backups").glob("app-*-notes-v1.db"))
    assert len(copies) == 1
    old = create_sqlite_engine(copies[0])
    assert await rows(old, "SELECT body FROM notes") == [("buy milk",)]  # the shape before
    await old.dispose()
    await engine.dispose()


async def test_a_migration_that_fails_changes_nothing(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "app.db")
    await migrate(engine, "notes", [NOTES_V1])
    await engine.dispose()

    broken = Migration(
        2,
        (
            "ALTER TABLE notes RENAME COLUMN body TO text",
            "CREATE TABLE tags (id TEXT PRIMARY KEY)",
            "THIS IS NOT SQL",
        ),
    )
    engine = create_sqlite_engine(tmp_path / "app.db")
    with pytest.raises(Exception, match="syntax error"):
        await migrate(engine, "notes", [NOTES_V1, broken])
    assert await version(engine, "notes") == 1
    assert await columns(engine, "notes") == ["id", "body", "pinned"]
    assert await rows(engine, "SELECT name FROM sqlite_master WHERE name = 'tags'") == []
    await engine.dispose()


async def test_a_file_from_a_newer_app_is_refused_in_words(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "app.db")
    await migrate(engine, "notes", [NOTES_V1, NOTES_V2])
    await engine.dispose()
    engine = create_sqlite_engine(tmp_path / "app.db")
    with pytest.raises(SchemaTooNew, match="newer version of Wasify AI"):
        await migrate(engine, "notes", [NOTES_V1])
    await engine.dispose()


async def test_two_processes_opening_one_file_run_each_migration_once(tmp_path: Path):
    ran: list[int] = []

    async def count(conn) -> None:
        ran.append(1)
        await asyncio.sleep(0.05)  # hold the write lock a moment

    once = [Migration(1, ("CREATE TABLE IF NOT EXISTS t (id INTEGER)",), run=count)]
    a, b = create_sqlite_engine(tmp_path / "app.db"), create_sqlite_engine(tmp_path / "app.db")
    await asyncio.gather(migrate(a, "t", once), migrate(b, "t", once))
    assert ran == [1]
    await a.dispose()
    await b.dispose()


async def test_stores_on_one_file_keep_their_own_versions(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "app.db")
    await migrate(engine, "notes", [NOTES_V1, NOTES_V2])
    await migrate(engine, "other", [Migration(1, ("CREATE TABLE IF NOT EXISTS o (id TEXT)",))])
    assert (await version(engine, "notes"), await version(engine, "other")) == (2, 1)
    await engine.dispose()


async def test_only_the_newest_copies_are_kept(tmp_path: Path):
    steps = [Migration(1, ("CREATE TABLE IF NOT EXISTS t (id INTEGER)",))]
    for n in range(2, BACKUPS_KEPT + 4):
        steps.append(Migration(n, (f"ALTER TABLE t ADD COLUMN c{n} TEXT",)))
        engine = create_sqlite_engine(tmp_path / "app.db")
        await migrate(engine, "t", steps)
        await engine.dispose()
    copies = sorted((tmp_path / "backups").glob("app-*.db"))
    assert len(copies) == BACKUPS_KEPT
    assert copies[-1].name.endswith(f"-t-v{BACKUPS_KEPT + 2}.db")


@pytest.mark.parametrize("numbers", [[2], [1, 3], [1, 1]])
async def test_migrations_must_be_numbered_from_one_in_order(tmp_path: Path, numbers):
    engine = create_sqlite_engine(tmp_path / "app.db")
    with pytest.raises(ValueError, match="numbered"):
        await migrate(engine, "t", [Migration(n) for n in numbers])
    await engine.dispose()


async def test_a_cancel_while_waiting_for_the_lock_comes_out_as_a_cancel(tmp_path: Path):
    """A task stopped while its migration waits for another writer must end as cancelled: a
    rollback error in its place kept a retrying loop (the desktop's completion consumer) alive,
    and the engine never stopped."""
    holder = create_sqlite_engine(tmp_path / "app.db")
    waiter = create_sqlite_engine(tmp_path / "app.db")
    async with holder.connect() as conn:
        await conn.exec_driver_sql("BEGIN IMMEDIATE")  # another writer holds the file
        task = asyncio.create_task(migrate(waiter, "notes", [NOTES_V1]))
        await asyncio.sleep(0.3)  # it is waiting for the lock now
        task.cancel()
        await conn.exec_driver_sql("COMMIT")
    with pytest.raises(asyncio.CancelledError):
        await task
    await migrate(waiter, "notes", [NOTES_V1])  # and the next start does it
    assert await version(waiter, "notes") == 1
    await holder.dispose()
    await waiter.dispose()
