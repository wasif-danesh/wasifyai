"""One store, two databases (stage J2): the same calls, the same SQL and the same answers on a
SQLite file and on a Postgres schema. The Postgres half skips where nothing answers (as the product
store tests do)."""

import os
import socket
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from wasifyai_platform_sdk.sqlstore import PostgresStoreDb, SqliteStoreDb, ddl_for

DDL = """
CREATE TABLE IF NOT EXISTS notes(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, body TEXT NOT NULL,
  size BIGINT NOT NULL DEFAULT 0, score DOUBLE PRECISION, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS notes_owner ON notes(tenant_id, created_at);
"""
LATER = (("notes", "pinned", "INTEGER NOT NULL DEFAULT 0"),)


def pg_dsn() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://wasifyai:wasifyai@localhost:5432/wasifyai")
    dsn = url.replace("+asyncpg", "").replace("+psycopg", "")
    u = urlparse(dsn)
    try:
        socket.create_connection((u.hostname or "localhost", u.port or 5432), timeout=1).close()
    except OSError:
        pytest.skip("Postgres not reachable")
    return dsn


@pytest.fixture(params=["sqlite", "postgres"])
def make(request, tmp_path: Path):
    """A database of each kind; a second call opens the same one again (a restart, a replica)."""
    made: list = []
    schema = f"sqlstore_t_{uuid.uuid4().hex[:8]}"

    def open_db(**kw):
        if request.param == "sqlite":
            db = SqliteStoreDb(tmp_path / "app.db", **kw)
        else:
            db = PostgresStoreDb(pg_dsn(), schema)
        made.append(db)
        return db

    yield open_db
    if request.param == "postgres" and made:
        made[0].drop()
    for db in made:
        db.close()


def test_the_same_sql_gives_the_same_answers(make):
    db = make()
    db.open_tables(DDL)
    big = 5_000_000_000  # past what a 32-bit number holds: BIGINT on both
    assert db.exec(
        "INSERT INTO notes(id, tenant_id, body, size, score, created_at) VALUES (?,?,?,?,?,?)",
        ("n1", "t1", "50% off?", big, 0.25, "2026-10-29T10:00:00"),
    ) == 1  # fmt: skip
    db.exec(
        "INSERT INTO notes(id, tenant_id, body, created_at) VALUES (?,?,?,?) "
        "ON CONFLICT (id) DO UPDATE SET body = excluded.body",
        ("n1", "t1", "changed", "x"),
    )
    row = db.one("SELECT * FROM notes WHERE id = ?", ("n1",))
    assert (row["body"], row["size"], row["score"]) == ("changed", big, 0.25)
    assert [r["id"] for r in db.all("SELECT id FROM notes WHERE tenant_id = ?", ("t1",))] == ["n1"]
    got = db.one("DELETE FROM notes WHERE id = ? RETURNING id", ("n1",))
    assert got["id"] == "n1" and db.all("SELECT id FROM notes") == []


def test_tables_grow_the_columns_a_later_version_added(make):
    first = make()
    first.open_tables(DDL)
    first.exec("INSERT INTO notes(id, tenant_id, body, created_at) VALUES ('a', 't', 'x', 'y')")
    again = make()  # the next version of the app opens the same database
    again.open_tables(DDL, LATER)
    again.open_tables(DDL, LATER)  # and opening it once more changes nothing
    assert again.one("SELECT pinned FROM notes WHERE id = 'a'")["pinned"] == 0


def test_a_transaction_stands_or_falls_whole(make):
    db = make()
    db.open_tables(DDL)
    with pytest.raises(RuntimeError), db.transaction() as t:
        t.execute("INSERT INTO notes(id, tenant_id, body, created_at) VALUES ('a', 't', 'x', 'y')")
        raise RuntimeError("half-way")
    assert db.all("SELECT id FROM notes") == []
    with db.transaction() as t:
        for i in range(3):
            t.execute(
                "INSERT INTO notes(id, tenant_id, body, created_at) VALUES (?, 't', 'x', 'y')",
                (f"n{i}",),
            )
    assert len(db.all("SELECT id FROM notes")) == 3


def test_replicas_starting_together_make_the_tables_once(make):
    dbs = [make() for _ in range(4)]
    errors: list[BaseException] = []

    def start(db) -> None:
        try:
            db.open_tables(DDL, LATER)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=start, args=(db,)) for db in dbs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_a_connection_per_call_reads_by_position_and_runs_its_preparation(tmp_path: Path):
    prepared: list[int] = []
    db = SqliteStoreDb(
        tmp_path / "app.db", rows="tuple", shared=False, on_open=lambda c: prepared.append(1)
    )
    db.open_tables(DDL)
    db.exec("INSERT INTO notes(id, tenant_id, body, created_at) VALUES ('a', 't', 'x', 'y')")
    assert db.one("SELECT id, body FROM notes") == ("a", "x")
    assert len(prepared) == 3  # each block had a connection of its own


def test_a_counting_key_is_written_the_way_each_database_has_it():
    ddl = "CREATE TABLE v(id INTEGER PRIMARY KEY AUTOINCREMENT, x TEXT)"
    assert ddl_for(ddl, "sqlite") == ddl
    assert ddl_for(ddl, "postgres") == "CREATE TABLE v(id BIGSERIAL PRIMARY KEY, x TEXT)"
