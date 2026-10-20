"""Conversations and their messages (ADR-0057 decision 3).

Ids are text and times are UTC ISO strings in both databases, so one implementation serves the
web profile (Postgres, migration 0018) and the desktop profile (SQLite, created on first use).
Every query is scoped by tenant, product and user (rules 7 to 9). A message's `parts` is JSON:

    {"type": "text", "text": "..."}
    {"type": "tool_call", "id": "...", "name": "...", "arguments": {...}}
    {"type": "tool_result", "id": "...", "name": "...", "status": "ok", "output": {...},
     "text": "..."}

The messages of a conversation form a tree (ADR-0082, stage CU2): every row has a `parent_id`
(None for a first message) and the conversation has a `head_id`, the last row of the branch the
person is looking at. A row that has a second child is a branch: an edited message is a sibling
of the one it replaced, and a regenerated answer is a sibling of the answer it replaced. One turn
stores several rows (the user's message, an assistant row with a tool call, a `tool` row with its
results, the answer) chained one under the other; only the first user row and the first assistant
row of a turn can have siblings. Conversations written before the tree are chains (each row's
parent is the row before it) and have no head: their head is their last row.
"""

import json
import weakref
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk.sqlite import ensure_tables, is_sqlite, now_iso

PRODUCT_ID = "wasifyai-assistant"
MAX_MESSAGES = 500  # per conversation: a bound, not a feature
HEAD = "@head"  # `add_message(parent_id=HEAD)`: under the conversation's current head (the default)


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    seq: int
    role: str  # user, assistant, tool
    parts: list[dict[str, Any]]
    created_at: str = ""
    parent_id: str | None = None

    def text(self) -> str:
        return "".join(str(p.get("text", "")) for p in self.parts if p.get("type") == "text")


def path_in(messages: list[Message], leaf_id: str | None) -> list[Message]:
    """The rows from the first message down to `leaf_id`, oldest first. No leaf, or one that is not
    there: the last row, for a conversation that was written before the tree."""
    by_id = {m.id: m for m in messages}
    cur = by_id.get(leaf_id or "") or (messages[-1] if messages else None)
    out: list[Message] = []
    seen: set[str] = set()
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        out.append(cur)
        cur = by_id.get(cur.parent_id or "")
    out.reverse()
    return out


def leaf_in(messages: list[Message], message_id: str) -> str | None:
    """The last row of the turn that starts at `message_id`: a user row is its own leaf; an
    assistant row leads down through its tool rows and follow-up rows (the newest child each
    time, never into the next user message). None when there is no such row."""
    by_id = {m.id: m for m in messages}
    cur = by_id.get(message_id)
    if cur is None:
        return None
    if cur.role == "user":
        return cur.id
    children: dict[str, list[Message]] = {}
    for m in messages:
        if m.parent_id and m.role != "user":
            children.setdefault(m.parent_id, []).append(m)
    seen: set[str] = set()
    while cur.id not in seen:
        seen.add(cur.id)
        nxt = children.get(cur.id)
        if not nxt:
            break
        cur = max(nxt, key=lambda m: m.seq)
    return cur.id


