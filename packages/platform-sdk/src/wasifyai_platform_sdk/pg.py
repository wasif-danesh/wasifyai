"""What a product needs to keep its own tables in the deployment's Postgres with SQL it also runs
on SQLite (the desktop's engine): a connection pool whose connections look at the product's own
schema first, and a small wrapper that lets code written with `?` parameters and `fetchone()` rows
run on it.

A product that does this keeps one store class: the SQL is shared and the few differences between
the databases are hooks. Examples: the notebooks (`wasifyai_notebooks.pgstore`) and the voice
product (`wasifyai_voice.pgstore`)."""

import re
from collections.abc import Sequence
from typing import Any

SCHEMA_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def translate(sql: str) -> str:
    """The shared SQL uses `?` for a parameter, psycopg wants `%s` (and `%` doubled)."""
    return sql.replace("%", "%%").replace("?", "%s")


def vector_text(vector: Sequence[float]) -> str:
    """A pgvector literal: `[0.1,0.2]`."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class PgDb:
    """What the store's SQL runs on: `execute(sql, params)` answering a cursor (iterable,
    `fetchone`, `fetchall`, `rowcount`), like the sqlite3 connection the shared code was for."""

    dialect = "postgres"

    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return self._conn.execute(translate(sql), tuple(params))  # pyright: ignore[reportArgumentType]

    def transaction(self) -> Any:
        """A savepoint inside the open transaction."""
        return self._conn.transaction()


def check_schema_name(schema: str) -> str:
    if not SCHEMA_NAME.match(schema):
        raise ValueError("the schema name must be lower-case letters, digits and underscores")
    return schema


def open_pool(dsn: str, schema: str, *, max_connections: int = 8, dict_rows: bool = False) -> Any:
    """A pool of connections that look at `schema` first. `dsn` is a libpq string or URL; the
    SQLAlchemy `+asyncpg` form is accepted. With `dict_rows` a row is a dict by column name."""
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    kwargs: dict[str, Any] = {"options": f"-c search_path={check_schema_name(schema)},public"}
    if dict_rows:
        kwargs["row_factory"] = dict_row
    return ConnectionPool(
        dsn.replace("+asyncpg", "").replace("+psycopg", ""),
        min_size=1,
        max_size=max_connections,
        kwargs=kwargs,
        open=True,
    )
