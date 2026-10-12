"""The Postgres user store follows the same rules as the in-memory one (needs `make migrate`)."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from wasifyai_api.users import PostgresUserStore

from tests.user_store_contract import NO_ADMINS, check_contract, claims


@pytest.fixture
async def store(engine):
    try:
        async with engine.connect() as c:
            await c.execute(text("select 1 from users limit 1"))
    except Exception:
        pytest.skip("users table missing (make migrate)")
    return PostgresUserStore(engine)


async def test_postgres_store_follows_the_rules(store):
    await check_contract(store, "it-" + uuid4().hex)


async def test_simultaneous_first_sign_ins_make_one_user(store):
    tenant = "it-" + uuid4().hex
    users = await asyncio.gather(*(store.resolve(tenant, claims(), NO_ADMINS) for _ in range(8)))
    assert len({u.id for u in users}) == 1