class ConversationStore(Protocol):
    async def create(self, tenant_id: str, user_id: str, title: str = "") -> Conversation: ...

    async def get(
        self, tenant_id: str, user_id: str, conversation_id: str
    ) -> Conversation | None: ...

    async def recent(
        self, tenant_id: str, user_id: str, limit: int, before: str | None = None
    ) -> list[Conversation]: ...

    async def rename(
        self, tenant_id: str, user_id: str, conversation_id: str, title: str
    ) -> bool: ...

    async def delete(self, tenant_id: str, user_id: str, conversation_id: str) -> bool: ...

    async def add_message(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        role: str,
        parts: list[dict[str, Any]],
        message_id: str | None = None,
        parent_id: str | None = HEAD,
    ) -> Message:
        """Add a message under `parent_id` (the head by default, None for a first message) and make
        it the head. `message_id` is an id the client chose for it; it is used unless a message with
        that id exists already (then the store makes one). A parent that is not in this
        conversation puts the message under the head."""
        ...

    async def set_parts(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        message_id: str,
        parts: list[dict[str, Any]],
    ) -> bool:
        """Replace the parts of a row of this conversation (a tool row written while the turn waited
        for the person's answer, completed after it). False when it is not there."""
        ...

    async def messages(
        self, tenant_id: str, user_id: str, conversation_id: str, limit: int = MAX_MESSAGES
    ) -> list[Message]:
        """Every row of the conversation, every branch, oldest first."""
        ...

    async def head(self, tenant_id: str, user_id: str, conversation_id: str) -> str | None:
        """The last row of the branch on screen (None: an empty conversation)."""
        ...

    async def set_head(
        self, tenant_id: str, user_id: str, conversation_id: str, message_id: str
    ) -> bool:
        """Show the branch that ends in the turn of `message_id`. False when it is not a row of
        this conversation."""
        ...

    async def path(
        self, tenant_id: str, user_id: str, conversation_id: str, leaf_id: str | None = None
    ) -> list[Message]:
        """The rows of one branch, oldest first: down to `leaf_id`, or to the head."""
        ...

    async def leaf_of(
        self, tenant_id: str, user_id: str, conversation_id: str, message_id: str
    ) -> str | None:
        """The last row of the turn that starts at `message_id` (see `leaf_in`)."""
        ...


