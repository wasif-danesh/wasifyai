# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""Creative Studio's API, under /products/wasifyai-creative/: projects, writing a plan, and changing it. Desktop first:
where the product has no folder every route answers 404. Every query is scoped by tenant and user."""

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk import Identity, RouteDeps, parse_ids

from wasifyai_creative import cutting
from wasifyai_creative.cut import CutRefused, apply_cut_edits, default_cut
from wasifyai_creative.document import Brief, EditRefused, apply_edits, problems
from wasifyai_creative.runtime import (
    NotAvailable,
    Refused,
    add_to_search,
    delete_project,
    manager_for,
    store_for,
)
from wasifyai_creative.shots import view as shots_view
from wasifyai_creative.stills import REFERENCE
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


class MakeStills(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["plain", "reference"] = REFERENCE
    redo_out_of_date: bool = False


class RedoShot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["plain", "reference"] = REFERENCE


class MakeMotion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality: Literal["draft", "final"] = "draft"
    start: float | None = Field(None, ge=0, description="Where a draft excerpt starts, in seconds.")
    shot_id: str | None = Field(None, max_length=32, description="Only this shot.")


class CutEdits(BaseModel):
    edits: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    note: str = Field("Changed in the cut", max_length=200)


class KeepVideo(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field("", max_length=120)


class ChooseTake(BaseModel):
    model_config = ConfigDict(extra="forbid")

    take_id: str = Field(min_length=1, max_length=64)


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
        jobs = manager_for(deps)
        found["live"] = jobs.active(identity) == row["id"]
        found["shots"] = shots_view(store(), row)
        if found["shots"]["preview"]:
            del found["shots"]["preview"]["rel"]
        found["shots_live"] = jobs.shots.active(identity) == row["id"]
        return found

    async def shown(row: dict[str, Any], identity: Identity) -> dict[str, Any]:
        """One project with its cut, and links to its preview and its video."""
        found = out(row, identity)
        owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
        preview = found["shots"]["preview"]
        if preview:
            kept = store().preview_of(row["id"])
            preview["url"] = (
                await deps.storage.url_for(owner, kept["rel"]) if deps.storage and kept else None
            )
        found["cut"] = await asyncio.to_thread(cutting.view, store(), row)
        made = found["cut"] and found["cut"]["render"]
        if made:
            rel = made.pop("rel")
            made["url"] = await deps.storage.url_for(owner, rel) if deps.storage else None
        return found

    def row_or_404(identity: Identity, item: str) -> dict[str, Any]:
        try:
            return store().get(identity.tenant_id, identity.user_id, item)
        except NotFound:
            raise HTTPException(404, "project not found") from None

    def refuse(e: Refused) -> HTTPException:
        return HTTPException(409, {"code": e.code, "message": e.message})

    @router.get("/characters")
    async def characters(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """People used in earlier projects, so they can be used again."""
        return {"items": store().characters(identity.tenant_id, identity.user_id)}

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
        store().keep_characters(
            identity.tenant_id, identity.user_id, body.brief.model_dump()["cast"]
        )
        row = store().add(
            identity.tenant_id, identity.user_id, title_of(body.title, body.brief),
            body.brief.model_dump(),
        )  # fmt: skip
        await add_to_search(deps.state, identity, row)
        return await shown(row, identity)

    @router.get("/projects/{item}")
    async def get_project(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        return await shown(row_or_404(identity, item), identity)

    @router.patch("/projects/{item}")
    async def change_project(
        item: str, body: ChangeProject, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        row = row_or_404(identity, item)
        if manager_for(deps).active(identity) == item:
            raise HTTPException(409, {"code": "busy", "message": "The plan is being written."})
        brief = body.brief.model_dump() if body.brief else row["brief"]
        store().keep_characters(identity.tenant_id, identity.user_id, brief.get("cast", []))
        store().set_brief(item, body.title or row["title"], brief)
        fresh = row_or_404(identity, item)
        await add_to_search(deps.state, identity, fresh)
        return await shown(fresh, identity)

    @router.delete("/projects/{item}", status_code=204)
    async def remove_project(
        item: str, with_media: bool = False, identity: Identity = Depends(deps.identity)
    ) -> None:
        row_or_404(identity, item)
        await delete_project(deps, identity, item, with_media=with_media)

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
        return await shown(row_or_404(identity, item), identity)

    @router.post("/projects/{item}/plan/stop")
    async def stop_plan(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        row_or_404(identity, item)
        await manager_for(deps).stop_and_wait(identity, item)
        return await shown(row_or_404(identity, item), identity)

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
        return await shown(fresh, identity)

    @router.post("/projects/{item}/undo")
    async def undo(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        row_or_404(identity, item)
        if store().undo(item) is None:
            raise HTTPException(409, {"code": "nothing", "message": "There is nothing to undo."})
        fresh = row_or_404(identity, item)
        await add_to_search(deps.state, identity, fresh)
        return await shown(fresh, identity)

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
        return await shown(row_or_404(identity, item), identity)

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

    # ---- the shots ------------------------------------------------------------------------------

    @router.get("/projects/{item}/shots/estimate")
    async def estimate(
        item: str,
        mode: Literal["plain", "reference"] = REFERENCE,
        redo_out_of_date: bool = False,
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """Before Start: how many, how long, how much disk, whether it fits."""
        row = row_or_404(identity, item)
        return await manager_for(deps).shots.estimate(row, mode, redo_out_of_date)

    @router.post("/projects/{item}/shots", status_code=202)
    async def make_stills(
        item: str, body: MakeStills, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Make what is missing. Follow it with GET; a stop keeps what is made."""
        row = row_or_404(identity, item)
        try:
            await manager_for(deps).shots.start_stills(
                identity, row, body.mode, body.redo_out_of_date
            )
        except Refused as e:
            raise refuse(e) from None
        return await shown(row_or_404(identity, item), identity)

    @router.post("/projects/{item}/shots/stop")
    async def stop_stills(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        row_or_404(identity, item)
        await manager_for(deps).shots.stop_and_wait(identity, item)
        return await shown(row_or_404(identity, item), identity)

    @router.post("/projects/{item}/shots/{shot}/redo", status_code=202)
    async def redo_shot(
        item: str, shot: str, body: RedoShot, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        row = row_or_404(identity, item)
        try:
            await manager_for(deps).shots.start_redo(identity, row, shot, body.mode)
        except Refused as e:
            raise refuse(e) from None
        return await shown(row_or_404(identity, item), identity)

    @router.put("/projects/{item}/shots/{shot}/chosen")
    async def choose_take(
        item: str, shot: str, body: ChooseTake, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        row = row_or_404(identity, item)
        if not any(
            t["id"] == body.take_id and t["shot_id"] == shot for t in store().takes_of(item)
        ):
            raise HTTPException(404, "that take is not of this shot")
        store().choose_take(item, shot, body.take_id)
        return await shown(row, identity)

    @router.post("/projects/{item}/preview", status_code=202)
    async def make_preview(
        item: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Join the chosen stills over the song. Follow it with GET."""
        row = row_or_404(identity, item)
        try:
            manager_for(deps).shots.start_preview(identity, row)
        except Refused as e:
            raise refuse(e) from None
        return await shown(row_or_404(identity, item), identity)

    @router.get("/projects/{item}/motion/estimate")
    async def motion_estimate(
        item: str,
        quality: Literal["draft", "final"] = "draft",
        start: float | None = None,
        shot_id: str | None = None,
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """Before Start: which shots, how many clips, how long, how much disk, whether it fits."""
        row = row_or_404(identity, item)
        try:
            return await manager_for(deps).shots.motion_estimate(row, quality, start, shot_id)
        except Refused as e:
            raise refuse(e) from None

    @router.post("/projects/{item}/motion", status_code=202)
    async def make_motion(
        item: str, body: MakeMotion, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Animate a draft excerpt, the shots marked Animate (final), or one shot. Stop with /shots/stop."""
        row = row_or_404(identity, item)
        try:
            await manager_for(deps).shots.start_motion(
                identity, row, body.quality, body.start, body.shot_id
            )
        except Refused as e:
            raise refuse(e) from None
        return await shown(row_or_404(identity, item), identity)

    def cut_busy(identity: Identity, item: str) -> None:
        if manager_for(deps).shots.active(identity) == item:
            raise HTTPException(
                409,
                {
                    "code": "busy",
                    "message": "The video is being made. Wait for it, or stop it first.",
                },
            )

    @router.post("/projects/{item}/cut/edits")
    async def edit_cut(
        item: str, body: CutEdits, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Change the cut: move, lengthen, split, fade, remove or put in a piece, and the captions. `reset` starts it again from the plan."""
        row = row_or_404(identity, item)
        cut_busy(identity, item)
        found = cutting.current(store(), row)
        if found is None:
            raise HTTPException(409, {"code": "no_plan", "message": "There is no plan yet."})
        if any(e.get("op") == "reset" for e in body.edits):
            new = default_cut(row["plan"], row["facts"])
        else:
            try:
                new = apply_cut_edits(
                    found["cut"],
                    body.edits,
                    row["facts"].get("beats", []),
                    cutting.song_s(row),
                    cutting.song_lines(row),
                )
            except (CutRefused, KeyError, TypeError, ValueError) as e:
                message = (
                    str(e) if isinstance(e, CutRefused) else "That change is missing something."
                )
                raise HTTPException(422, {"code": "bad_edit", "message": message}) from None
        if new == found["cut"]:
            raise HTTPException(
                422,
                {
                    "code": "bad_edit",
                    "message": "The cut already says that, so there is nothing to change.",
                },
            )
        store().save_cut(item, new, body.note)
        await add_to_search(deps.state, identity, row)
        return await shown(row, identity)

    @router.post("/projects/{item}/cut/undo")
    async def undo_cut(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        row = row_or_404(identity, item)
        cut_busy(identity, item)
        if store().step_cut(item, -1) is None:
            raise HTTPException(409, {"code": "nothing", "message": "There is nothing to undo."})
        return await shown(row, identity)

    @router.post("/projects/{item}/cut/redo")
    async def redo_cut(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        row = row_or_404(identity, item)
        cut_busy(identity, item)
        if store().step_cut(item, 1) is None:
            raise HTTPException(409, {"code": "nothing", "message": "There is nothing to redo."})
        return await shown(row, identity)

    @router.post("/projects/{item}/cut/video", status_code=202)
    async def make_video(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """Make the cut's video at full size, with the song and the captions. Follow it with GET."""
        row = row_or_404(identity, item)
        try:
            manager_for(deps).shots.start_cut(identity, row, None)
        except Refused as e:
            raise refuse(e) from None
        return await shown(row_or_404(identity, item), identity)

    @router.post("/projects/{item}/cut/keep", status_code=202)
    async def keep_video(
        item: str, body: KeepVideo, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Make the video if it is out of date, then keep it in Your videos: a new video every time."""
        row = row_or_404(identity, item)
        try:
            manager_for(deps).shots.start_cut(identity, row, body.title or row["title"])
        except Refused as e:
            raise refuse(e) from None
        return await shown(row_or_404(identity, item), identity)

    @router.get("/projects/{item}/log")
    async def planning_log(
        item: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """What the writer was asked and what came back: how a person understands a bad plan."""
        row_or_404(identity, item)
        return {"items": await asyncio.to_thread(store().log_of, item)}

    return router
