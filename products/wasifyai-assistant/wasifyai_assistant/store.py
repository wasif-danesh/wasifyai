"""Conversations and their messages (ADR-0057 decision 3).

Ids are text and times are UTC ISO strings in both databases, so one implementation serves the
web profile (Postgres, migration 0018) and the desktop profile (SQLite, created on first use).
Every query is scoped by tenant, product and user (rules 7 to 9). A message's `parts` is JSON:

    {"type": "text", "text": "..."}
    {"type": "tool_call", "id": "...", "name": "...", "arguments": {...}}
    {"type": "tool_result", "id": "...", "name": "...", "status": "ok", "output": {...},
     "text": "..."}
"""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk.sqlite import ensure_tables, is_sqlite, now_iso

PRODUCT_ID = "wasifyai-assistant"
MAX_MESSAGES = 500  # per conversation: a bound, not a feature


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

    def text(self) -> str:
        return "".join(str(p.get("text", "")) for p in self.parts if p.get("type") == "text")


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
    ) -> Message:
        """Add a message. `message_id` is an id the client chose for it; it is used unless a message
        with that id exists already (then the store makes one)."""
        ...

    async def messages(
        self, tenant_id: str, user_id: str, conversation_id: str, limit: int = MAX_MESSAGES
    ) -> list[Message]: ...


_DDL = (
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
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
        created_at TEXT NOT NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_messages_conversation_seq "
    "ON messages (conversation_id, seq)",
)


class SqlConversationStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def _ready(self) -> None:
        if is_sqlite(self._engine):  # the web profile's tables come from migration 0018
            await ensure_tables(self._engine, "assistant", _DDL)

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
            await conn.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, tenant_id, product_id, user_id, "
                    "seq, role, parts, created_at) VALUES (:id, :c, :t, :p, :u, :seq, :role, "
                    ":parts, :now)"
                ),
                {
                    "id": mid, "c": conversation_id, "t": tenant_id, "p": PRODUCT_ID, "u": user_id,
                    "seq": int(seq), "role": role, "parts": json.dumps(parts), "now": now,
                },
            )  # fmt: skip
            await conn.execute(
                text("UPDATE conversations SET updated_at = :now WHERE id = :id"),
                {"now": now, "id": conversation_id},
            )
        return Message(mid, conversation_id, int(seq), role, parts, now)

    async def messages(
        self, tenant_id: str, user_id: str, conversation_id: str, limit: int = MAX_MESSAGES
    ) -> list[Message]:
        await self._ready()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, conversation_id, seq, role, parts, created_at FROM messages "
                    "WHERE conversation_id = :id AND tenant_id = :t AND user_id = :u "
                    "ORDER BY seq LIMIT :n"
                ),
                {"id": conversation_id, "t": tenant_id, "u": user_id, "n": limit},
            )
            return [Message(r[0], r[1], r[2], r[3], json.loads(r[4]), r[5]) for r in rows]


@dataclass
class InMemoryConversationStore:
    """For tests: the same behaviour without a database."""

    _conversations: dict[str, tuple[str, str, Conversation]] = field(default_factory=dict)
    _messages: dict[str, list[Message]] = field(default_factory=dict)
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
    ) -> Message:
        c = self._mine(tenant_id, user_id, conversation_id)
        assert c is not None, "no such conversation"
        now = self._now()
        msgs = self._messages[conversation_id]
        taken = {x.id for ms in self._messages.values() for x in ms}
        mid = message_id if message_id and message_id not in taken else str(uuid4())
        m = Message(mid, conversation_id, len(msgs) + 1, role, parts, now)
        msgs.append(m)
        self._conversations[conversation_id] = (
            tenant_id, user_id, Conversation(c.id, c.title, c.created_at, now)
        )  # fmt: skip
        return m

    async def messages(
        self, tenant_id: str, user_id: str, conversation_id: str, limit: int = MAX_MESSAGES
    ) -> list[Message]:
        if self._mine(tenant_id, user_id, conversation_id) is None:
            return []
        return list(self._messages[conversation_id])[:limit]