_DDL = (
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        head_id TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_conversations_user_updated "
    "ON conversations (tenant_id, product_id, user_id, updated_at)",
    """
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        role TEXT NOT NULL,
        parts TEXT NOT NULL,
        created_at TEXT NOT NULL,
        parent_id TEXT
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_messages_conversation_seq "
    "ON messages (conversation_id, seq)",
)


async def _add_tree(engine: AsyncEngine) -> None:
    """A desktop database file made before the tree gets its two columns, and every old message
    its parent (the message before it), once. Done in one step so a half-way file cannot lose
    its order; migration 0021 does the same for the web profile."""
    done = _TREE_DONE.setdefault(engine, False)
    if done:
        return
    async with engine.begin() as conn:
        have = {
            str(r._mapping["name"])
            for r in await conn.exec_driver_sql("PRAGMA table_info(messages)")
        }
        if "parent_id" not in have:
            await conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN parent_id TEXT")
            await conn.exec_driver_sql(
                "UPDATE messages SET parent_id = (SELECT p.id FROM messages p "
                "WHERE p.conversation_id = messages.conversation_id AND p.seq = messages.seq - 1)"
            )
        have = {
            str(r._mapping["name"])
            for r in await conn.exec_driver_sql("PRAGMA table_info(conversations)")
        }
        if "head_id" not in have:
            await conn.exec_driver_sql("ALTER TABLE conversations ADD COLUMN head_id TEXT")
    _TREE_DONE[engine] = True


_TREE_DONE: "weakref.WeakKeyDictionary[AsyncEngine, bool]" = weakref.WeakKeyDictionary()


class SqlConversationStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        if is_sqlite(self._engine):  # the web profile's tables come from migrations 0018 and 0021
            await ensure_tables(self._engine, "assistant", _DDL)
            await _add_tree(self._engine)

    async def create(self, tenant_id: str, user_id: str, title: str = "") -> Conversation:
        await self._ready()
        now, cid = now_iso(), str(uuid4())
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO conversations (id, tenant_id, product_id, user_id, title, "
                    "created_at, updated_at) VALUES (:id, :t, :p, :u, :title, :now, :now)"
                ),
                {
                    "id": cid,
                    "t": tenant_id,
                    "p": PRODUCT_ID,
                    "u": user_id,
                    "title": title,
                    "now": now,
                },
            )
        return Conversation(cid, title, now, now)

    async def get(self, tenant_id: str, user_id: str, conversation_id: str) -> Conversation | None:
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, title, created_at, updated_at FROM conversations "
                        "WHERE id = :id AND tenant_id = :t AND product_id = :p AND user_id = :u"
                    ),
                    {"id": conversation_id, "t": tenant_id, "p": PRODUCT_ID, "u": user_id},
                )
            ).first()
        return Conversation(*row) if row else None

    async def recent(
        self, tenant_id: str, user_id: str, limit: int, before: str | None = None
    ) -> list[Conversation]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, title, created_at, updated_at FROM conversations "
                    "WHERE tenant_id = :t AND product_id = :p AND user_id = :u "
                    "AND (:before IS NULL OR updated_at < :before) "
                    "ORDER BY updated_at DESC, id DESC LIMIT :n"
                ),
                {"t": tenant_id, "p": PRODUCT_ID, "u": user_id, "before": before, "n": limit},
            )
            return [Conversation(*r) for r in rows]

    async def rename(self, tenant_id: str, user_id: str, conversation_id: str, title: str) -> bool:
        await self._ready()
        async with self._engine.begin() as conn:
            res = await conn.execute(
                text(
                    "UPDATE conversations SET title = :title WHERE id = :id AND tenant_id = :t "
                    "AND product_id = :p AND user_id = :u"
                ),
                {
                    "title": title,
                    "id": conversation_id,
                    "t": tenant_id,
                    "p": PRODUCT_ID,
                    "u": user_id,
                },
            )
            return (res.rowcount or 0) > 0

    async def delete(self, tenant_id: str, user_id: str, conversation_id: str) -> bool:
        await self._ready()
        if await self.get(tenant_id, user_id, conversation_id) is None:
            return False
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM messages WHERE conversation_id = :id AND tenant_id = :t "
                    "AND user_id = :u"
                ),
                {"id": conversation_id, "t": tenant_id, "u": user_id},
            )
            await conn.execute(
                text(
                    "DELETE FROM conversations WHERE id = :id AND tenant_id = :t AND user_id = :u"
                ),
                {"id": conversation_id, "t": tenant_id, "u": user_id},
            )
        return True

    async def add_message(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        role: str,
        parts: list[dict[str, Any]],
        message_id: str | None = None,
        parent_id: str | None = HEAD,
    ) -> Message:
        await self._ready()
        now, mid = now_iso(), message_id or str(uuid4())
        async with self._engine.begin() as conn:
            if (
                message_id
                and (
                    await conn.execute(
                        text("SELECT 1 FROM messages WHERE id = :id"), {"id": message_id}
                    )
                ).first()
            ):
                mid = str(uuid4())  # taken (by anyone): the client's id is only a wish
            seq = (
                await conn.execute(
                    text(
                        "SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id = :id"
                    ),
                    {"id": conversation_id},
                )
            ).scalar_one()
            parent = await self._parent(conn, conversation_id, parent_id)
            await conn.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, tenant_id, product_id, user_id, "
                    "seq, role, parts, created_at, parent_id) VALUES (:id, :c, :t, :p, :u, :seq, "
                    ":role, :parts, :now, :parent)"
                ),
                {
                    "id": mid, "c": conversation_id, "t": tenant_id, "p": PRODUCT_ID, "u": user_id,
                    "seq": int(seq), "role": role, "parts": json.dumps(parts), "now": now,
                    "parent": parent,
                },
            )  # fmt: skip
            await conn.execute(
                text("UPDATE conversations SET updated_at = :now, head_id = :mid WHERE id = :id"),
                {"now": now, "mid": mid, "id": conversation_id},
            )
        return Message(mid, conversation_id, int(seq), role, parts, now, parent)

    async def _parent(self, conn: Any, conversation_id: str, parent_id: str | None) -> str | None:
        """The row to put a new message under: the one asked for if it is in this conversation,
        nothing for a first message, else the head (the last row for an old conversation)."""
        if parent_id is None:
            return None
        if parent_id != HEAD:
            found = (
                await conn.execute(
                    text("SELECT id FROM messages WHERE id = :id AND conversation_id = :c"),
                    {"id": parent_id, "c": conversation_id},
                )
            ).first()
            if found:
                return str(found[0])
        row = (
            await conn.execute(
                text(
                    "SELECT COALESCE((SELECT m.id FROM messages m WHERE m.id = c.head_id "
                    "AND m.conversation_id = c.id), (SELECT m.id FROM messages m "
                    "WHERE m.conversation_id = c.id ORDER BY m.seq DESC LIMIT 1)) "
                    "FROM conversations c WHERE c.id = :c"
                ),
                {"c": conversation_id},
            )
        ).first()
        return str(row[0]) if row and row[0] else None

    async def set_parts(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        message_id: str,
        parts: list[dict[str, Any]],
    ) -> bool:
        await self._ready()
        async with self._engine.begin() as conn:
            res = await conn.execute(
                text(
                    "UPDATE messages SET parts = :parts WHERE id = :id AND conversation_id = :c "
                    "AND tenant_id = :t AND user_id = :u"
                ),
                {
                    "parts": json.dumps(parts), "id": message_id, "c": conversation_id,
                    "t": tenant_id, "u": user_id,
                },
            )  # fmt: skip
            return (res.rowcount or 0) > 0

    async def messages(
        self, tenant_id: str, user_id: str, conversation_id: str, limit: int = MAX_MESSAGES
    ) -> list[Message]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, conversation_id, seq, role, parts, created_at, parent_id "
                    "FROM messages WHERE conversation_id = :id AND tenant_id = :t "
                    "AND user_id = :u ORDER BY seq LIMIT :n"
                ),
                {"id": conversation_id, "t": tenant_id, "u": user_id, "n": limit},
            )
            return [Message(r[0], r[1], r[2], r[3], json.loads(r[4]), r[5], r[6]) for r in rows]

    async def head(self, tenant_id: str, user_id: str, conversation_id: str) -> str | None:
        await self._ready()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT head_id FROM conversations WHERE id = :id AND tenant_id = :t "
                        "AND product_id = :p AND user_id = :u"
                    ),
                    {"id": conversation_id, "t": tenant_id, "p": PRODUCT_ID, "u": user_id},
                )
            ).first()
        if row is None:
            return None
        if row[0]:
            return str(row[0])
        msgs = await self.messages(tenant_id, user_id, conversation_id)
        return msgs[-1].id if msgs else None

    async def set_head(
        self, tenant_id: str, user_id: str, conversation_id: str, message_id: str
    ) -> bool:
        msgs = await self.messages(tenant_id, user_id, conversation_id)
        leaf = leaf_in(msgs, message_id)
        if leaf is None:
            return False
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE conversations SET head_id = :h WHERE id = :id AND tenant_id = :t "
                    "AND product_id = :p AND user_id = :u"
                ),
                {"h": leaf, "id": conversation_id, "t": tenant_id, "p": PRODUCT_ID, "u": user_id},
            )
        return True

    async def path(
        self, tenant_id: str, user_id: str, conversation_id: str, leaf_id: str | None = None
    ) -> list[Message]:
        msgs = await self.messages(tenant_id, user_id, conversation_id)
        return path_in(msgs, leaf_id or await self.head(tenant_id, user_id, conversation_id))

    async def leaf_of(
        self, tenant_id: str, user_id: str, conversation_id: str, message_id: str
    ) -> str | None:
        return leaf_in(await self.messages(tenant_id, user_id, conversation_id), message_id)


@dataclass
class InMemoryConversationStore:
    """For tests: the same behaviour without a database."""

    _conversations: dict[str, tuple[str, str, Conversation]] = field(default_factory=dict)
    _messages: dict[str, list[Message]] = field(default_factory=dict)
    _heads: dict[str, str] = field(default_factory=dict)
    _tick: int = 0

    def _now(self) -> str:
        self._tick += 1
        return f"2026-10-16T00:00:{self._tick:06d}"

    async def create(self, tenant_id: str, user_id: str, title: str = "") -> Conversation:
        now, cid = self._now(), str(uuid4())
        conv = Conversation(cid, title, now, now)
        self._conversations[cid] = (tenant_id, user_id, conv)
        self._messages[cid] = []
        return conv

    def _mine(self, tenant_id: str, user_id: str, cid: str) -> Conversation | None:
        found = self._conversations.get(cid)
        return found[2] if found and found[:2] == (tenant_id, user_id) else None

    async def get(self, tenant_id: str, user_id: str, conversation_id: str) -> Conversation | None:
        return self._mine(tenant_id, user_id, conversation_id)

    async def recent(
        self, tenant_id: str, user_id: str, limit: int, before: str | None = None
    ) -> list[Conversation]:
        mine = [c for t, u, c in self._conversations.values() if (t, u) == (tenant_id, user_id)]
        mine = [c for c in mine if before is None or c.updated_at < before]
        return sorted(mine, key=lambda c: (c.updated_at, c.id), reverse=True)[:limit]

    async def rename(self, tenant_id: str, user_id: str, conversation_id: str, title: str) -> bool:
        c = self._mine(tenant_id, user_id, conversation_id)
        if c is None:
            return False
        self._conversations[conversation_id] = (
            tenant_id, user_id, Conversation(c.id, title, c.created_at, c.updated_at)
        )  # fmt: skip
        return True

    async def delete(self, tenant_id: str, user_id: str, conversation_id: str) -> bool:
        if self._mine(tenant_id, user_id, conversation_id) is None:
            return False
        del self._conversations[conversation_id]
        self._messages.pop(conversation_id, None)
        return True

    async def add_message(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        role: str,
        parts: list[dict[str, Any]],
        message_id: str | None = None,
        parent_id: str | None = HEAD,
    ) -> Message:
        c = self._mine(tenant_id, user_id, conversation_id)
        assert c is not None, "no such conversation"
        now = self._now()
        msgs = self._messages[conversation_id]
        taken = {x.id for ms in self._messages.values() for x in ms}
        mid = message_id if message_id and message_id not in taken else str(uuid4())
        parent: str | None
        if parent_id is None:
            parent = None
        elif parent_id != HEAD and any(x.id == parent_id for x in msgs):
            parent = parent_id
        else:
            parent = self._heads.get(conversation_id) or (msgs[-1].id if msgs else None)
        m = Message(mid, conversation_id, len(msgs) + 1, role, parts, now, parent)
        msgs.append(m)
        self._heads[conversation_id] = mid
        self._conversations[conversation_id] = (
            tenant_id, user_id, Conversation(c.id, c.title, c.created_at, now)
        )  # fmt: skip
        return m

    async def set_parts(
        self,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        message_id: str,
        parts: list[dict[str, Any]],
    ) -> bool:
        if self._mine(tenant_id, user_id, conversation_id) is None:
            return False
        msgs = self._messages[conversation_id]
        for i, x in enumerate(msgs):
            if x.id == message_id:
                msgs[i] = Message(
                    x.id, x.conversation_id, x.seq, x.role, parts, x.created_at, x.parent_id
                )
                return True
        return False

    async def messages(
        self, tenant_id: str, user_id: str, conversation_id: str, limit: int = MAX_MESSAGES
    ) -> list[Message]:
        if self._mine(tenant_id, user_id, conversation_id) is None:
            return []
        return list(self._messages[conversation_id])[:limit]

    async def head(self, tenant_id: str, user_id: str, conversation_id: str) -> str | None:
        if self._mine(tenant_id, user_id, conversation_id) is None:
            return None
        msgs = self._messages[conversation_id]
        return self._heads.get(conversation_id) or (msgs[-1].id if msgs else None)

    async def set_head(
        self, tenant_id: str, user_id: str, conversation_id: str, message_id: str
    ) -> bool:
        if self._mine(tenant_id, user_id, conversation_id) is None:
            return False
        leaf = leaf_in(self._messages[conversation_id], message_id)
        if leaf is None:
            return False
        self._heads[conversation_id] = leaf
        return True

    async def path(
        self, tenant_id: str, user_id: str, conversation_id: str, leaf_id: str | None = None
    ) -> list[Message]:
        msgs = await self.messages(tenant_id, user_id, conversation_id)
        return path_in(msgs, leaf_id or await self.head(tenant_id, user_id, conversation_id))

    async def leaf_of(
        self, tenant_id: str, user_id: str, conversation_id: str, message_id: str
    ) -> str | None:
        return leaf_in(await self.messages(tenant_id, user_id, conversation_id), message_id)
