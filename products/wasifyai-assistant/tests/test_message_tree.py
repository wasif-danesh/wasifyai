"""The messages of a conversation as a tree (ADR-0082, stage CU2).

Edit and regenerate make branches, the model only sees the branch on screen, and old
conversations are chains."""

import pytest
from assistant_rig import FakeHost, Rig
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import text
from wasifyai_assistant.routes import build_routes
from wasifyai_assistant.store import (
    HEAD,
    InMemoryConversationStore,
    SqlConversationStore,
    leaf_in,
    path_in,
)
from wasifyai_platform_sdk import Identity, RouteDeps
from wasifyai_platform_sdk.sqlite import create_sqlite_engine


@pytest.fixture
async def engine(tmp_path):
    eng = create_sqlite_engine(tmp_path / "wasifyai.db")
    yield eng
    await eng.dispose()


def part(t: str) -> list[dict]:
    return [{"type": "text", "text": t}]


async def check_tree(store) -> None:
    c = await store.create("t1", "u1", "Tree")
    cid = c.id
    u1 = await store.add_message("t1", "u1", cid, "user", part("one"))
    a1 = await store.add_message("t1", "u1", cid, "assistant", part("A1"))  # under the head: u1
    assert (u1.parent_id, a1.parent_id) == (None, u1.id)
    assert await store.head("t1", "u1", cid) == a1.id

    # a second question, then an edit of it: the edit is a sibling, under the same parent
    u2 = await store.add_message("t1", "u1", cid, "user", part("two"))
    a2 = await store.add_message("t1", "u1", cid, "assistant", part("A2"))
    u2b = await store.add_message("t1", "u1", cid, "user", part("two, edited"), parent_id=a1.id)
    a2b = await store.add_message("t1", "u1", cid, "assistant", part("A2b"))
    assert u2b.parent_id == a1.id and a2b.parent_id == u2b.id
    assert [m.id for m in await store.path("t1", "u1", cid)] == [u1.id, a1.id, u2b.id, a2b.id]
    assert [m.id for m in await store.path("t1", "u1", cid, a2.id)] == [u1.id, a1.id, u2.id, a2.id]
    assert len(await store.messages("t1", "u1", cid)) == 6  # nothing was lost

    # showing the other branch is the person's choice and is remembered
    assert await store.set_head("t1", "u1", cid, a2.id) is True
    assert await store.head("t1", "u1", cid) == a2.id
    assert await store.set_head("t1", "u1", cid, "nope") is False
    assert await store.set_head("t1", "u2", cid, a2.id) is False  # not theirs

    # a new message continues the branch on screen
    u3 = await store.add_message("t1", "u1", cid, "user", part("three"))
    assert u3.parent_id == a2.id

    # a first message can have a sibling too (an edit of the very first message)
    root2 = await store.add_message("t1", "u1", cid, "user", part("uno"), parent_id=None)
    assert root2.parent_id is None
    assert [m.id for m in await store.path("t1", "u1", cid)] == [root2.id]

    # a parent that is not in this conversation is the head, never another conversation's row
    other = await store.create("t1", "u1", "Other")
    foreign = await store.add_message("t1", "u1", other.id, "user", part("x"))
    stray = await store.add_message("t1", "u1", cid, "user", part("y"), parent_id=foreign.id)
    assert stray.parent_id == root2.id

    # the leaf of a turn: an assistant row leads down through tool rows to the answer
    t_u = await store.add_message("t1", "u1", other.id, "user", part("draw"), parent_id=None)
    t_a = await store.add_message("t1", "u1", other.id, "assistant", [{"type": "tool_call"}])
    t_r = await store.add_message("t1", "u1", other.id, "tool", [{"type": "tool_result"}])
    t_z = await store.add_message("t1", "u1", other.id, "assistant", part("done"))
    assert await store.leaf_of("t1", "u1", other.id, t_a.id) == t_z.id
    assert await store.leaf_of("t1", "u1", other.id, t_u.id) == t_u.id  # a user row is its own
    assert await store.leaf_of("t1", "u1", other.id, "nope") is None
    assert t_r.parent_id == t_a.id and t_z.parent_id == t_r.id


async def test_the_memory_store_keeps_a_tree():
    await check_tree(InMemoryConversationStore())


async def test_the_sql_store_keeps_a_tree(engine):
    await check_tree(SqlConversationStore(engine))


