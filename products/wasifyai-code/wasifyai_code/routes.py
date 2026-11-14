"""The coding product's API, under /products/wasifyai-code/code/: sessions, their turns, and the
models a session can run on. Desktop only: where there is no coding engine every route answers
404. Every route resolves a person, and every query is scoped by tenant, product and person.

Nothing here reaches the coding engine or gives out one of its ids or keys (ADR-0101, decision 4).
There is no stream yet: the session's events are relayed inside the engine (`runtime.Feed`) until
the new event kinds are agreed for the SSE contract (`docs/spikes/coding-c1b.md`). Until then a
caller reads a session's state with `GET /code/sessions/{id}`."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk import Identity, RouteDeps, parse_ids

from wasifyai_code import PRODUCT_ID
from wasifyai_code.runtime import NotAvailable, Refused, Sessions, owner_of, sessions_for, store_for


class CodeSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    folder: str = Field(min_length=1, max_length=1024)
    title: str = Field("", max_length=200)
    model: str = Field("", max_length=64)
    cost_limit_usd: float = Field(0, ge=0, le=100)


class CodeMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=20000)


def build_routes(deps: RouteDeps) -> APIRouter:
    router = APIRouter(prefix="/code", tags=[PRODUCT_ID])

    def sessions() -> Sessions:
        try:
            return sessions_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(404, str(e)) from None

    def refuse(e: Refused) -> HTTPException:
        status = {"not_found": 404, "busy": 409, "model_not_ready": 409}.get(e.code, 422)
        return HTTPException(status, {"code": e.code, "message": e.message})

    @router.get("/models")
    async def list_models(_: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """The models a session can run on, and whether each is ready (never a key)."""
        return {"items": await sessions().models()}

    @router.post("/sessions", status_code=201)
    async def start_session(
        body: CodeSessionIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        try:
            return await sessions().start(
                owner_of(identity), folder=body.folder, title=body.title, model=body.model,
                cost_limit_usd=body.cost_limit_usd,
            )  # fmt: skip
        except Refused as e:
            raise refuse(e) from None

    @router.get("/sessions")
    async def list_sessions(
        ids: str | None = Query(None, max_length=2000),
        limit: int = Query(50, ge=1, le=200),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        live, owner = sessions(), owner_of(identity)
        found = await asyncio.to_thread(
            store_for(deps.state).list_sessions, owner, None, parse_ids(ids)
        )
        return {"items": [live.view(owner, row["id"]) for row in found[:limit]]}

    @router.get("/sessions/{session_id}")
    async def get_session(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        try:
            return sessions().view(owner_of(identity), session_id)
        except Refused as e:
            raise refuse(e) from None

    @router.get("/sessions/{session_id}/turns")
    async def list_turns(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        try:
            return {"items": sessions().turns(owner_of(identity), session_id)}
        except Refused as e:
            raise refuse(e) from None

    @router.post("/sessions/{session_id}/messages", status_code=202)
    async def send_message(
        session_id: str, body: CodeMessageIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Begin a turn. It answers at once with the turn; the agent works on in the engine."""
        live, owner = sessions(), owner_of(identity)
        try:
            turn = await live.send(owner, session_id, body.text)
            return {"turn_id": turn["id"], "session": live.view(owner, session_id)}
        except Refused as e:
            raise refuse(e) from None

    @router.post("/sessions/{session_id}/stop")
    async def stop_session(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Stop the turn in flight. It answers when the turn is closed."""
        live, owner = sessions(), owner_of(identity)
        try:
            stopped = await live.stop(owner, session_id)
            return {"stopped": stopped, "session": live.view(owner, session_id)}
        except Refused as e:
            raise refuse(e) from None

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        try:
            await sessions().delete(owner_of(identity), session_id)
        except Refused:
            return Response(status_code=204)  # already gone
        await deps.unindex(identity, PRODUCT_ID, session_id)
        return Response(status_code=204)

    return router
