"""The desktop profile's stores follow the same contracts as the Postgres and in-memory ones."""

import asyncio
from uuid import uuid4

import pytest
from wasifyai_api.creation_index import InMemoryIndexStore
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_api.sqlite_stores import SqliteIndexStore, SqliteSettingsStore, SqliteUserStore
from wasifyai_platform_sdk.sqlite import create_sqlite_engine

from tests.index_store_contract import check_contract as check_index_contract
from tests.user_store_contract import NO_ADMINS, claims
from tests.user_store_contract import check_contract as check_user_contract


@pytest.fixture
async def engine(tmp_path):
    eng = create_sqlite_engine(tmp_path / "wasifyai.db")
    yield eng
    await eng.dispose()


def tenant() -> str:
    return "ct-" + uuid4().hex


async def test_user_store_follows_the_rules(engine):
    await check_user_contract(SqliteUserStore(engine), tenant())


async def test_simultaneous_first_sign_ins_make_one_user(engine):
    store, t = SqliteUserStore(engine), tenant()
    users = await asyncio.gather(*(store.resolve(t, claims(), NO_ADMINS) for _ in range(8)))
    assert len({u.id for u in users}) == 1


async def test_a_user_is_the_same_user_after_a_restart(tmp_path):
    t = tenant()
    first = create_sqlite_engine(tmp_path / "wasifyai.db")
    one = await SqliteUserStore(first).resolve(t, claims("desktop", "local"), NO_ADMINS)
    await first.dispose()
    second = create_sqlite_engine(tmp_path / "wasifyai.db")
    two = await SqliteUserStore(second).resolve(t, claims("desktop", "local"), NO_ADMINS)
    await second.dispose()
    assert one.id == two.id


async def test_settings_round_trip_and_survive_a_restart(tmp_path):
    first = create_sqlite_engine(tmp_path / "wasifyai.db")
    store = SqliteSettingsStore(first)
    assert await store.get("safeguards.enabled") is None
    await store.put("safeguards.enabled", True, "me")
    await store.put("other", {"a": [1, 2]}, "me")
    await store.put("safeguards.enabled", False, "me")  # replaces
    await first.dispose()
    second = create_sqlite_engine(tmp_path / "wasifyai.db")
    again = SqliteSettingsStore(second)
    assert await again.get("safeguards.enabled") is False
    assert await again.get("other") == {"a": [1, 2]}
    await second.dispose()


async def test_settings_memory_store_agrees():
    store = InMemorySettingsStore()
    await store.put("k", {"a": 1}, "me")
    assert await store.get("k") == {"a": 1}


async def test_index_store_memory():
    await check_index_contract(InMemoryIndexStore(), tenant())


async def test_index_store_sqlite(engine):
    await check_index_contract(SqliteIndexStore(engine), tenant())
