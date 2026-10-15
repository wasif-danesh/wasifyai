"""Desktop-profile adapters (ADR-0056): the interfaces the web profile serves from Postgres and
Redis, served from one SQLite file. Product code never imports this package: the API chooses these
adapters from the engine's dialect and the deployment profile."""

from wasifyai_platform_sdk.sqlite.engine import (
    create_sqlite_engine,
    ensure_columns,
    ensure_tables,
    from_iso,
    is_sqlite,
    now_iso,
    to_iso,
)
from wasifyai_platform_sdk.sqlite.eventlog import SqliteEventLog
from wasifyai_platform_sdk.sqlite.jobqueue import DoneMessage, QueuedJob, SqliteJobQueue
from wasifyai_platform_sdk.sqlite.runstore import SqliteRunStore
from wasifyai_platform_sdk.sqlite.uploads import SqliteUploadStore
from wasifyai_platform_sdk.sqlite.usage import SqliteUsageRecorder

__all__ = [
    "DoneMessage",
    "QueuedJob",
    "SqliteEventLog",
    "SqliteJobQueue",
    "SqliteRunStore",
    "SqliteUploadStore",
    "SqliteUsageRecorder",
    "create_sqlite_engine",
    "ensure_columns",
    "ensure_tables",
    "from_iso",
    "is_sqlite",
    "now_iso",
    "to_iso",
]
