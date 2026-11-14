import contextlib
import os
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from wasifyai_code.store import CodeStore, Owner


def pg_dsn() -> str:
    """The Postgres the store tests run against: `DATABASE_URL` (as CI and `make dev` set it) or the
    compose stack's default. The test skips when nothing answers there."""
    url = os.environ.get("DATABASE_URL", "postgresql://wasifyai:wasifyai@localhost:5432/wasifyai")
    dsn = url.replace("+asyncpg", "").replace("+psycopg", "")
    u = urlparse(dsn)
    try:
        socket.create_connection((u.hostname or "localhost", u.port or 5432), timeout=1).close()
    except OSError:
        pytest.skip("Postgres not reachable")
    return dsn


@pytest.fixture
def me() -> Owner:
    return Owner("t1", "u1")


@pytest.fixture
def store(tmp_path: Path):
    """A store on a real SQLite file."""
    s = CodeStore.in_folder(tmp_path / "data")
    yield s
    s.close()


@pytest.fixture(params=["sqlite", "postgres"])
def any_store(request, tmp_path: Path):
    """A store on SQLite, then on Postgres: the same tests run against both. Each Postgres test
    has a schema of its own, dropped at the end."""
    if request.param == "sqlite":
        s = CodeStore.in_folder(tmp_path / "data")
        yield s
        s.close()
        return
    s = CodeStore.on_postgres(pg_dsn(), schema=f"codet_{uuid.uuid4().hex[:10]}")
    yield s
    s.drop_schema()
    s.close()


@pytest.fixture(params=["sqlite", "postgres"])
def two_stores(request, tmp_path: Path):
    """Two openings of one store, as two windows (or two servers) have: on a SQLite file, then on
    Postgres."""
    if request.param == "sqlite":
        first = CodeStore.in_folder(tmp_path / "data")
        second = CodeStore.on_file(tmp_path / "data" / "code.db")
        yield first, second
    else:
        schema = f"codet_{uuid.uuid4().hex[:10]}"
        first = CodeStore.on_postgres(pg_dsn(), schema=schema)
        second = CodeStore.on_postgres(pg_dsn(), schema=schema)
        yield first, second
        first.drop_schema()
    for s in (first, second):
        with contextlib.suppress(Exception):
            s.close()
