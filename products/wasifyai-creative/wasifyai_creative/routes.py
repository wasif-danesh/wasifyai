# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""Creative Studio's API, under /products/wasifyai-creative/: projects, writing a plan, and changing it. Desktop first:
where the product has no folder every route answers 404. Every query is scoped by tenant and user."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk import Identity, RouteDeps, parse_ids

from wasifyai_creative.document import Brief, EditRefused, apply_edits, problems
from wasifyai_creative.runtime import (
    NotAvailable,
    Refused,
    add_to_search,
    delete_project,
    manager_for,
    store_for,
)
from wasifyai_creative.store import NotFound

PRODUCT_ID = "wasifyai-creative"


class NewProject(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field("", max_length=200)
    brief: Brief


class ChangeProject(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(None, min_length=1, max_length=200)
    brief: Brief | None = None


class MakePlan(BaseModel):
    again: bool = False  # start afresh, instead of going on from the steps already finished


class Edits(BaseModel):
    edits: list[dict[str, Any]] = Field(min_length=1, max_length=50)


class KeepConversation(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=64)


class AddMedia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=20)
    item_id: str = Field(min_length=1, max_length=64)
    shot_id: str | None = Field(None, max_length=32)


def title_of(given: str, brief: Brief) -> str:
    if given:
        return given
    # a whole-word name: an idea's first 60 characters, back to the last space
    short = brief.idea if len(brief.idea) <= 60 else brief.idea[:60].rsplit(" ", 1)[0]
    return short.rstrip(" ,.") or "New project"


def cast_names(row: dict[str, Any]) -> list[str]:
    return [p["name"] for p in row["brief"].get("cast", [])]


def edit_project(row: dict[str, Any], store: Any, edits: list[dict[str, Any]], note: str) -> None:
    """Make the edits and keep a new revision, or raise `EditRefused` and change nothing."""
    if not row["plan"]:
        raise EditRefused("There is no plan to change yet.")
    new = apply_edits(row["plan"], edits, row["facts"].get("beats", []))
    if new == row["plan"]:
        raise EditRefused("The plan already says that, so there is nothing to change.")
    wrong = problems(new, cast_names(row), float(row["facts"].get("seconds", 0)))
    if wrong:
        raise EditRefused(wrong[0])
    store.save_plan(row["id"], new, note)


def build_routes(deps: RouteDeps) -> APIRouter:
    router = APIRouter(prefix="/creative", tags=[PRODUCT_ID])

    def store() -> Any:
        try:
            return store_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(404, str(e)) from None

    def out(row: dict[str, Any], identity: Identity) -> dict[str, Any]:
        found = {k: v for k, v in row.items() if k not in ("tenant_id", "user_id")}
        found["live"] = manager_for(deps).active(identity) == row["id"]
        return found

    def row_or_404(identity: Identity, item: str) -> dict[str, Any]:
        try:
            return store().get(identity.tenant_id, identity.user_id, item)
        except NotFound:
            raise HTTPException(404, "project not found") from None

    def refuse(e: Refused) -> HTTPException:
        return HTTPException(409, {"code": e.code, "message": e.message})

    @router.get("/status")
    async def status(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        store()
        tool = deps.state.music_analysis
        return {
            "analysis": tool.state() if tool is not None else None,
            "writing": manager_for(deps).active(identity),
        }

    @router.get("/projects")
    async def list_projects(
        ids: str | None = Query(None, max_length=4000),
        limit: int = Query(50, ge=1, le=200),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        wanted = parse_ids(ids)
        rows = await asyncio.to_thread(
            store().list_projects, identity.tenant_id, identity.user_id, wanted, limit
        )
        return {"items": [out(r, identity) for r in rows]}

    @router.post("/projects", status_code=201)
    async def add_project(
        body: NewProject, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        row = store().add(
            identity.tenant_id, identity.user_id, title_of(body.title, body.brief),
            body.brief.model_dump(),
        )  # fmt: skip
        await add_to_search(deps.state, identity, row)
        return out(row, identity)

    @router.get("/projects/{item}")
    async def get_project(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        return out(row_or_404(identity, item), identity)

    @router.patch("/projects/{item}")
    async def change_project(
        item: str, body: ChangeProject, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        row = row_or_404(identity, item)
        if manager_for(deps).active(identity) == item:
            raise HTTPException(409, {"code": "busy", "message": "The plan is being written."})
        brief = body.brief.model_dump() if body.brief else row["brief"]
        store().set_brief(item, body.title or row["title"], brief)
        fresh = row_or_404(identity, item)
        await add_to_search(deps.state, identity, fresh)
        return out(fresh, identity)

    @router.delete("/projects/{item}", status_code=204)
    async def remove_project(item: str, identity: Identity = Depends(deps.identity)) -> None:
        row_or_404(identity, item)
        await delete_project(deps, identity, item)

    # ---- the plan ------------------------------------------------------------------------------

    @router.post("/projects/{item}/plan", status_code=202)
    async def make_plan(
        item: str, body: MakePlan, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Write the plan, or go on with one that stopped. Follow it with GET."""
        row_or_404(identity, item)
        try:
            manager_for(deps).start(identity, item, again=body.again)
        except Refused as e:
            raise refuse(e) from None
        return out(row_or_404(identity, item), identity)

    @router.post("/projects/{item}/plan/stop")
    async def stop_plan(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        row_or_404(identity, item)
        await manager_for(deps).stop_and_wait(identity, item)
        return out(row_or_404(identity, item), identity)

    @router.post("/projects/{item}/edits")
    async def edit_plan(
        item: str, body: Edits, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        row = row_or_404(identity, item)
        if manager_for(deps).active(identity) == item:
            raise HTTPException(409, {"code": "busy", "message": "The plan is being written."})
        try:
            edit_project(row, store(), body.edits, "Changed on the screen")
        except EditRefused as e:
            raise HTTPException(422, {"code": "bad_edit", "message": str(e)}) from None
        fresh = row_or_404(identity, item)
        await add_to_search(deps.state, identity, fresh)
        return out(fresh, identity)

    @router.post("/projects/{item}/undo")
    async def undo(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        row_or_404(identity, item)
        if store().undo(item) is None:
            raise HTTPException(409, {"code": "nothing", "message": "There is nothing to undo."})
        fresh = row_or_404(identity, item)
        await add_to_search(deps.state, identity, fresh)
        return out(fresh, identity)

    @router.post("/projects/{item}/parts/{beat}/rewrite", status_code=202)
    async def rewrite(
        item: str, beat: int, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Try another idea for this part; the other shots stay. Follow it with GET."""
        row_or_404(identity, item)
        try:
            manager_for(deps).rewrite(identity, item, beat)
        except Refused as e:
            raise refuse(e) from None
        return out(row_or_404(identity, item), identity)

    @router.put("/projects/{item}/conversation")
    async def keep_conversation(
        item: str, body: KeepConversation, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """The Ask tab's chat, so that coming back finds it."""
        row_or_404(identity, item)
        store().keep_conversation(item, body.conversation_id)
        return {"conversation_id": body.conversation_id}

    # ---- what was made for it: the library, filtered by this project ---------------------------

    async def run_media(action: str, params: dict[str, Any], identity: Identity) -> None:
        executor = deps.state.actions
        if executor is None:
            raise HTTPException(404, "actions are not available")
        done = await executor.run_action(action, params, "window", actor=identity)
        if done.status != "ok":
            raise HTTPException(409, {"code": done.code or "refused", "message": done.text})

    @router.get("/projects/{item}/media")
    async def list_media(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        row_or_404(identity, item)
        return {"items": await asyncio.to_thread(store().media_of, item)}

    @router.post("/projects/{item}/media", status_code=201)
    async def add_media(
        item: str, body: AddMedia, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        row_or_404(identity, item)
        await run_media("creative.add_media", {"project_id": item, **body.model_dump()}, identity)
        return {"items": await asyncio.to_thread(store().media_of, item)}

    @router.delete("/projects/{item}/media/{kind}/{media_id}")
    async def remove_media(
        item: str, kind: str, media_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        row_or_404(identity, item)
        params = {"project_id": item, "kind": kind, "item_id": media_id}
        await run_media("creative.remove_media", params, identity)
        return {"items": await asyncio.to_thread(store().media_of, item)}

    @router.get("/projects/{item}/log")
    async def planning_log(
        item: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """What the writer was asked and what came back: how a person understands a bad plan."""
        row_or_404(identity, item)
        return {"items": await asyncio.to_thread(store().log_of, item)}

    return router
