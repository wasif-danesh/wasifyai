"""The assistant's conversation store on real Postgres: asyncpg cannot guess the type of a parameter
that is only tested for NULL, which made Recents answer 500 on the web (2026-10-21). SQLite never
complained."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from wasifyai_assistant.index import ConversationIndexSource
from wasifyai_assistant.store import SqlConversationStore


@pytest.fixture
async def store(engine):
    s = SqlConversationStore(engine)
    tenant = "it-" + uuid4().hex
    try:
        await s.create(tenant, "u1", "first")
    except Exception:
        pytest.skip("the conversations table is not there (make migrate)")
    yield s, tenant
    async with engine.begin() as c:
        await c.execute(text("DELETE FROM conversations WHERE tenant_id = :t"), {"t": tenant})


async def test_recent_lists_the_first_page_and_pages_back(store):
    s, tenant = store
    second = await s.create(tenant, "u1", "second")
    first_page = await s.recent(tenant, "u1", 10)  # no `before`: the case that failed
    assert {c.title for c in first_page} == {"first", "second"}
    older = await s.recent(tenant, "u1", 10, before=second.updated_at)
    assert all(c.updated_at < second.updated_at for c in older)


async def test_the_search_source_pages_from_the_start(store, engine):
    _, tenant = store
    items = await ConversationIndexSource(engine).page(None, 50)
    assert any(i.tenant_id == tenant for i in items)
