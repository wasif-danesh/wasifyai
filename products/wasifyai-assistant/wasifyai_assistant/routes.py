"""The assistant's read API: a user's conversations under /products/wasifyai-assistant/.

Every query is scoped by tenant, product and user; another person's conversation is a plain 404."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk import Identity, RouteDeps

from wasifyai_assistant.store import (
    PRODUCT_ID,
    ConversationStore,
    SqlConversationStore,
)


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: str
    seq: int
    role: str
    parts: list[dict[str, Any]]
    created_at: str


class ConversationOut(ConversationSummary):
    messages: list[MessageOut]


class ConversationList(BaseModel):
    conversations: list[ConversationSummary]
    next_before: str | None


class Rename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)


def build_routes(deps: RouteDeps, store: ConversationStore | None = None) -> APIRouter:
    """`store` is injectable for tests; production reads the shared database."""
    router = APIRouter(tags=[PRODUCT_ID])

    def conversations() -> ConversationStore:
        return store or SqlConversationStore(deps.engine)

    @router.get("/conversations", response_model=ConversationList)
    async def list_conversations(
        limit: int = Query(30, ge=1, le=100),
        before: str | None = None,
        identity: Identity = Depends(deps.identity),
    ) -> ConversationList:
        rows = await conversations().recent(identity.tenant_id, identity.user_id, limit + 1, before)
        page, more = rows[:limit], len(rows) > limit
        return ConversationList(
            conversations=[ConversationSummary(**c.__dict__) for c in page],
            next_before=page[-1].updated_at if more and page else None,
        )

    @router.get("/conversations/{conversation_id}", response_model=ConversationOut)
    async def get_conversation(
        conversation_id: str, identity: Identity = Depends(deps.identity)
    ) -> ConversationOut:
        c = await conversations().get(identity.tenant_id, identity.user_id, conversation_id)
        if c is None:
            raise HTTPException(404, "conversation not found")
        msgs = await conversations().messages(identity.tenant_id, identity.user_id, c.id)
        return ConversationOut(
            **c.__dict__,
            messages=[
                MessageOut(id=m.id, seq=m.seq, role=m.role, parts=m.parts, created_at=m.created_at)
                for m in msgs
            ],
        )

    @router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
    async def rename_conversation(
        conversation_id: str, body: Rename, identity: Identity = Depends(deps.identity)
    ) -> ConversationSummary:
        ok = await conversations().rename(
            identity.tenant_id, identity.user_id, conversation_id, body.title.strip()
        )
        c = await conversations().get(identity.tenant_id, identity.user_id, conversation_id)
        if not ok or c is None:
            raise HTTPException(404, "conversation not found")
        return ConversationSummary(**c.__dict__)

    @router.delete("/conversations/{conversation_id}", status_code=204)
    async def delete_conversation(
        conversation_id: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        if not await conversations().delete(identity.tenant_id, identity.user_id, conversation_id):
            raise HTTPException(404, "conversation not found")
        await deps.unindex(identity, PRODUCT_ID, conversation_id)  # out of search too (ADR-0041)
        return Response(status_code=204)

    return router
