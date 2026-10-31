# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""What Creative Studio can do, for the action catalogue (ADR-0068, ADR-0090): turn a brief into a plan, change a plan,
and projects as a kind of creation. Nothing is made at this stage: a plan is words."""

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk.actions import (
    CHAT,
    Action,
    ActionContext,
    CallBinding,
    LibraryItem,
    LibraryKind,
    Outcome,
    need_product,
    need_runtime,
)
from wasifyai_platform_sdk.actions.helpers import need_deps

from wasifyai_creative import editor
from wasifyai_creative.document import Brief, EditRefused
from wasifyai_creative.routes import edit_project, title_of
from wasifyai_creative.runtime import (
    KIND,
    PRODUCT_ID,
    Refused,
    add_to_search,
    delete_project,
    manager_for,
    store_for,
)
from wasifyai_creative.store import NotFound

HERE = need_product(PRODUCT_ID)
SAMPLE_ID = "0b7c1f9e-0000-4000-8000-000000000000"
SAMPLE_PROJECT = "1f8d2c3b4a5e4f60a7b8c9d0e1f20314"


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    brief: Brief = Field(description="The song, the idea, who is in it and where.")
    title: str = Field("", max_length=200, description="A name for the project.")


class PlanOut(BaseModel):
    project_id: str
    uri: str
    title: str
    shots: int
    plain_shots: int = Field(
        description="Shots that fell back to plain words, for a person to rewrite."
    )
    seconds: float
    shots_preview: list[dict[str, Any]] = Field(description="The first shots: start, end, shows.")


class EditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=32, max_length=32)
    edits: list[dict[str, Any]] = Field(
        min_length=1, max_length=50,
        description="Changes, in order. {op: 'set_shot', shot_id, shows?, motion?, place?, camera?, "
        "note?, who?}, {op: 'delete_shot', shot_id}, {op: 'add_shot', after, shows?} or "
        "{op: 'move_cut', shot_id, by_beats}. Motion is Hold, Animate or Sing.",
    )  # fmt: skip


class EditOut(BaseModel):
    project_id: str
    revision: int
    shots: int


class ReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=32, max_length=32)
    shot_id: str | None = Field(
        None, max_length=32, description="The shot the person has selected."
    )


class ReadOut(BaseModel):
    project_id: str
    title: str
    brief: str
    actions: list[str]


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=32, max_length=32)


class UndoOut(BaseModel):
    project_id: str
    revision: int


MediaKind = Literal["image", "video", "track", "speech", "lipsync", "model3d", "composition"]


class MediaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=32, max_length=32)
    kind: MediaKind
    item_id: str = Field(min_length=1, max_length=64)
    shot_id: str | None = Field(
        None, max_length=32, description="The shot it is meant for, if any."
    )


class RemoveMediaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=32, max_length=32)
    kind: MediaKind
    item_id: str = Field(min_length=1, max_length=64)


class MediaOut(BaseModel):
    project_id: str
    kind: str
    item_id: str


def _item(row: dict[str, Any]) -> LibraryItem:
    shots = len((row["plan"] or {}).get("shots", []))
    return LibraryItem(
        kind=KIND, id=row["id"], title=row["title"][:120], created_at=row["created_at"],
        detail={"status": row["status"], "shots": shots},
    )  # fmt: skip


async def _plan(p: PlanIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    store, jobs = store_for(deps.state), manager_for(deps)
    row = store.add(
        ctx.actor.tenant_id, ctx.actor.user_id, title_of(p.title, p.brief), p.brief.model_dump()
    )
    try:
        jobs.start(ctx.actor, row["id"])
        try:
            await jobs.wait(ctx.actor, row["id"])
        except asyncio.CancelledError:
            jobs.stop(ctx.actor, row["id"])
            raise
    except Refused as e:
        store.delete(ctx.actor.tenant_id, ctx.actor.user_id, row["id"])
        return Outcome.refused(e.message, e.code)
    done = store.get(ctx.actor.tenant_id, ctx.actor.user_id, row["id"])
    if done["status"] != "planned" or not done["plan"]:
        return Outcome.error(done["error"] or "The plan could not be written.", "failed")
    shots = done["plan"]["shots"]
    plain = sum(1 for s in shots if s["fallback"])
    return Outcome.ok(
        {
            "project_id": done["id"], "uri": f"wasify://creation/{KIND}/{done['id']}",
            "title": done["title"], "shots": len(shots), "plain_shots": plain,
            "seconds": float(done["facts"]["seconds"]),
            "shots_preview": [
                {"start": s["start"], "end": s["end"], "shows": s["shows"]} for s in shots[:6]
            ],
        },
        f'The plan "{done["title"]}" has {len(shots)} shots'
        + (f", {plain} of them in plain words to rewrite." if plain else ".")
        + " Nothing has been made yet. It can be changed in Creative Studio.",
    )  # fmt: skip


async def _edit(p: EditIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    store = store_for(deps.state)
    try:
        row = store.get(ctx.actor.tenant_id, ctx.actor.user_id, p.project_id)
    except NotFound:
        return Outcome.refused("That project is not in the library.", "not_found")
    if manager_for(deps).active(ctx.actor) == p.project_id:
        return Outcome.refused("The plan is being written. Wait for it.", "busy")
    try:
        edit_project(row, store, p.edits, "Changed by the assistant")
    except EditRefused as e:
        return Outcome.refused(str(e), "bad_edit")
    fresh = store.get(ctx.actor.tenant_id, ctx.actor.user_id, p.project_id)
    await add_to_search(deps.state, ctx.actor, fresh)
    shots = len(fresh["plan"]["shots"])
    return Outcome.ok(
        {"project_id": fresh["id"], "revision": fresh["revision"], "shots": shots},
        f"The plan was changed. It has {shots} shots.",
    )


def _row(ctx: ActionContext, project: str) -> dict[str, Any] | None:
    try:
        return store_for(need_deps(ctx).state).get(ctx.actor.tenant_id, ctx.actor.user_id, project)
    except NotFound:
        return None


GONE = "That project is not in the library."


async def _read(p: ReadIn, ctx: ActionContext) -> Outcome:
    row = _row(ctx, p.project_id)
    if row is None:
        return Outcome.refused(GONE, "not_found")
    return Outcome.ok(
        {
            "project_id": row["id"], "title": row["title"],
            "brief": editor.brief(row, p.shot_id), "actions": list(editor.ACTIONS),
        },
        f'This is the project "{row["title"]}".',
    )  # fmt: skip


async def _undo(p: ProjectIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    if _row(ctx, p.project_id) is None:
        return Outcome.refused(GONE, "not_found")
    if manager_for(deps).active(ctx.actor) == p.project_id:
        return Outcome.refused("The plan is being written. Wait for it.", "busy")
    store = store_for(deps.state)
    if store.undo(p.project_id) is None:
        return Outcome.refused("There is nothing to undo.", "nothing_to_undo")
    fresh = store.get(ctx.actor.tenant_id, ctx.actor.user_id, p.project_id)
    await add_to_search(deps.state, ctx.actor, fresh)
    return Outcome.ok(
        {"project_id": fresh["id"], "revision": fresh["revision"]},
        "The last change was taken back.",
    )


async def _add_media(p: MediaIn, ctx: ActionContext) -> Outcome:
    if _row(ctx, p.project_id) is None:
        return Outcome.refused(GONE, "not_found")
    found = ctx.library.get(p.kind)
    if found is None:
        return Outcome.refused(f"This computer does not keep {p.kind} creations.", "unavailable")
    item = await found.get(ctx, p.item_id)
    if item is None:
        return Outcome.refused("That is not in the library.", "not_found")
    store_for(need_deps(ctx).state).add_media(p.project_id, p.kind, p.item_id, p.shot_id)
    return Outcome.ok(
        {"project_id": p.project_id, "kind": p.kind, "item_id": p.item_id},
        f'"{item.title or item.id}" is now part of this project.',
    )


async def _remove_media(p: RemoveMediaIn, ctx: ActionContext) -> Outcome:
    if _row(ctx, p.project_id) is None:
        return Outcome.refused(GONE, "not_found")
    store_for(need_deps(ctx).state).remove_media(p.project_id, p.kind, p.item_id)
    return Outcome.ok(
        {"project_id": p.project_id, "kind": p.kind, "item_id": p.item_id},
        "It is no longer part of this project. It stays in the library.",
    )


async def _list(ctx: ActionContext, limit: int) -> list[LibraryItem]:
    rows = await asyncio.to_thread(
        store_for(need_deps(ctx).state).list_projects,
        ctx.actor.tenant_id,
        ctx.actor.user_id,
        None,
        limit,
    )
    return [_item(r) for r in rows]


async def _get(ctx: ActionContext, item_id: str) -> LibraryItem | None:
    try:
        return _item(
            store_for(need_deps(ctx).state).get(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
        )
    except NotFound:
        return None


async def _delete(ctx: ActionContext, item_id: str) -> bool:
    return await delete_project(need_deps(ctx), ctx.actor, item_id)


async def _rename(ctx: ActionContext, item_id: str, name: str) -> bool:
    deps = need_deps(ctx)
    try:
        row = store_for(deps.state).rename(ctx.actor.tenant_id, ctx.actor.user_id, item_id, name)
    except NotFound:
        return False
    await add_to_search(deps.state, ctx.actor, row)
    return True


def actions() -> list[Action]:
    return [
        Action(
            id="creative.plan",
            title="Plan a music video",
            summary="Turn a song and an idea into an editable plan of shots. Nothing is made yet.",
            description=(
                "Plan a music video of a song in the library: the cuts follow the beats, and every "
                "shot says what is seen, who is in it, where, how the camera moves and whether it "
                "holds or moves. It takes about a minute with an 8B chat model, longer with a larger one. No pictures "
                "or clips are made. Use it when the person wants a music video or a plan for one; "
                "they can then change it in Creative Studio. Returns the project and its first shots."
            ),
            input=PlanIn,
            output=PlanOut,
            examples=({"brief": {"track_id": SAMPLE_ID, "idea": "A woman drives home at dawn"}},),
            effect="make",
            flags=("private",),
            requires=(HERE, CHAT, need_runtime("music_analysis")),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_plan),
            ui="creative",
        ),
        Action(
            id="creative.edit_plan",
            title="Change a plan",
            summary="Change the shots of a plan: words, motion, cuts, or add and remove shots.",
            description=(
                "Change the plan of a project from Creative Studio: what a shot shows, whether it "
                "holds, animates or sings, its place or camera; remove or add a shot; move a cut by "
                "whole beats. Every plan stays whole: the shots still cover the song and only people "
                "of its cast appear. Each call can be undone on the screen."
            ),
            input=EditIn,
            output=EditOut,
            examples=(
                {
                    "project_id": SAMPLE_PROJECT,
                    "edits": [{"op": "set_shot", "shot_id": "s1", "motion": "Animate"}],
                },
            ),
            effect="change",
            requires=(HERE,),
            product=PRODUCT_ID,
            bind=CallBinding(_edit),
            ui="creative",
        ),
        Action(
            id="creative.read_project",
            title="Read a plan",
            summary="Read the plan of a project: its parts and every shot.",
            description=(
                "Read the plan of a project from Creative Studio: its idea, its cast, its parts and "
                "every shot with its times, motion, camera, place and words. The assistant in the "
                "project's Ask tab works from this."
            ),
            input=ReadIn,
            output=ReadOut,
            examples=({"project_id": SAMPLE_PROJECT},),
            effect="read",
            flags=("private",),
            requires=(HERE,),
            product=PRODUCT_ID,
            bind=CallBinding(_read),
            ui="creative",
        ),
        Action(
            id="creative.undo",
            title="Undo a change to a plan",
            summary="Take back the last change to a plan.",
            description="Take back the last change to the plan of a project from Creative Studio.",
            input=ProjectIn,
            output=UndoOut,
            examples=({"project_id": SAMPLE_PROJECT},),
            effect="change",
            requires=(HERE,),
            product=PRODUCT_ID,
            bind=CallBinding(_undo),
            ui="creative",
        ),
        Action(
            id="creative.add_media",
            title="Add to a project",
            summary="Make a creation from the library part of a Creative Studio project.",
            description=(
                "Tag a picture, clip, song, speech, lip sync, 3D model or motion graphic from the "
                "library with a project of Creative Studio, so it shows in that project's media rail. "
                "The creation itself stays in the library and is not copied."
            ),
            input=MediaIn,
            output=MediaOut,
            examples=({"project_id": SAMPLE_PROJECT, "kind": "image", "item_id": SAMPLE_ID},),
            effect="change",
            requires=(HERE,),
            product=PRODUCT_ID,
            bind=CallBinding(_add_media),
            ui="creative",
        ),
        Action(
            id="creative.remove_media",
            title="Take out of a project",
            summary="Take a creation out of a Creative Studio project; it stays in the library.",
            description=(
                "Take a creation out of a project of Creative Studio. It stays in the library."
            ),
            input=RemoveMediaIn,
            output=MediaOut,
            examples=({"project_id": SAMPLE_PROJECT, "kind": "image", "item_id": SAMPLE_ID},),
            effect="change",
            requires=(HERE,),
            product=PRODUCT_ID,
            bind=CallBinding(_remove_media),
            ui="creative",
        ),
    ]


def library_kinds() -> list[LibraryKind]:
    return [LibraryKind(KIND, PRODUCT_ID, "Creative Studio project", _list, _get, _delete, _rename)]


__all__ = ["actions", "library_kinds"]