def test_the_pure_helpers_cope_with_loops_and_old_chains():
    from wasifyai_assistant.store import Message

    a = Message("a", "c", 1, "user", [], "", None)
    b = Message("b", "c", 2, "assistant", [], "", "a")
    assert [m.id for m in path_in([a, b], None)] == ["a", "b"]  # no head: the last row
    loop = [
        Message("x", "c", 1, "user", [], "", "y"),
        Message("y", "c", 2, "assistant", [], "", "x"),
    ]
    assert len(path_in(loop, "y")) == 2  # a loop ends instead of hanging
    assert leaf_in(loop, "y") == "y"
    assert path_in([], None) == []
    assert HEAD not in {"a", "b"}


async def test_a_database_made_before_the_tree_becomes_a_chain_with_its_head_at_the_end(engine):
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE conversations (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, "
            "product_id TEXT NOT NULL, user_id TEXT NOT NULL, title TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        await conn.exec_driver_sql(
            "CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, "
            "tenant_id TEXT NOT NULL, product_id TEXT NOT NULL, user_id TEXT NOT NULL, "
            "seq INTEGER NOT NULL, role TEXT NOT NULL, parts TEXT NOT NULL, "
            "created_at TEXT NOT NULL)"
        )
        await conn.execute(
            text(
                "INSERT INTO conversations VALUES "
                "('c1','t1','wasifyai-assistant','u1','Old','a','b')"
            )
        )
        for i, role in enumerate(["user", "assistant", "user", "assistant"], 1):
            await conn.execute(
                text(
                    "INSERT INTO messages VALUES (:id,'c1','t1','wasifyai-assistant','u1',:s,:r,"
                    '\'[{"type":"text","text":"x"}]\',\'a\')'
                ),
                {"id": f"m{i}", "s": i, "r": role},
            )
    store = SqlConversationStore(engine)
    msgs = await store.messages("t1", "u1", "c1")
    assert [m.parent_id for m in msgs] == [None, "m1", "m2", "m3"]
    assert await store.head("t1", "u1", "c1") == "m4"
    assert [m.id for m in await store.path("t1", "u1", "c1")] == ["m1", "m2", "m3", "m4"]
    again = SqlConversationStore(engine)  # opening it a second time changes nothing
    assert [m.parent_id for m in await again.messages("t1", "u1", "c1")] == [None, "m1", "m2", "m3"]
    new = await again.add_message("t1", "u1", "c1", "user", part("more"))
    assert new.parent_id == "m4"


# ---- the graph ------------------------------------------------------------------------------


async def test_an_edit_is_a_sibling_and_the_model_sees_only_its_own_branch(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "A1"}, {"text": "A2"}, {"text": "A2 edited"}])
    first, _ = await rig.turn("one")
    cid = first["conversation_id"]
    second, _ = await rig.turn("two", cid)
    u2 = second["user_message_id"]
    rows = {m.id: m for m in await rig.store.messages("t1", "u1", cid)}
    a1_id = rows[u2].parent_id
    assert a1_id == first["assistant_message_id"]

    edited, _ = await rig.turn_with(
        {"text": "two, better", "conversation_id": cid, "parent_message_id": a1_id}
    )
    new = {m.id: m for m in await rig.store.messages("t1", "u1", cid)}
    assert new[edited["user_message_id"]].parent_id == a1_id
    assert new[edited["assistant_message_id"]].parent_id == edited["user_message_id"]
    sent = rig.model.chats[2]["messages"]
    assert [m["content"] for m in sent[1:]] == ["one", "A1", "two, better"]  # not "two"/"A2"
    assert len(new) == 6  # the old branch is still there
    assert [m.text() for m in await rig.store.path("t1", "u1", cid)] == [
        "one", "A1", "two, better", "A2 edited"
    ]  # fmt: skip


async def test_the_first_message_can_be_edited_with_an_empty_parent(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "A1"}, {"text": "B1"}])
    first, _ = await rig.turn("one")
    cid = first["conversation_id"]
    second, _ = await rig.turn_with(
        {"text": "uno", "conversation_id": cid, "parent_message_id": ""}
    )
    rows = {m.id: m for m in await rig.store.messages("t1", "u1", cid)}
    assert rows[second["user_message_id"]].parent_id is None
    assert [m["content"] for m in rig.model.chats[1]["messages"][1:]] == ["uno"]


async def test_regenerate_answers_the_same_message_again_as_a_sibling(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "first try"}, {"text": "second try"}])
    first, _ = await rig.turn("explain")
    cid, uid = first["conversation_id"], first["user_message_id"]
    again, events = await rig.turn_with(
        {"conversation_id": cid, "parent_message_id": uid, "regenerate": True}
    )
    assert again["status"] == "done" and again["reply"] == "second try"
    assert again["user_message_id"] == uid  # no new question was stored
    rows = await rig.store.messages("t1", "u1", cid)
    assert [(m.role, m.parent_id) for m in rows] == [
        ("user", None), ("assistant", uid), ("assistant", uid)
    ]  # fmt: skip
    assert [m["content"] for m in rig.model.chats[1]["messages"][1:]] == ["explain"]
    assert again["title"] == "explain"


