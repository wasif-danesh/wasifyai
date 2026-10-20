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


class SearchOptions(BaseModel):
    """Web search as the chat box sees it (ADR-0083): whether the Search button is there, and
    what pressing it first has to ask."""

    available: bool = False  # this engine can search at all
    consented: bool = False  # the person allowed searching with the service named below
    ready: bool = False  # allowed, and the service has its key
    provider: str = ""
    provider_title: str = ""
    consent_text: str = ""
    needs_key: bool = False  # the chosen service needs a key that is not saved yet


class ChatOptions(BaseModel):
    """What the chat box can offer with the model in use (ADR-0083)."""

    thinking: bool  # the model can think when asked: the box gets a Thinking switch
    search: SearchOptions = SearchOptions()


class SearchProviderOut(BaseModel):
    id: str
    title: str
    needs_key: bool
    key_set: bool
    key_url: str
    sends_to: str
    note: str


class SearchStatus(BaseModel):
    provider: str
    consented: bool
    consent_text: str
    can_save_keys: bool
    providers: list[SearchProviderOut]


class SearchKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(max_length=40)
    value: str = Field(max_length=400)


class SearchUpdate(BaseModel):
    """A change to web search settings. Keys are written, never read back."""

    model_config = ConfigDict(extra="forbid")
    provider: str | None = Field(default=None, max_length=40)
    consent: bool | None = None
    key: SearchKey | None = None
    remove_key: str | None = Field(default=None, max_length=40)


class Rename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)


def build_routes(deps: RouteDeps, store: ConversationStore | None = None) -> APIRouter:
    """`store` is injectable for tests; production reads the shared database."""
    router = APIRouter(tags=[PRODUCT_ID])

    def conversations() -> ConversationStore:
        return store or SqlConversationStore(deps.engine)

    @router.get("/options", response_model=ChatOptions)
    async def chat_options(identity: Identity = Depends(deps.identity)) -> ChatOptions:
        """Which options of the box work with the model in use: on the desktop the model the person
        chose (its chat template takes the thinking switch); on the web the chat alias, when its
        settings say how to switch thinking (`thinking_options`)."""
        language = getattr(deps.state, "desktop_language", None)
        if language is not None:
            chosen = language.selected
            thinking = bool(chosen and chosen.thinking)
        else:
            caps = (getattr(deps.state, "caps", None) or {}).get(PRODUCT_ID)
            try:
                binding = caps.text._bound["chat"][0] if caps is not None else None
            except (AttributeError, KeyError):
                binding = None
            thinking = bool(binding and binding.defaults.get("thinking_options"))
        return ChatOptions(thinking=thinking, search=await search_options())

    async def search_options() -> SearchOptions:
        web = getattr(deps.state, "web", None)
        if web is None:
            return SearchOptions()
        st = await web.status()
        chosen = next(p for p in st["providers"] if p["id"] == st["provider"])
        ready = (await web.readiness()).state == "ready"
        return SearchOptions(
            available=True,
            consented=st["consented"],
            ready=ready,
            provider=chosen["id"],
            provider_title=chosen["title"],
            consent_text=st["consent_text"],
            needs_key=chosen["needs_key"] and not chosen["key_set"],
        )

    @router.get("/search", response_model=SearchStatus)
    async def search_status(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """The web search settings: which service, whether the person allowed it, which keys are
        saved (never the keys)."""
        web = getattr(deps.state, "web", None)
        if web is None:
            raise HTTPException(404, "Web search is not available here.")
        return await web.status()

    @router.put("/search", response_model=SearchStatus)
    async def search_update(
        body: SearchUpdate, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        web = getattr(deps.state, "web", None)
        if web is None:
            raise HTTPException(404, "Web search is not available here.")
        try:
            return await web.update(
                provider=body.provider,
                consent=body.consent,
                key=(body.key.provider, body.key.value) if body.key else None,
                remove_key=body.remove_key,
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

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
