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

from wasifyai_code import PRODUCT_ID, files, starters
from wasifyai_code import scheduled as runs
from wasifyai_code.runtime import (
    NotAvailable,
    Refused,
    Sessions,
    owner_of,
    scheduled_for,
    sessions_for,
    store_for,
)
from wasifyai_code.scheduled import ScheduleRefused
from wasifyai_code.terminal import TerminalError


class CodeSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    folder: str = Field(min_length=1, max_length=1024)
    title: str = Field("", max_length=200)
    model: str = Field("", max_length=128)
    cost_limit_usd: float = Field(0, ge=0, le=100)
    mode: Literal["plan", "ask", "own"] = "plan"


class CodeSessionPatch(BaseModel):
    """What can be changed about a session: the most it may cost, and how much the agent asks."""

    model_config = ConfigDict(extra="forbid")

    cost_limit_usd: float | None = Field(None, gt=0, le=100)
    # for a session on a model with no known price, which is counted in tokens
    token_limit: int | None = Field(None, gt=0, le=200_000_000)
    mode: Literal["plan", "ask", "own"] | None = None


class CodeAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: Literal["yes", "allow", "no"]


class CodeAllowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool


class CodeCheckIn(BaseModel):
    """The project's check: one command; empty means the project has none."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command: str = Field("", max_length=2000)
    limit_s: int | None = Field(None, ge=5, le=3600)


class CodePreviewIn(BaseModel):
    """The command that starts the project for its preview; empty means none is set."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command: str = Field("", max_length=2000)


class CodeNewIn(BaseModel):
    """A new project from a starter, in a new folder inside a folder the person chose."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    parent: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=64)
    starter: str = Field("web", max_length=32)
    model: str = Field("", max_length=128)
    mode: Literal["plan", "ask", "own"] = "ask"


class CodeSwitchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=64)
    on: bool


class CodeScheduleIn(BaseModel):
    """A schedule: what the agent is asked at each run, in which project, and when."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    workspace_id: str = Field(min_length=1, max_length=64)
    request: str = Field(min_length=1, max_length=20_000)
    rule: dict[str, Any]
    time_zone: str = Field("", max_length=64)  # empty: this computer's own
    title: str = Field("", max_length=200)
    model: str = Field("", max_length=128)
    run_when_missed: bool = True


class CodeSchedulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request: str | None = Field(None, min_length=1, max_length=20_000)
    rule: dict[str, Any] | None = None
    time_zone: str | None = Field(None, min_length=1, max_length=64)
    title: str | None = Field(None, max_length=200)
    model: str | None = Field(None, max_length=128)
    run_when_missed: bool | None = None
    enabled: bool | None = None


class CodeFolderIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    folder: str = Field(min_length=1, max_length=1024)
    workspace_id: str = Field("", max_length=64)


class CodeTerminalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cols: int = Field(80, ge=2, le=500)
    rows: int = Field(24, ge=2, le=300)


class CodeTerminalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: str = Field(min_length=1, max_length=65536)


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
        status = {
            "not_found": 404,
            "busy": 409,
            "model_not_ready": 409,
            "not_last": 409,
            "too_many": 409,
            "no_check": 409,
            "ended": 409,
            "not_empty": 409,
            "not_yours": 403,
            "taken": 409,
            "needs_approval": 409,
            "no_copy": 409,
            "not_signed_in": 409,
            "harness_not_installed": 409,
            "no_harness": 404,
            "nothing_to_install": 409,
            "not_on_harness": 409,
        }.get(  # fmt: skip
            e.code, 422
        )
        return HTTPException(status, {"code": e.code, "message": e.message})

    @router.get("/models")
    async def list_models(_: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """The models a session can run on, and whether each is ready (never a key)."""
        return {"items": await sessions().models()}

    @router.get("/harnesses")
    async def list_harnesses(_: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """The person's own agent programs (ADR-0107): set up or not, signed in or not, how and
        on which plan. Never an email or a token."""
        try:
            return {"items": await sessions().harnesses()}
        except Refused as e:
            raise refuse(e) from None

    @router.post("/harnesses/{harness}/sign-in")
    async def sign_in_harness(harness: str, _: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """Start the program's own sign-in: its page opens in the person's browser."""
        try:
            return await sessions().sign_in(harness)
        except Refused as e:
            raise refuse(e) from None

    @router.post("/harnesses/{harness}/sign-in/cancel")
    async def cancel_sign_in_harness(
        harness: str, _: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        try:
            return await sessions().cancel_sign_in(harness)
        except Refused as e:
            raise refuse(e) from None

    @router.get("/harnesses/{harness}/models")
    async def harness_models(harness: str, _: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """The models the program offers on the person's plan, named for a session's `model`."""
        try:
            return await sessions().harness_models(harness)
        except Refused as e:
            raise refuse(e) from None

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
        """Change the most this session may cost or use (it holds from the next model call), or how
        much the agent asks (Plan, Ask me, Work on its own)."""
        live, owner = sessions(), owner_of(identity)
        try:
            if body.cost_limit_usd is not None:
                live.set_limit(owner, session_id, body.cost_limit_usd)
            if body.token_limit is not None:
                live.set_token_limit(owner, session_id, body.token_limit)
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

    # ---- the check ------------------------------------------------------------------------------

    @router.get("/sessions/{session_id}/check")
    async def get_check(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """The project's check: its command, what the project's files suggest, and the last
        checks of this session."""
        live, owner = sessions(), owner_of(identity)
        try:
            return await asyncio.to_thread(live.check, owner, session_id)
        except Refused as e:
            raise refuse(e) from None

    @router.put("/sessions/{session_id}/check")
    async def put_check(
        session_id: str, body: CodeCheckIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Set the project's check command. It is kept by the app, outside the project."""
        live, owner = sessions(), owner_of(identity)
        try:
            return await asyncio.to_thread(
                live.set_check, owner, session_id, body.command, body.limit_s
            )
        except Refused as e:
            raise refuse(e) from None

    @router.post("/sessions/{session_id}/check/run")
    async def run_check(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Run the check now, outside a turn. It answers when the check has ended; Stop ends
        it."""
        live, owner = sessions(), owner_of(identity)
        try:
            row = await live.check_now(owner, session_id)
            return {"check": row, "session": live.view(owner, session_id)}
        except Refused as e:
            raise refuse(e) from None

    @router.get("/sessions/{session_id}/checks/{check_id}")
    async def check_output(
        session_id: str, check_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """One check of this session with its whole output."""
        live, owner = sessions(), owner_of(identity)
        try:
            return await asyncio.to_thread(live.check_output, owner, session_id, check_id)
        except Refused as e:
            raise refuse(e) from None

    @router.post("/sessions/{session_id}/check/again", status_code=202)
    async def try_again(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Three more rounds: a new turn that tells the agent the check still fails."""
        live, owner = sessions(), owner_of(identity)
        try:
            turn = await live.try_again(owner, session_id)
            return {"turn_id": turn["id"], "session": live.view(owner, session_id)}
        except Refused as e:
            raise refuse(e) from None

    # ---- installs for a session on a program (ADR-0107, stage H4) -------------------------------

    @router.post("/sessions/{session_id}/install", status_code=202)
    async def install(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Install what the project lists, in Wasify AI's own sandbox, for the session's program.
        It answers at once; the `code_install` events say how it goes."""
        try:
            return await sessions().install(owner_of(identity), session_id)
        except Refused as e:
            raise refuse(e) from None

    @router.delete("/sessions/{session_id}/install")
    async def not_now(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Close the install card ("Not now")."""
        try:
            return sessions().not_now(owner_of(identity), session_id)
        except Refused as e:
            raise refuse(e) from None

    # ---- extensions (ADR-0104) -------------------------------------------------------------------

    @router.get("/workspaces")
    async def list_workspaces(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """The person's projects, the newest first."""
        return {"items": await asyncio.to_thread(sessions().workspaces, owner_of(identity))}

    @router.get("/extensions")
    async def list_extensions(
        workspace_id: str = Query("", max_length=64),
        ids: str | None = Query(None, max_length=4000),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """The short list and what the person added; with `workspace_id`, whether each is on
        for that project. `ids` (the ids of added ones, for search) keeps only those."""
        live, owner = sessions(), owner_of(identity)
        try:
            items = await asyncio.to_thread(live.list_extensions, owner, workspace_id)
        except Refused as e:
            raise refuse(e) from None
        if ids is not None:
            wanted = {f"added:{i}" for i in parse_ids(ids) or []}
            items = [i for i in items if i["id"] in wanted]
        return {"items": items}

    @router.post("/extensions/look")
    async def look_at_folder(
        body: CodeFolderIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """What a folder holds, before it is added: a skill with its text, or why not."""
        live = sessions()
        try:
            return await asyncio.to_thread(live.look_at_folder, body.folder)
        except Refused as e:
            raise refuse(e) from None

    @router.post("/extensions", status_code=201)
    async def add_extension(
        body: CodeFolderIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Copy a skill's folder in. With `workspace_id` it is switched on for that project."""
        try:
            return await sessions().add_extension(
                owner_of(identity), body.folder, body.workspace_id
            )
        except Refused as e:
            raise refuse(e) from None

    @router.get("/extensions/{extension_id}")
    async def get_extension(
        extension_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """One extension with the whole text it gives the agent, and where it is on."""
        live, owner = sessions(), owner_of(identity)
        try:
            return await asyncio.to_thread(live.extension, owner, extension_id)
        except Refused as e:
            raise refuse(e) from None

    @router.put("/extensions/{extension_id}/on")
    async def switch_extension(
        extension_id: str, body: CodeSwitchIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Switch an extension on or off for one project."""
        try:
            return await sessions().switch_extension(
                owner_of(identity), extension_id, body.workspace_id, body.on
            )
        except Refused as e:
            raise refuse(e) from None

    @router.delete("/extensions/{extension_id}", status_code=204)
    async def remove_extension(
        extension_id: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        """Forget an extension the person added."""
        try:
            gone = await sessions().remove_extension(owner_of(identity), extension_id)
        except Refused as e:
            raise refuse(e) from None
        if gone:
            await deps.unindex(identity, PRODUCT_ID, extension_id.partition(":")[2])
        return Response(status_code=204)

    @router.post("/extensions/{extension_id}/approve")
    async def approve_extension(
        extension_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """The person has seen what a plugin brings (its hooks, its tool connections) and says
        yes. It is not an action: only a person at the window approves."""
        live, owner = sessions(), owner_of(identity)
        try:
            return await asyncio.to_thread(live.approve_extension, owner, extension_id)
        except Refused as e:
            raise refuse(e) from None

    # ---- scheduled runs (ADR-0105) ---------------------------------------------------------------

    def scheduled() -> runs.Scheduled:
        try:
            return scheduled_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(404, str(e)) from None

    def refused(e: ScheduleRefused) -> HTTPException:
        return refuse(Refused(e.code, e.message))

    @router.get("/schedules/templates")
    async def list_templates(_: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """Our short list of starting points for a schedule."""
        scheduled()
        return {"items": await asyncio.to_thread(runs.templates)}

    @router.get("/schedules")
    async def list_schedules(
        ids: str | None = Query(None, max_length=4000),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """The person's schedules, the newest first, each with its next time and last run.
        `ids` (for search) keeps only those."""
        live = scheduled()
        return {
            "items": await asyncio.to_thread(live.list, owner_of(identity), parse_ids(ids)),
            "time_zone": runs.time_zone_of_this_computer(),
        }

    @router.post("/schedules", status_code=201)
    async def add_schedule(
        body: CodeScheduleIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        live = scheduled()
        try:
            made = await asyncio.to_thread(
                lambda: live.add(
                    owner_of(identity), workspace_id=body.workspace_id, request=body.request,
                    rule=body.rule, time_zone=body.time_zone or runs.time_zone_of_this_computer(),
                    title=body.title, model=body.model, run_when_missed=body.run_when_missed,
                )
            )  # fmt: skip
        except ScheduleRefused as e:
            raise refused(e) from None
        live.start()
        await live.index(owner_of(identity), made)
        return made

    @router.get("/schedules/{schedule_id}")
    async def get_schedule(
        schedule_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """One schedule with its runs, the newest first."""
        try:
            return await asyncio.to_thread(scheduled().get, owner_of(identity), schedule_id)
        except ScheduleRefused as e:
            raise refused(e) from None

    @router.patch("/schedules/{schedule_id}")
    async def change_schedule(
        schedule_id: str, body: CodeSchedulePatch, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Change what it asks or when it runs, or pause it (`enabled`)."""
        live, given = scheduled(), body.model_dump(exclude_none=True)
        try:
            made = await asyncio.to_thread(
                lambda: live.change(owner_of(identity), schedule_id, **given)
            )
        except ScheduleRefused as e:
            raise refused(e) from None
        await live.index(owner_of(identity), made)
        return made

    @router.delete("/schedules/{schedule_id}", status_code=204)
    async def remove_schedule(
        schedule_id: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        """Forget a schedule, its history and the copies of its runs. Never the project."""
        try:
            await scheduled().remove(owner_of(identity), schedule_id)
        except ScheduleRefused as e:
            raise refused(e) from None
        await deps.unindex(identity, PRODUCT_ID, schedule_id)
        return Response(status_code=204)

    @router.post("/schedules/{schedule_id}/run", status_code=202)
    async def run_schedule_now(
        schedule_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """ "Run now": the same run as at its time."""
        try:
            return scheduled().run_now(owner_of(identity), schedule_id)
        except ScheduleRefused as e:
            raise refused(e) from None

    @router.get("/schedules/runs/{run_id}/changes")
    async def run_changes(
        run_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """What a run changed in its copy, and for each file whether the project's own file was
        changed meanwhile."""
        try:
            return await scheduled().changes(owner_of(identity), run_id)
        except ScheduleRefused as e:
            raise refused(e) from None

    @router.post("/schedules/runs/{run_id}/apply")
    async def apply_run(run_id: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """Write a run's changes into the project; a file changed meanwhile is left and named."""
        try:
            return await scheduled().apply(owner_of(identity), run_id)
        except ScheduleRefused as e:
            raise refused(e) from None

    @router.post("/schedules/runs/{run_id}/discard")
    async def discard_run(
        run_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Let a run's changes go. The project is as it was."""
        try:
            return await scheduled().discard(owner_of(identity), run_id)
        except ScheduleRefused as e:
            raise refused(e) from None

    @router.post("/schedules/runs/{run_id}/stop")
    async def stop_run(run_id: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        try:
            return {"stopped": await scheduled().stop(owner_of(identity), run_id)}
        except ScheduleRefused as e:
            raise refused(e) from None

    # ---- the preview and the starters ------------------------------------------------------------

    @router.get("/starters")
    async def list_starters(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """What a new project can be started from."""
        sessions()
        return {"items": starters.list_starters()}

    @router.post("/projects", status_code=201)
    async def new_project(
        body: CodeNewIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """A new project from a starter, in a new folder inside `parent`, and a session on it."""
        try:
            return await sessions().start_new(
                owner_of(identity), parent=body.parent, name=body.name, starter=body.starter,
                model=body.model, mode=body.mode,
            )  # fmt: skip
        except Refused as e:
            raise refuse(e) from None

    @router.get("/sessions/{session_id}/preview")
    async def get_preview(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """The project's preview: its command, what the files suggest, and the running one
        (its state, its port on this computer, the end of its output)."""
        live, owner = sessions(), owner_of(identity)
        try:
            return await asyncio.to_thread(live.preview, owner, session_id)
        except Refused as e:
            raise refuse(e) from None

    @router.put("/sessions/{session_id}/preview")
    async def put_preview(
        session_id: str, body: CodePreviewIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        live, owner = sessions(), owner_of(identity)
        try:
            return await asyncio.to_thread(live.set_preview, owner, session_id, body.command)
        except Refused as e:
            raise refuse(e) from None

    @router.post("/sessions/{session_id}/preview/start")
    async def start_preview(
        session_id: str,
        body: CodePreviewIn | None = None,
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """Start the project inside its sandbox. It answers at once; the state is read again
        until it runs."""
        try:
            return await sessions().start_preview(
                owner_of(identity), session_id, body.command if body else None
            )
        except Refused as e:
            raise refuse(e) from None

    @router.post("/sessions/{session_id}/preview/stop")
    async def stop_preview(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Stop the preview and everything it started."""
        try:
            return await sessions().stop_preview(owner_of(identity), session_id)
        except Refused as e:
            raise refuse(e) from None

    # ---- the person's terminal -------------------------------------------------------------------

    @router.get("/sessions/{session_id}/terminals")
    async def list_terminals(
        session_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        try:
            return {"items": sessions().list_terminals(owner_of(identity), session_id)}
        except Refused as e:
            raise refuse(e) from None

    @router.post("/sessions/{session_id}/terminals", status_code=201)
    async def open_terminal(
        session_id: str, body: CodeTerminalIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Open a terminal of the person's own in the project, inside the sandbox."""
        try:
            return await sessions().open_terminal(
                owner_of(identity), session_id, body.cols, body.rows
            )
        except Refused as e:
            raise refuse(e) from None

    @router.get("/sessions/{session_id}/terminals/{terminal_id}/events")
    async def terminal_events(
        session_id: str,
        terminal_id: str,
        last_event_id: str | None = Header(None),
        identity: Identity = Depends(deps.identity),
    ) -> StreamingResponse:
        """What the terminal prints, as it comes (`terminal_output`, the bytes in base64), and
        `terminal_ended` when its shell has ended."""
        try:
            found = sessions().terminal(owner_of(identity), session_id, terminal_id)
        except Refused as e:
            raise refuse(e) from None
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
        return StreamingResponse(
            _stream(found.follow(after), deps.state.heartbeat_s),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @router.post("/sessions/{session_id}/terminals/{terminal_id}/input", status_code=204)
    async def terminal_input(
        session_id: str,
        terminal_id: str,
        body: CodeTerminalInput,
        identity: Identity = Depends(deps.identity),
    ) -> Response:
        """What the person typed."""
        try:
            sessions().terminal(owner_of(identity), session_id, terminal_id).write(body.data)
        except Refused as e:
            raise refuse(e) from None
        except TerminalError as e:
            raise HTTPException(409, {"code": e.code, "message": e.message}) from None
        return Response(status_code=204)

    @router.post("/sessions/{session_id}/terminals/{terminal_id}/size", status_code=204)
    async def terminal_size(
        session_id: str,
        terminal_id: str,
        body: CodeTerminalIn,
        identity: Identity = Depends(deps.identity),
    ) -> Response:
        try:
            found = sessions().terminal(owner_of(identity), session_id, terminal_id)
        except Refused as e:
            raise refuse(e) from None
        found.resize(body.cols, body.rows)
        return Response(status_code=204)

    @router.delete("/sessions/{session_id}/terminals/{terminal_id}", status_code=204)
    async def close_terminal(
        session_id: str, terminal_id: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        """Close a terminal: its shell and everything it started are ended."""
        try:
            await sessions().close_terminal(owner_of(identity), session_id, terminal_id)
        except Refused as e:
            raise refuse(e) from None
        return Response(status_code=204)

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
