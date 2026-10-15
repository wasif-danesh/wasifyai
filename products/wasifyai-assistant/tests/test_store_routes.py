"""Conversation records, their search source and their read API."""

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from wasifyai_assistant.index import conversation_index_source
from wasifyai_assistant.routes import build_routes
from wasifyai_assistant.store import (
    InMemoryConversationStore,
    SqlConversationStore,
)
from wasifyai_platform_sdk import Identity, RouteDeps
from wasifyai_platform_sdk.sqlite import create_sqlite_engine


@pytest.fixture
async def engine(tmp_path):
    eng = create_sqlite_engine(tmp_path / "wasifyai.db")
    yield eng
    await eng.dispose()


async def check_store(store) -> None:
    a = await store.create("t1", "u1", "First")
    b = await store.create("t1", "u1", "")
    other = await store.create("t1", "u2", "Theirs")
    other_tenant = await store.create("t2", "u1", "Elsewhere")

    # ownership: another user or tenant sees nothing
    assert (await store.get("t1", "u1", a.id)).title == "First"
    assert await store.get("t1", "u2", a.id) is None
    assert await store.get("t2", "u1", a.id) is None
    assert await store.get("t1", "u1", "nope") is None

    # messages are numbered in order and bump the conversation
    m1 = await store.add_message("t1", "u1", a.id, "user", [{"type": "text", "text": "hi"}])
    m2 = await store.add_message(
        "t1",
        "u1",
        a.id,
        "assistant",
        [{"type": "tool_call", "id": "c", "name": "n", "arguments": {"q": 1}}],
    )
    assert (m1.seq, m2.seq) == (1, 2)
    got = await store.messages("t1", "u1", a.id)
    assert [m.role for m in got] == ["user", "assistant"]
    assert got[1].parts[0]["arguments"] == {"q": 1} and got[0].text() == "hi"
    assert await store.messages("t1", "u2", a.id) == []

    # newest activity first: `a` was touched after `b` was made
    order = [c.id for c in await store.recent("t1", "u1", 10)]
    assert order == [a.id, b.id]
    page = await store.recent("t1", "u1", 1)
    assert [c.id for c in page] == [a.id]
    older = await store.recent("t1", "u1", 10, before=page[0].updated_at)
    assert [c.id for c in older] == [b.id]

    # rename and delete are the owner's
    assert await store.rename("t1", "u2", a.id, "Hijacked") is False
    assert await store.rename("t1", "u1", a.id, "Renamed") is True
    assert (await store.get("t1", "u1", a.id)).title == "Renamed"
    assert await store.delete("t1", "u2", a.id) is False
    assert await store.delete("t1", "u1", a.id) is True
    assert (
        await store.get("t1", "u1", a.id) is None and await store.messages("t1", "u1", a.id) == []
    )
    assert await store.get("t1", "u2", other.id) is not None
    assert await store.get("t2", "u1", other_tenant.id) is not None


async def test_the_memory_store():
    await check_store(InMemoryConversationStore())


async def test_the_sql_store_on_the_desktop_database(engine):
    await check_store(SqlConversationStore(engine))


async def test_the_search_source_lists_conversations_with_what_the_person_wrote(engine):
    store = SqlConversationStore(engine)
    c = await store.create("t1", "u1", "Teapots")
    await store.add_message("t1", "u1", c.id, "user", [{"type": "text", "text": "a red teapot"}])
    await store.add_message(
        "t1", "u1", c.id, "assistant", [{"type": "text", "text": "secret answer"}]
    )
    source = conversation_index_source(engine)
    assert (source.product_id, source.kind) == ("wasifyai-assistant", "conversation")
    (item,) = await source.page(None, 10)
    assert (item.tenant_id, item.user_id, item.item_id) == ("t1", "u1", c.id)
    assert "Teapots" in item.text and "red teapot" in item.text and "secret" not in item.text
    assert await source.page(c.id, 10) == []
    assert await source.present([c.id, "gone"]) == {c.id}
    assert await source.present([]) == set()


def who(x_user: str = Header("u1")) -> Identity:
    return Identity(tenant_id="t1", user_id=x_user)


@pytest.fixture
def client():
    store = InMemoryConversationStore()
    unindexed: list[str] = []
    app = FastAPI()

    class State:
        engine = None
        storage = None

        async def noop(self) -> None: ...

    deps = RouteDeps(State(), who)

    async def unindex(identity, product_id, item_id):
        unindexed.append(item_id)

    deps.unindex = unindex  # type: ignore[method-assign]
    app.include_router(build_routes(deps, store), prefix="/products/wasifyai-assistant")
    c = TestClient(app)
    c.store = store  # type: ignore[attr-defined]
    c.unindexed = unindexed  # type: ignore[attr-defined]
    return c


BASE = "/products/wasifyai-assistant/conversations"


async def seed(client, user="u1", title="Hello"):
    conv = await client.store.create("t1", user, title)
    await client.store.add_message("t1", user, conv.id, "user", [{"type": "text", "text": "hi"}])
    return conv


async def test_the_list_and_one_conversation(client):
    mine = await seed(client)
    await seed(client, user="someone-else", title="Theirs")
    listing = client.get(BASE).json()
    assert [c["id"] for c in listing["conversations"]] == [mine.id]
    one = client.get(f"{BASE}/{mine.id}").json()
    assert one["title"] == "Hello" and one["messages"][0]["parts"][0]["text"] == "hi"
    assert client.get(f"{BASE}/{mine.id}", headers={"x-user": "someone-else"}).status_code == 404


async def test_rename_validates_and_is_the_owners(client):
    mine = await seed(client)
    ok = client.patch(f"{BASE}/{mine.id}", json={"title": "  New name "})
    assert ok.status_code == 200 and ok.json()["title"] == "New name"
    assert client.patch(f"{BASE}/{mine.id}", json={"title": ""}).status_code == 422
    assert client.patch(f"{BASE}/{mine.id}", json={"title": "x", "extra": 1}).status_code == 422
    other = client.patch(f"{BASE}/{mine.id}", json={"title": "x"}, headers={"x-user": "b"})
    assert other.status_code == 404


async def test_delete_removes_the_conversation_and_takes_it_out_of_search(client):
    mine = await seed(client)
    assert client.delete(f"{BASE}/{mine.id}", headers={"x-user": "b"}).status_code == 404
    assert client.delete(f"{BASE}/{mine.id}").status_code == 204
    assert client.unindexed == [mine.id]
    assert client.get(f"{BASE}/{mine.id}").status_code == 404
    assert client.delete(f"{BASE}/{mine.id}").status_code == 404