async def test_regenerate_needs_a_question_to_answer(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "x"}])
    first, _ = await rig.turn("hello")
    cid = first["conversation_id"]
    bad, _ = await rig.turn_with(
        {
            "conversation_id": cid,
            "parent_message_id": first["assistant_message_id"],
            "regenerate": True,
        }
    )
    assert bad["status"] == "refused" and bad["refusal"]["code"] == "invalid_request"
    gone, _ = await rig.turn_with(
        {"conversation_id": cid, "parent_message_id": "nope", "regenerate": True}
    )
    assert gone["refusal"]["code"] == "not_found"
    nothing, _ = await rig.turn_with({"text": "", "conversation_id": cid})
    assert nothing["refusal"]["code"] == "invalid_request"  # an empty message is still refused


async def test_continuing_from_an_answer_that_used_a_tool_goes_under_its_last_row(tmp_path, ctx):
    host = FakeHost()
    rig = Rig(
        tmp_path,
        [
            {
                "text": "Looking.",
                "tool_calls": [{"name": "search_creations", "arguments": {"query": "fox"}}],
            },
            {"text": "Found none."},
            {"text": "Next."},
        ],
        host,
    )  # fmt: skip
    first, _ = await rig.turn("find a fox")
    cid = first["conversation_id"]
    rows = await rig.store.messages("t1", "u1", cid)
    assert [m.role for m in rows] == ["user", "assistant", "tool", "assistant"]
    assert [m.parent_id for m in rows] == [None, rows[0].id, rows[1].id, rows[2].id]
    # the client names the turn by its first assistant row; the engine goes to the end of it
    second, _ = await rig.turn_with(
        {
            "text": "thanks",
            "conversation_id": cid,
            "parent_message_id": first["assistant_message_id"],
        }
    )
    new = {m.id: m for m in await rig.store.messages("t1", "u1", cid)}
    assert new[second["user_message_id"]].parent_id == rows[3].id


# ---- the routes -----------------------------------------------------------------------------


def who(x_user: str = Header("u1")) -> Identity:
    return Identity(tenant_id="t1", user_id=x_user)


@pytest.fixture
def client():
    store = InMemoryConversationStore()
    app = FastAPI()

    class State:
        engine = None
        storage = None

    deps = RouteDeps(State(), who)
    app.include_router(build_routes(deps, store), prefix="/products/wasifyai-assistant")
    c = TestClient(app)
    c.store = store  # type: ignore[attr-defined]
    return c


BASE = "/products/wasifyai-assistant/conversations"


async def test_a_conversation_reads_as_the_branch_on_screen_or_as_the_whole_tree(client):
    s = client.store
    c = await s.create("t1", "u1", "Tree")
    u1 = await s.add_message("t1", "u1", c.id, "user", part("one"))
    a1 = await s.add_message("t1", "u1", c.id, "assistant", part("A1"))
    u2 = await s.add_message("t1", "u1", c.id, "user", part("two"))
    u2b = await s.add_message("t1", "u1", c.id, "user", part("two b"), parent_id=a1.id)

    one = client.get(f"{BASE}/{c.id}").json()
    assert one["head_id"] == u2b.id
    assert [m["id"] for m in one["messages"]] == [u1.id, a1.id, u2b.id]
    assert one["messages"][2]["parent_id"] == a1.id
    full = client.get(f"{BASE}/{c.id}?tree=1").json()
    assert [m["id"] for m in full["messages"]] == [u1.id, a1.id, u2.id, u2b.id]

    shown = client.patch(f"{BASE}/{c.id}", json={"head_id": u2.id})
    assert shown.status_code == 200
    assert client.get(f"{BASE}/{c.id}").json()["head_id"] == u2.id
    assert client.patch(f"{BASE}/{c.id}", json={"head_id": "nope"}).status_code == 404
    assert client.patch(f"{BASE}/{c.id}", json={}).status_code == 422
    assert (
        client.patch(
            f"{BASE}/{c.id}", json={"head_id": u2.id}, headers={"x-user": "u2"}
        ).status_code
        == 404
    )
    renamed = client.patch(f"{BASE}/{c.id}", json={"title": "New", "head_id": u1.id}).json()
    assert renamed["title"] == "New"
    assert client.get(f"{BASE}/{c.id}").json()["head_id"] == u1.id
    assert client.patch(f"{BASE}/{c.id}", json={"title": "x", "bogus": 1}).status_code == 422
