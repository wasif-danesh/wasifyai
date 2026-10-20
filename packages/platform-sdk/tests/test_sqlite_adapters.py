"""The desktop profile's adapters follow the same contracts as the in-memory and Redis ones."""

import os
import socket
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from adapter_contracts import check_event_log, check_job_queue, check_run_store
from wasifyai_platform_sdk import InMemoryEventLog, RedisEventLog
from wasifyai_platform_sdk.runstore import InMemoryRunStore, RedisRunStore
from wasifyai_platform_sdk.sqlite import (
    SqliteEventLog,
    SqliteJobQueue,
    SqliteRunStore,
    create_sqlite_engine,
)


@pytest.fixture
async def engine(tmp_path):
    eng = create_sqlite_engine(tmp_path / "wasifyai.db")
    yield eng
    await eng.dispose()


@pytest.fixture
async def redis():
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    u = urlparse(url)
    try:
        socket.create_connection((u.hostname or "localhost", u.port or 6379), timeout=1).close()
    except OSError:
        pytest.skip("Redis not reachable")
    from redis.asyncio import Redis

    conn = Redis.from_url(url, decode_responses=True)
    yield conn
    await conn.aclose()


def tenant() -> str:
    return "ct-" + uuid4().hex


# ---- event log ----------------------------------------------------------------------------


async def test_event_log_memory():
    await check_event_log(InMemoryEventLog(), tenant())


async def test_event_log_sqlite(engine):
    await check_event_log(SqliteEventLog(engine), tenant())


async def test_event_log_redis(redis):
    await check_event_log(RedisEventLog(redis), tenant())


async def test_event_log_survives_a_restart(tmp_path):
    t = tenant()
    first = create_sqlite_engine(tmp_path / "wasifyai.db")
    await SqliteEventLog(first).append(t, "run-1", {"event": "node", "label": "kept"})
    await first.dispose()
    second = create_sqlite_engine(tmp_path / "wasifyai.db")
    log = SqliteEventLog(second)
    assert (await log.read(t, "run-1", 0, 50))[0]["label"] == "kept"
    assert await log.append(t, "run-1", {"event": "node"}) == 2  # seq continues, never restarts
    await second.dispose()


# ---- run store ----------------------------------------------------------------------------


async def test_run_store_memory():
    await check_run_store(InMemoryRunStore(), tenant())


async def test_run_store_sqlite(engine):
    await check_run_store(SqliteRunStore(engine), tenant())


async def test_run_store_redis(redis):
    await check_run_store(RedisRunStore(redis), tenant())


# ---- job queue (the Redis streams are exercised by the integration pipeline test) --------


async def test_job_queue_sqlite(engine):
    log = SqliteEventLog(engine)
    await check_job_queue(SqliteJobQueue(engine, log), log, tenant())


async def test_run_store_redis_claims_a_run_id_once_without_a_server():
    """The Redis store's claim of a run id (HSETNX), run against a stand-in for the parts it
    uses, so the path is checked where no Redis is reachable (`test_run_store_redis` runs the
    whole contract)."""
    from wasifyai_platform_sdk import RunRecord

    class Stand:
        def __init__(self):
            self.h: dict[str, dict[str, str]] = {}
            self.ttl: dict[str, int] = {}

        def register_script(self, _src):
            return None

        async def hsetnx(self, key, field, value):
            row = self.h.setdefault(key, {})
            if field in row:
                return 0
            row[field] = value
            return 1

        async def expire(self, key, seconds):
            self.ttl[key] = seconds

        async def hset(self, key, mapping):
            self.h.setdefault(key, {}).update(mapping)

    stand = Stand()
    store = RedisRunStore(stand)  # type: ignore[arg-type]
    rec = RunRecord(run_id="r1", thread_id="t1", product_id="p", tenant_id="x", user_id="u1")
    assert await store.create(rec) is True
    assert stand.ttl, "a run record must expire"
    mine = dict(next(iter(stand.h.values())))
    other = rec.model_copy(update={"thread_id": "t2", "user_id": "u2"})
    assert await store.create(other) is False
    assert next(iter(stand.h.values())) == mine  # the first run is untouched
