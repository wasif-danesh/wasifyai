# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""What Creative Studio can do, for the action catalogue (ADR-0068, ADR-0090): turn a brief into a plan, change a plan,
and projects as a kind of creation. Nothing is made at this stage: a plan is words."""

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from wasifyai_platform_sdk.actions import (
    CHAT,
    Action,
    ActionContext,
    CallBinding,
    LibraryItem,
    LibraryKind,
    Outcome,
    need_product,
)
from wasifyai_platform_sdk.actions.helpers import need_deps

from wasifyai_creative import cutting, editor, stills
from wasifyai_creative.cut import CutRefused, apply_cut_edits
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
from wasifyai_creative.shots import view
from wasifyai_creative.store import NotFound

HERE = need_product(PRODUCT_ID)
SAMPLE_ID = "0b7c1f9e-0000-4000-8000-000000000000"
SAMPLE_PROJECT = "1f8d2c3b4a5e4f60a7b8c9d0e1f20314"


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    brief: Brief = Field(description="The song, the idea, who is in it and where.")
    title: str = Field("", max_length=200, description="A name for the project.")

    @field_validator("brief", mode="before")
    @classmethod
    def _idea(cls, v: Any) -> Any:
        # a model often gives the brief as a line of words: that line is its idea
        return {"idea": v} if isinstance(v, str) else v


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


class MakeShotsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=32, max_length=32)
    mode: Literal["plain", "reference"] = Field(
        "reference",
        description="reference keeps faces steadier and takes about twice as long as plain.",
    )
    redo_out_of_date: bool = Field(
        False, description="Also make again the stills whose shot changed."
    )


class RedoShotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=32, max_length=32)
    shot_id: str = Field(min_length=1, max_length=32)
    mode: Literal["plain", "reference"] = "reference"


class ChooseTakeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=32, max_length=32)
    shot_id: str = Field(min_length=1, max_length=32)
    take_id: str = Field(min_length=1, max_length=64)


class AnimateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=32, max_length=32)
    quality: Literal["draft", "final"] = Field(
        "draft",
        description=(
            "draft: about 30 seconds of the song (its loudest part unless start says where), quick "
            "and soft. final: the shots the plan marks Animate, sharp and about four times as long."
        ),
    )
    start: float | None = Field(None, ge=0, description="Draft only: where the 30 seconds start.")
    shot_id: str | None = Field(
        None, min_length=1, max_length=32, description="Only this shot, made again."
    )


class AnimateOut(BaseModel):
    project_id: str
    clips: int = Field(description="Shots of the plan that now have a clip.")


class ShotsOut(BaseModel):
    project_id: str
    missing: int = Field(description="Shots with no still yet.")
    out_of_date: int = Field(description="Shots whose still was made before the shot changed.")


class EditCutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=32, max_length=32)
    edits: list[dict[str, Any]] = Field(
        min_length=1, max_length=50,
        description="Changes to the cut, in order. Pieces: {op: 'move', item_id, to}, {op: 'length', item_id, "
        "by_beats}, {op: 'split', item_id}, {op: 'fade', item_id, fade}, {op: 'remove', item_id}. Captions: "
        "{op: 'caption', caption_id, text?, by_beats?}, {op: 'add_caption', kind: 'line'|'title'|'lower', text, "
        "start, end}, {op: 'remove_caption', caption_id}, {op: 'captions', on}, {op: 'song_lines'} (the song's words where they were sung, again).",
    )  # fmt: skip


class CutOut(BaseModel):
    project_id: str
    pieces: int
    captions: int
    black_s: float = Field(description="Seconds at the end with no picture.")
    empty: int = Field(description="Pieces with nothing to show yet.")


class ExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=32, max_length=32)
    title: str = Field(
        "", max_length=120, description="What the video is called; left out, the project's name."
    )


class ExportOut(BaseModel):
    project_id: str
    video_id: str
    uri: str


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
    store = store_for(need_deps(ctx).state)
    store.add_media(p.project_id, p.kind, p.item_id, p.shot_id)
    row = _row(ctx, p.project_id)
    shot = next(
        (s for s in ((row or {}).get("plan") or {}).get("shots", []) if s["id"] == p.shot_id), None
    )
    known = any(
        t["kind"] == p.kind and t["item_id"] == p.item_id for t in store.takes_of(p.project_id)
    )
    if row and shot and p.kind in ("image", "video", "lipsync") and not known:
        # for a shot it is a take; it becomes the chosen one only if the shot has none, by the person's click
        store.add_take(
            p.project_id, shot["id"], p.kind, p.item_id, stills.inputs_of(shot, row["brief"]),
            item.title or "", "added", None, row["revision"], choose=False,
        )  # fmt: skip
    return Outcome.ok(
        {"project_id": p.project_id, "kind": p.kind, "item_id": p.item_id},
        f'"{item.title or item.id}" is now part of this project.',
    )


async def _remove_media(p: RemoveMediaIn, ctx: ActionContext) -> Outcome:
    if _row(ctx, p.project_id) is None:
        return Outcome.refused(GONE, "not_found")
    store = store_for(need_deps(ctx).state)
    store.remove_media(p.project_id, p.kind, p.item_id)
    store.remove_takes_of_media(p.project_id, p.kind, p.item_id)
    return Outcome.ok(
        {"project_id": p.project_id, "kind": p.kind, "item_id": p.item_id},
        "It is no longer part of this project. It stays in the library.",
    )


async def _make_shots(p: MakeShotsIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    row = _row(ctx, p.project_id)
    if row is None:
        return Outcome.refused(GONE, "not_found")
    jobs = manager_for(deps).shots
    try:
        await jobs.start_stills(ctx.actor, row, p.mode, p.redo_out_of_date)
        try:
            await jobs.wait(ctx.actor, p.project_id)
        except asyncio.CancelledError:
            await jobs.stop_and_wait(ctx.actor, p.project_id)
            raise
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    return _ran(ctx, p.project_id)


def _ran(ctx: ActionContext, project: str) -> Outcome:
    row = _row(ctx, project)
    if row is None:
        return Outcome.refused(GONE, "not_found")
    now = view(store_for(need_deps(ctx).state), row)
    run = now["run"] or {}
    if run.get("status") == "failed":
        return Outcome.error(
            run.get("error") or "It stopped on a problem. What was made is kept.", "failed"
        )
    return Outcome.ok(
        {
            "project_id": project,
            "missing": len(now["missing"]),
            "out_of_date": len(now["out_of_date"]),
        },
        "Done. The pictures are in Creative Studio and your Library."
        + (f" {len(now['missing'])} shots still have no still." if now["missing"] else ""),
    )


async def _redo_shot(p: RedoShotIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    row = _row(ctx, p.project_id)
    if row is None:
        return Outcome.refused(GONE, "not_found")
    jobs = manager_for(deps).shots
    try:
        await jobs.start_redo(ctx.actor, row, p.shot_id, p.mode)
        await jobs.wait(ctx.actor, p.project_id)
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    return _ran(ctx, p.project_id)


async def _animate(p: AnimateIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    row = _row(ctx, p.project_id)
    if row is None:
        return Outcome.refused(GONE, "not_found")
    jobs = manager_for(deps).shots
    try:
        await jobs.start_motion(ctx.actor, row, p.quality, p.start, p.shot_id)
        try:
            await jobs.wait(ctx.actor, p.project_id)
        except asyncio.CancelledError:
            await jobs.stop_and_wait(ctx.actor, p.project_id)
            raise
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    store = store_for(deps.state)
    run = store.run_of(p.project_id) or {}
    if run.get("status") == "failed":
        return Outcome.error(
            run.get("error") or "It stopped on a problem. What was made is kept.", "failed"
        )
    clips = len({t["shot_id"] for t in store.takes_of(p.project_id) if t["kind"] == "video"})
    return Outcome.ok(
        {"project_id": p.project_id, "clips": clips},
        "Done. The clips are used for their shots in Creative Studio and kept in Your videos.",
    )


async def _choose_take(p: ChooseTakeIn, ctx: ActionContext) -> Outcome:
    store = store_for(need_deps(ctx).state)
    if _row(ctx, p.project_id) is None:
        return Outcome.refused(GONE, "not_found")
    if not any(
        t["id"] == p.take_id and t["shot_id"] == p.shot_id for t in store.takes_of(p.project_id)
    ):
        return Outcome.refused("That take is not of this shot.", "not_found")
    store.choose_take(p.project_id, p.shot_id, p.take_id)
    return Outcome.ok(
        {"project_id": p.project_id, "missing": 0, "out_of_date": 0},
        "That take is now used for the shot.",
    )


async def _preview(p: ProjectIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    row = _row(ctx, p.project_id)
    if row is None:
        return Outcome.refused(GONE, "not_found")
    jobs = manager_for(deps).shots
    try:
        jobs.start_preview(ctx.actor, row)
        await jobs.wait(ctx.actor, p.project_id)
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    return _ran(ctx, p.project_id)


def _cut_out(ctx: ActionContext, row: dict[str, Any]) -> dict[str, Any]:
    now = cutting.view(store_for(need_deps(ctx).state), row) or {}
    summary = now.get("summary", {})
    return {
        "project_id": row["id"], "pieces": len(now.get("items", [])), "captions": len(now.get("captions", [])),
        "black_s": summary.get("black_tail", 0.0), "empty": summary.get("empty", 0),
    }  # fmt: skip


async def _edit_cut(p: EditCutIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    store = store_for(deps.state)
    row = _row(ctx, p.project_id)
    if row is None:
        return Outcome.refused(GONE, "not_found")
    if manager_for(deps).shots.active(ctx.actor) == p.project_id:
        return Outcome.refused("The video is being made. Wait for it.", "busy")
    found = cutting.current(store, row)
    if found is None:
        return Outcome.refused("There is no plan yet, so there is no cut.", "no_plan")
    try:
        new = apply_cut_edits(
            found["cut"],
            p.edits,
            row["facts"].get("beats", []),
            cutting.song_s(row),
            cutting.song_lines(row),
        )
    except CutRefused as e:
        return Outcome.refused(str(e), "bad_edit")
    except (KeyError, TypeError, ValueError):
        return Outcome.refused("That change is missing something.", "bad_edit")
    if new == found["cut"]:
        return Outcome.refused(
            "The cut already says that, so there is nothing to change.", "bad_edit"
        )
    store.save_cut(row["id"], new, "Changed by the assistant")
    await add_to_search(deps.state, ctx.actor, row)
    out = _cut_out(ctx, row)
    return Outcome.ok(
        out, f"The cut was changed. It has {out['pieces']} pieces and {out['captions']} captions."
    )


async def _run_cut(ctx: ActionContext, row: dict[str, Any], keep: str | None) -> Outcome | None:
    jobs = manager_for(need_deps(ctx)).shots
    try:
        jobs.start_cut(ctx.actor, row, keep)
        await jobs.wait(ctx.actor, row["id"])
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    run = store_for(need_deps(ctx).state).run_of(row["id"]) or {}
    if run.get("status") == "failed":
        return Outcome.error(run.get("error") or "The video could not be made.", "failed")
    return None


async def _cut(p: ProjectIn, ctx: ActionContext) -> Outcome:
    row = _row(ctx, p.project_id)
    if row is None:
        return Outcome.refused(GONE, "not_found")
    wrong = await _run_cut(ctx, row, None)
    if wrong:
        return wrong
    out = _cut_out(ctx, row)
    return Outcome.ok(
        out,
        "The video is made. Watch it in Creative Studio's Cut step."
        + (f" {out['empty']} pieces have no picture yet and are black." if out["empty"] else ""),
    )


async def _export(p: ExportIn, ctx: ActionContext) -> Outcome:
    row = _row(ctx, p.project_id)
    if row is None:
        return Outcome.refused(GONE, "not_found")
    title = p.title.strip() or row["title"]
    wrong = await _run_cut(ctx, row, title)
    if wrong:
        return wrong
    kept = store_for(need_deps(ctx).state).exports_of(row["id"])
    if not kept:
        return Outcome.error("The video could not be kept.", "failed")
    video = kept[0]["video_id"]
    return Outcome.ok(
        {"project_id": row["id"], "video_id": video, "uri": f"wasify://creation/video/{video}"},
        f'"{title}" is saved to Your videos as a new video.',
    )


async def _read_video(ctx: ActionContext, item_id: str) -> bytes | None:
    """The project's latest video, for the video product to keep (creative.export)."""
    store = store_for(need_deps(ctx).state)
    try:
        store.get(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    except NotFound:
        return None
    return await cutting.read_render(need_deps(ctx), store, ctx.actor, item_id)


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
                "holds, moves or sings. It takes about a minute with an 8B chat model, longer with a larger one. No pictures "
                "or clips are made. Use it when the person wants a music video or a plan for one; "
                "they can then change it in Creative Studio. Returns the project and its first shots. "
                "For a video of a story, set brief.skill to story and brief.story to its text: a "
                "narrator reads it (brief.narrator, a saved voice) and words in quotes are said by the "
                "person named in the same sentence (their voice); reading it first takes a few minutes."
            ),
            input=PlanIn,
            output=PlanOut,
            examples=({"brief": {"track_id": SAMPLE_ID, "idea": "A woman drives home at dawn"}},),
            effect="make",
            flags=("private",),
            requires=(
                HERE,
                CHAT,
            ),  # a song needs its analysis, which music.analyse asks for; a story does not
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
            id="creative.make_shots",
            title="Make the stills of a plan",
            summary="Make a picture for every shot of a plan that has none. Costly: many pictures.",
            description=(
                "Make the still of every shot of a Creative Studio plan that has none, as one job. "
                "With reference, which is the default, people get two pictures first so every shot "
                "starts from the same face; a 3-minute song takes about 30 minutes, or about 15 with "
                "plain. Each picture is saved as it is made, and stopping keeps them. Use it when the "
                "person wants to see their plan as pictures."
            ),
            input=MakeShotsIn,
            output=ShotsOut,
            examples=({"project_id": SAMPLE_PROJECT},),
            effect="make",
            flags=("private", "costly"),
            requires=(HERE,),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_make_shots),
            ui="creative",
        ),
        Action(
            id="creative.redo_shot",
            title="Make a shot's still again",
            summary="Make another take of one shot's still; the old take is kept.",
            description=(
                "Make another still of one shot of a Creative Studio plan. The old one stays as a "
                "take, and the new one is used. It takes under a minute."
            ),
            input=RedoShotIn,
            output=ShotsOut,
            examples=({"project_id": SAMPLE_PROJECT, "shot_id": "s1"},),
            effect="make",
            flags=("private", "costly"),
            requires=(HERE,),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_redo_shot),
            ui="creative",
        ),
        Action(
            id="creative.animate",
            title="Animate a music video's shots",
            summary="Set shots moving: a quick 30 second draft, or the Animate shots made well.",
            description=(
                "Turn the stills of a Creative Studio plan into short clips. draft animates about 30 "
                "seconds of the song quickly and softly (about 50 seconds a shot), to see the motion "
                "first; final animates the shots the plan marks Animate, sharp (about 3 minutes a "
                "shot). With shot_id, only that shot. Each clip is saved as it is made, used for its "
                "shot and kept in Your videos; stopping keeps them."
            ),
            input=AnimateIn,
            output=AnimateOut,
            examples=(
                {"project_id": SAMPLE_PROJECT},
                {"project_id": SAMPLE_PROJECT, "quality": "final"},
            ),
            effect="make",
            flags=("private", "costly"),
            requires=(HERE,),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_animate),
            ui="creative",
        ),
        Action(
            id="creative.choose_take",
            title="Choose a shot's take",
            summary="Choose which take of a shot is used.",
            description="Choose which still or clip of a shot of Creative Studio is used in the preview.",
            input=ChooseTakeIn,
            output=ShotsOut,
            examples=({"project_id": SAMPLE_PROJECT, "shot_id": "s1", "take_id": SAMPLE_ID},),
            effect="change",
            requires=(HERE,),
            product=PRODUCT_ID,
            bind=CallBinding(_choose_take),
            ui="creative",
        ),
        Action(
            id="creative.preview",
            title="Preview a music video",
            summary="Join a plan's stills with camera moves, cut on the beats, over the song.",
            description=(
                "Join the chosen stills of a Creative Studio plan into a video over the song, with a "
                "camera move on each and cuts on the plan's times. It takes under a minute. A shot "
                "with no still is black. It is a draft to watch, not the finished video."
            ),
            input=ProjectIn,
            output=ShotsOut,
            examples=({"project_id": SAMPLE_PROJECT},),
            effect="make",
            flags=("private",),
            requires=(HERE,),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_preview),
            ui="creative",
        ),
        Action(
            id="creative.edit_cut",
            title="Change a music video's cut",
            summary="Move, lengthen, split or fade a piece of the cut, or change its captions.",
            description=(
                "Change the cut of a Creative Studio project: move a piece, make it longer or shorter by "
                "beats, split it, fade into it or take it out, and change, move, add or take out a "
                "caption or a title. Changing the plan's shots is creative.edit_plan; this is only the cut."
            ),
            input=EditCutIn,
            output=CutOut,
            examples=(
                {
                    "project_id": SAMPLE_PROJECT,
                    "edits": [{"op": "length", "item_id": "c3", "by_beats": 2}],
                },
            ),
            effect="change",
            requires=(HERE,),
            product=PRODUCT_ID,
            bind=CallBinding(_edit_cut),
            ui="creative",
        ),
        Action(
            id="creative.cut",
            title="Make a music video",
            summary="Make the finished video of a cut: its pictures, the song and the captions.",
            description=(
                "Make the video of a Creative Studio project's cut at full size, with the song and the "
                "captions. It takes about a minute for a 3-minute song of stills. It is kept with the project; "
                "creative.export keeps it in Your videos."
            ),
            input=ProjectIn,
            output=CutOut,
            examples=({"project_id": SAMPLE_PROJECT},),
            effect="make",
            flags=("private",),
            requires=(HERE,),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_cut),
            ui="creative",
        ),
        Action(
            id="creative.export",
            title="Keep a music video in Your videos",
            summary="Save a project's finished video to Your videos as a new video.",
            description=(
                "Save the finished video of a Creative Studio project to Your videos, making it first "
                "if the cut has changed. Every time is a new video; the old ones stay."
            ),
            input=ExportIn,
            output=ExportOut,
            examples=({"project_id": SAMPLE_PROJECT, "title": "Dawn drive"},),
            effect="make",
            flags=("private",),
            requires=(HERE,),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_export),
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
    return [
        LibraryKind(
            KIND,
            PRODUCT_ID,
            "Creative Studio project",
            _list,
            _get,
            _delete,
            _rename,
            read=_read_video,
        )
    ]


__all__ = ["actions", "library_kinds"]
