"""The coding product's API, under /products/wasifyai-code/code/: sessions, their turns, and the
models a session can run on. Desktop only: where there is no coding engine every route answers
404. Every route resolves a person, and every query is scoped by tenant, product and person.

Nothing here reaches the coding engine or gives out one of its ids or keys (ADR-0101, decision 4).
`GET /code/sessions/{id}/events` is the session's stream (the SSE contract, "A coding session's
stream"): one per session, open across its turns, with `Last-Event-ID` to come back."""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk import Identity, RouteDeps, parse_ids

from wasifyai_code import PRODUCT_ID, files
from wasifyai_code.runtime import NotAvailable, Refused, Sessions, owner_of, sessions_for, store_for


class CodeSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    folder: str = Field(min_length=1, max_length=1024)
    title: str = Field("", max_length=200)
    model: str = Field("", max_length=64)
    cost_limit_usd: float = Field(0, ge=0, le=100)
    mode: Literal["plan", "ask", "own"] = "plan"


class CodeSessionPatch(BaseModel):
    """What can be changed about a session: the most it may cost, and how much the agent asks."""

    model_config = ConfigDict(extra="forbid")

    cost_limit_usd: float | None = Field(None, gt=0, le=100)
    mode: Literal["plan", "ask", "own"] | None = None


class CodeAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: Literal["yes", "allow", "no"]


class CodeAllowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool


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
        status = {"not_found": 404, "busy": 409, "model_not_ready": 409, "not_last": 409}.get(
            e.code, 422
        )
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
                cost_limit_usd=body.cost_limit_usd, mode=body.mode,
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

    @router.patch("/sessions/{session_id}")
    async def change_session(
        session_id: str, body: CodeSessionPatch, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Change the most this session may cost (it holds from the next model call), or how
        much the agent asks (Plan, Ask me, Work on its own)."""
        live, owner = sessions(), owner_of(identity)
        try:
            if body.cost_limit_usd is not None:
                live.set_limit(owner, session_id, body.cost_limit_usd)
            if body.mode is not None:
                await live.set_mode(owner, session_id, body.mode)
            return live.view(owner, session_id)
        except Refused as e:
            raise refuse(e) from None

    @router.post("/sessions/{session_id}/asks/{ask_id}")
    async def answer_ask(
        session_id: str, ask_id: str, body: CodeAnswerIn,
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:  # fmt: skip
        """The person's answer to an approval card: yes, allow (yes, and stop asking about
        this kind of request in this project) or no."""
        live, owner = sessions(), owner_of(identity)
        try:
            taken = await live.answer(owner, session_id, ask_id, body.answer)
            return {"answered": taken, "session": live.view(owner, session_id)}
        except Refused as e:
            raise refuse(e) from None

    @router.get("/sessions/{session_id}/project")
    async def get_project(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """What this session's project may do: each kind of request and whether it is allowed."""
        try:
            return sessions().project(owner_of(identity), session_id)
        except Refused as e:
            raise refuse(e) from None

    @router.put("/sessions/{session_id}/project/allowed/{kind}")
    async def set_allowed(
        session_id: str, kind: str, body: CodeAllowIn,
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:  # fmt: skip
        """Allow a kind of request for the project, or take that back."""
        try:
            return sessions().allow(owner_of(identity), session_id, kind, body.allowed)
        except Refused as e:
            raise refuse(e) from None

    @router.get("/sessions/{session_id}/changes")
    async def list_changes(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """The turns that changed files, the newest first, each with its files (the Changes
        tab)."""
        try:
            return await sessions().changes(owner_of(identity), session_id)
        except Refused as e:
            raise refuse(e) from None

    @router.get("/sessions/{session_id}/changes/{turn_id}/file")
    async def read_change(
        session_id: str,
        turn_id: str,
        path: str = Query(min_length=1, max_length=2000),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """One file a turn changed: before, after, and the two as lines."""
        try:
            return await sessions().change(owner_of(identity), session_id, turn_id, path)
        except Refused as e:
            raise refuse(e) from None

    @router.post("/sessions/{session_id}/turns/{turn_id}/undo")
    async def undo_turn(
        session_id: str, turn_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Put the project's files back to how they were before this turn."""
        try:
            return await sessions().undo(owner_of(identity), session_id, turn_id)
        except Refused as e:
            raise refuse(e) from None

    @router.post("/sessions/{session_id}/turns/{turn_id}/redo")
    async def redo_turn(
        session_id: str, turn_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Bring an undone turn's changes back."""
        try:
            return await sessions().redo(owner_of(identity), session_id, turn_id)
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

    @router.get("/sessions/{session_id}/events")
    async def session_events(
        session_id: str,
        last_event_id: str | None = Header(None),
        identity: Identity = Depends(deps.identity),
    ) -> StreamingResponse:
        """The session's events as they happen. It stays open across turns; a turn's end is
        `code_state` with `state: "done"`."""
        live, owner = sessions(), owner_of(identity)
        try:
            live.view(owner, session_id)  # it must be this person's
        except Refused as e:
            raise refuse(e) from None
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
        return StreamingResponse(
            _stream(live.feed(session_id).follow(after), deps.state.heartbeat_s),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    def workspace_of(session_id: str, identity: Identity) -> str:
        try:
            return sessions().view(owner_of(identity), session_id)["folder"]
        except Refused as e:
            raise refuse(e) from None

    @router.get("/sessions/{session_id}/files")
    async def list_files(
        session_id: str,
        path: str = Query("", max_length=2000),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """One folder of the session's project (the Files tab). It is read by this engine for
        the person; the coding engine is not asked."""
        folder = workspace_of(session_id, identity)
        try:
            return await asyncio.to_thread(files.list_folder, Path(folder), path)
        except files.NotThere:
            raise HTTPException(404, "There is no such folder in this project.") from None

    @router.get("/sessions/{session_id}/files/find")
    async def find_files(
        session_id: str,
        q: str = Query(min_length=1, max_length=200),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """The project's files whose name holds `q` ("Find a file by name")."""
        folder = workspace_of(session_id, identity)
        return await asyncio.to_thread(files.find_files, Path(folder), q)

    @router.get("/sessions/{session_id}/file")
    async def read_file(
        session_id: str,
        path: str = Query(min_length=1, max_length=2000),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """One file of the session's project, to read."""
        folder = workspace_of(session_id, identity)
        try:
            return await asyncio.to_thread(files.read_file, Path(folder), path)
        except files.NotThere:
            raise HTTPException(404, "There is no such file in this project.") from None

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


async def _stream(
    events: AsyncIterator[dict[str, Any]], heartbeat_s: float
) -> AsyncGenerator[str, None]:
    """The feed as server-sent events, with a comment now and then so the connection stays open."""
    pending: asyncio.Future[dict[str, Any]] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(events))
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_s)
            if not done:
                yield ": ping\n\n"
                continue
            event, pending = pending.result(), None
            body = {k: v for k, v in event.items() if k != "event"}
            yield f"id: {event['seq']}\nevent: {event['event']}\ndata: {json.dumps(body)}\n\n"
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        close = getattr(events, "aclose", None)
        if close is not None:
            await close()
