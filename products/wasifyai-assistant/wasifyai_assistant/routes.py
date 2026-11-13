"""The assistant's read API: a user's conversations under /products/wasifyai-assistant/.

Every query is scoped by tenant, product and user; another person's conversation is a plain 404."""

import contextlib
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
    parent_id: str | None = None


class ConversationOut(ConversationSummary):
    messages: list[MessageOut]
    head_id: str | None = None  # the last message of the branch on screen


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


class AttachOptions(BaseModel):
    """Attaching files to a message (ADR-0083, CO2): what this engine and the model in use take."""

    available: bool = False  # the engine can keep an attachment at all
    images: bool | None = False  # the model reads pictures (None: not known, so try)
    documents: bool = False  # text, Markdown, CSV and HTML always; PDF and Office with the reader
    images_note: str = ""  # why a picture will not work, in words, when it will not
    # the app can fetch the model's picture reader: what it is and how big (None: nothing to offer)
    picture_reader: dict[str, Any] | None = None


class ChatOptions(BaseModel):
    """What the chat box can offer with the model in use (ADR-0083)."""

    thinking: bool  # the model can think when asked: the box gets a Thinking switch
    search: SearchOptions = SearchOptions()
    attach: AttachOptions = AttachOptions()


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


class ConversationPatch(BaseModel):
    """A change to a conversation: its title, or which branch is shown (`head_id`: a message of
    the branch; the engine keeps the last message of that turn)."""

    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=120)
    head_id: str | None = Field(default=None, max_length=80)


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
        language = deps.state.desktop_language
        if language is not None:
            chosen = language.selected
            thinking = bool(chosen and chosen.thinking)
            images: bool | None = getattr(chosen, "vision", False) if chosen else False
            why = (
                ""
                if images is not False
                else "This model reads pictures only with its picture reader (a file named "
                "mmproj, kept next to the model). None was found for this model."
            )
        else:
            caps = (deps.state.caps or {}).get(PRODUCT_ID)
            try:
                binding = caps.text._bound["chat"][0] if caps is not None else None
            except (AttributeError, KeyError):
                binding = None
            thinking = bool(binding and binding.defaults.get("thinking_options"))
            images = bool(binding and "image" in getattr(binding, "inputs", []))
            why = "" if images else "The chat model in use does not read pictures."
        stored = deps.state.uploads is not None and deps.storage is not None
        reader = None
        vision = deps.state.desktop_vision
        if stored and images is False and vision is not None:
            found = await vision.status()
            if found and found.get("state") in ("available", "downloading"):
                reader = found
        attach = AttachOptions(
            available=stored,
            images=images if stored else False,
            documents=stored,
            images_note=why,
            picture_reader=reader,
        )
        return ChatOptions(thinking=thinking, search=await search_options(identity), attach=attach)

    async def search_options(identity: Identity) -> SearchOptions:
        web = deps.state.web
        if web is None:
            return SearchOptions()
        st = await web.status(identity)
        chosen = next(p for p in st["providers"] if p["id"] == st["provider"])
        ready = (await web.readiness(identity)).state == "ready"
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
        web = deps.state.web
        if web is None:
            raise HTTPException(404, "Web search is not available here.")
        return await web.status(identity)

    @router.put("/search", response_model=SearchStatus)
    async def search_update(
        body: SearchUpdate, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        web = deps.state.web
        if web is None:
            raise HTTPException(404, "Web search is not available here.")
        # on a service the admins choose the search service and keep its keys; anyone may allow it
        if getattr(web, "per_person", False) and identity.role != "admin":
            if body.provider is not None or body.key is not None or body.remove_key is not None:
                raise HTTPException(403, "An admin chooses the search service and keeps its keys.")
        try:
            return await web.update(
                provider=body.provider,
                consent=body.consent,
                key=(body.key.provider, body.key.value) if body.key else None,
                remove_key=body.remove_key,
                who=identity,
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

    async def with_link(owner: tuple[str, str, str], part: dict[str, Any]) -> dict[str, Any]:
        """A picture attached to a message, with a short-lived link the window can show it from."""
        storage = deps.storage
        if part.get("type") != "attachment" or part.get("kind") != "image" or storage is None:
            return part
        try:
            return {**part, "url": await storage.url_for(owner, str(part.get("key", "")))}
        except ValueError:
            return part

    @router.get("/conversations/{conversation_id}", response_model=ConversationOut)
    async def get_conversation(
        conversation_id: str,
        tree: bool = Query(False, description="every branch, not only the one on screen"),
        identity: Identity = Depends(deps.identity),
    ) -> ConversationOut:
        """The conversation. Its messages are the branch on screen (oldest first), or with
        `tree=1` every message of every branch, each with its `parent_id`; `head_id` is the last
        message of the branch on screen."""
        c = await conversations().get(identity.tenant_id, identity.user_id, conversation_id)
        if c is None:
            raise HTTPException(404, "conversation not found")
        head = await conversations().head(identity.tenant_id, identity.user_id, c.id)
        if tree:
            msgs = await conversations().messages(identity.tenant_id, identity.user_id, c.id)
        else:
            msgs = await conversations().path(identity.tenant_id, identity.user_id, c.id, head)
        owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
        out: list[MessageOut] = []
        for m in msgs:
            parts = m.parts
            if any(p.get("type") == "attachment" for p in parts):
                parts = [await with_link(owner, p) for p in parts]
            out.append(
                MessageOut(
                    id=m.id,
                    seq=m.seq,
                    role=m.role,
                    parts=parts,
                    created_at=m.created_at,
                    parent_id=m.parent_id,
                )
            )
        return ConversationOut(**c.__dict__, head_id=head, messages=out)

    @router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
    async def patch_conversation(
        conversation_id: str, body: ConversationPatch, identity: Identity = Depends(deps.identity)
    ) -> ConversationSummary:
        """Rename the conversation, or show another branch (`head_id`)."""
        if body.title is None and body.head_id is None:
            raise HTTPException(422, "nothing to change")
        c = await conversations().get(identity.tenant_id, identity.user_id, conversation_id)
        if c is None:
            raise HTTPException(404, "conversation not found")
        if body.title is not None and not await conversations().rename(
            identity.tenant_id, identity.user_id, conversation_id, body.title.strip()
        ):
            raise HTTPException(404, "conversation not found")
        if body.head_id is not None and not await conversations().set_head(
            identity.tenant_id, identity.user_id, conversation_id, body.head_id
        ):
            raise HTTPException(404, "message not found")
        c = await conversations().get(identity.tenant_id, identity.user_id, conversation_id)
        if c is None:
            raise HTTPException(404, "conversation not found")
        return ConversationSummary(**c.__dict__)

    @router.delete("/conversations/{conversation_id}", status_code=204)
    async def delete_conversation(
        conversation_id: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        gone = await conversations().messages(identity.tenant_id, identity.user_id, conversation_id)
        if not await conversations().delete(identity.tenant_id, identity.user_id, conversation_id):
            raise HTTPException(404, "conversation not found")
        # what was attached goes with the conversation (ADR-0083)
        if deps.storage is not None:
            owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
            for m in gone:
                for p in m.parts:
                    if p.get("type") == "attachment":
                        with contextlib.suppress(FileNotFoundError, ValueError):
                            await deps.storage.delete_for(owner, str(p.get("key", "")))
        await deps.unindex(identity, PRODUCT_ID, conversation_id)  # out of search too (ADR-0041)
        return Response(status_code=204)

    return router
