"""What Motion graphics can do, for the action catalogue (ADR-0068, ADR-0079): write a video from a
template, check it, make it, change it, and the compositions as a kind of creation in the library.

`motion.make` is the plain-words front door (ADR-0079): the assistant or an agent maps "a lower
third for Maya Chen, Head of Design" onto a template and its fields, and the words go in verbatim;
no model retypes them, and the exact-text check refuses a page that does not say them.

`motion.write_scenes` and the `motion.*_scene` actions work on a project of scenes (ADR-0096). The
editor's assistant uses them, so one change is one version that `motion.undo` brings back."""

import asyncio
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from wasifyai_platform_sdk.actions import (
    Action,
    ActionContext,
    ActionRefused,
    CallBinding,
    LibraryItem,
    LibraryKind,
    Outcome,
    need_product,
    need_runtime,
)
from wasifyai_platform_sdk.actions.helpers import need_deps

from wasifyai_video.builder import editor, scenes, templates
from wasifyai_video.builder.routes import delete_composition
from wasifyai_video.builder.runtime import (
    NotFound,
    Refused,
    engine_for,
    index_composition,
    manager_for,
    store_for,
)
from wasifyai_video.builder.store import NothingToUndo

PRODUCT_ID = "wasifyai-video"
BUILDER = need_runtime("video-builder")
SAMPLE_ID = "0b7c1f9e000040008000000000000000"
SAMPLE_SCENE = "1f2e3d4c"
TemplateId = Literal["title", "quote", "chart", "lower_third", "captions"]
Format = Literal["mp4", "webm", "mov"]
Shape = Literal["landscape", "portrait", "square"]
Font = Literal["sans", "serif"]
Transition = Literal["none", "fade", "slide"]


def _fields_help() -> str:
    """For a model: each template, its fields and its limits, from the templates themselves."""
    parts = []
    for t in templates.TEMPLATES.values():
        fields = []
        for f in t.fields:
            if f.kind in ("text", "longtext"):
                need = ", required" if f.required else ""
                what = f"{f.id} (text, up to {f.max_chars} characters{need})"
            elif f.kind == "lines":
                what = f"{f.id} (one caption per line, up to {f.maximum} lines)"
            elif f.kind == "rows":
                what = f"{f.id} (lines like 'Sales, 120', up to {f.maximum})"
            elif f.kind == "choice":
                what = f"{f.id} ({'/'.join(v for v, _ in f.choices)})"
            else:
                what = f"{f.id} (seconds, {f.minimum} to {f.maximum})"
            fields.append(what)
        parts.append(f"{t.id}: {t.description} Fields: {'; '.join(fields)}.")
    return " ".join(parts)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateIn(Strict):
    template: TemplateId = Field("title", description="Which template.")
    fields: dict[str, Any] = Field(
        description="The words and settings of the template, exactly as they should be shown."
    )


class CompositionOut(BaseModel):
    composition_id: str
    product_id: str
    uri: str
    title: str
    template: str
    seconds: int


class CompositionIn(Strict):
    composition_id: str = Field(
        min_length=32, max_length=32, pattern="^[0-9a-f]{32}$",
        description="The video project, as returned when it was created.",
    )  # fmt: skip


class RenderIn(CompositionIn):
    format: Format = Field(
        "mp4",
        description="mp4, or webm or mov (transparent) for a lower third or captions.",
    )


class Finding(BaseModel):
    file: str
    line: int
    code: str
    message: str


class LintOut(BaseModel):
    composition_id: str
    ok: bool
    findings: list[Finding]


class RenderOut(BaseModel):
    composition_id: str
    render_id: str
    video_id: str
    product_id: str
    uri: str
    seconds: int
    format: str
    checked: bool


class MakeIn(Strict):
    template: TemplateId = Field(description="Which template.")
    fields: dict[str, Any] = Field(
        description="The words and settings of the template, exactly as they should be shown."
    )
    format: Format = Field("mp4", description="mp4, or webm or mov (transparent) for overlays.")
    render: bool = Field(True, description="False to write the project without making the video.")


class ReviseIn(CompositionIn):
    fields: dict[str, Any] = Field(description="Only the fields to change.")
    format: Format = Field("mp4", description="mp4, or webm or mov (transparent) for overlays.")
    render: bool = Field(True, description="False to change the project without making the video.")


class MotionOut(BaseModel):
    composition_id: str
    product_id: str
    uri: str
    title: str
    template: str
    seconds: int
    video_id: str | None
    video_uri: str | None
    checked: bool


def _into_fields(known: set[str], raw: Any) -> Any:
    """A scene's words and settings, wherever a small model put them: its fields beside `fields`,
    and what belongs to the scene inside it. Anything that is neither is still refused by name when
    the scene is checked."""
    if not isinstance(raw, dict):
        return raw
    inside = raw.get("fields")
    fields: dict[str, Any] = inside if isinstance(inside, dict) else {}
    kept = {k: v for k, v in raw.items() if k in known and k != "fields"}
    beside = {k: v for k, v in raw.items() if k not in known}
    merged = {**beside, **fields}
    # the shape and the letters are the whole project's: a scene that names them changes nothing
    out = {k: v for k, v in merged.items() if k not in known and k not in ("shape", "font")}
    return {**{k: v for k, v in merged.items() if k in known}, **kept, "fields": out}


class SceneIn(Strict):
    kind: TemplateId = Field(description="What the scene is: one of the five templates.")
    name: str = Field("", max_length=60, description="A short name for the scene.")
    caption: str = Field("", max_length=140, description="Words along the bottom of the scene.")
    transition: Transition = Field("fade", description="How the scene starts.")
    fields: dict[str, Any] = Field(
        description=(
            "The template's words and settings, exactly as they should be shown, without shape and "
            "font (those are set for the whole project). `seconds` is 5 if not given."
        )
    )

    @model_validator(mode="before")
    @classmethod
    def _gather(cls, raw: Any) -> Any:
        return _into_fields(set(cls.model_fields), raw)


class WriteScenesIn(Strict):
    name: str = Field("", max_length=80, description="The project's name.")
    shape: Shape = Field("landscape", description="The shape of the whole video.")
    font: Font = Field("sans", description="The letters of the whole video.")
    scenes: list[SceneIn] = Field(
        min_length=1, max_length=templates.MAX_SCENES, description="The scenes, in order."
    )


class AddSceneIn(CompositionIn, SceneIn):
    position: int | None = Field(
        None, ge=0, description="Where it goes, from 0. At the end if not given."
    )


class SceneRefIn(CompositionIn):
    scene_id: str = Field(
        min_length=8, max_length=8, pattern="^[0-9a-f]{8}$",
        description="The scene, as listed by the project.",
    )  # fmt: skip


class ChangeSceneIn(SceneRefIn):
    fields: dict[str, Any] = Field(
        default_factory=dict, description="Only the fields of this scene that change."
    )
    name: str | None = Field(None, max_length=60, description="A new name for the scene.")
    caption: str | None = Field(None, max_length=140, description="Words along the bottom.")
    transition: Transition | None = Field(None, description="How the scene starts.")

    @model_validator(mode="before")
    @classmethod
    def _gather(cls, raw: Any) -> Any:
        return _into_fields(set(cls.model_fields), raw)


class MoveSceneIn(SceneRefIn):
    position: int = Field(ge=0, description="Where it goes, from 0.")


class SetProjectIn(CompositionIn):
    name: str | None = Field(None, max_length=80, description="The project's name.")
    shape: Shape | None = Field(None, description="The shape of the whole video.")
    font: Font | None = Field(None, description="The letters of the whole video.")
    scenes: list[SceneIn] | None = Field(
        None, max_length=templates.MAX_SCENES,
        description="All the scenes, in order, replacing the ones there now.",
    )  # fmt: skip


class ReadProjectIn(CompositionIn):
    scene_id: str | None = Field(
        None, pattern="^[0-9a-f]{8}$", description="The scene the person is on, if any."
    )


class ReadProjectOut(BaseModel):
    composition_id: str
    title: str
    brief: str
    actions: list[str]


class SceneOut(BaseModel):
    id: str
    name: str
    kind: str
    seconds: int


class ScenesOut(BaseModel):
    composition_id: str
    product_id: str
    uri: str
    title: str
    shape: str
    seconds: int
    scenes: list[SceneOut]
    scene_id: str | None = None


def _store(ctx: ActionContext):  # noqa: ANN202
    return store_for(need_deps(ctx).state)


def _found(ctx: ActionContext, cid: str) -> dict[str, Any]:
    try:
        return _store(ctx).get_composition(ctx.actor.tenant_id, ctx.actor.user_id, cid)
    except NotFound:
        raise ActionRefused("not_found", "That video project does not exist.") from None


async def _check_composition(p: CompositionIn, ctx: ActionContext) -> None:
    _found(ctx, p.composition_id)


def _created(found: dict[str, Any]) -> dict[str, Any]:
    return {
        "composition_id": found["id"], "product_id": PRODUCT_ID,
        "uri": f"wasify://creation/composition/{found['id']}", "title": found["title"],
        "template": found["template"], "seconds": int(found["slots"]["seconds"]),
    }  # fmt: skip


async def _create_project(ctx: ActionContext, template: str, fields: dict[str, Any]):  # noqa: ANN202
    deps = need_deps(ctx)
    slots = templates.normalize_slots(template, fields)
    found = await asyncio.to_thread(
        store_for(deps.state).add_composition, ctx.actor.tenant_id, ctx.actor.user_id,
        title=templates.title_of(template, slots), template=template, slots=slots,
    )  # fmt: skip
    await index_composition(deps, ctx.actor, found)
    return found


async def _create(p: CreateIn, ctx: ActionContext) -> Outcome:
    try:
        found = await _create_project(ctx, p.template, p.fields)
    except templates.SlotError as e:
        return Outcome.refused(str(e), "bad_slot")
    return Outcome.ok(
        _created(found),
        f'The video project "{found["title"]}" was created ({found["slots"]["seconds"]} seconds). '
        "Nothing has been made yet: use video_builder.render to make the video.",
    )


async def _lint(p: CompositionIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    found = _found(ctx, p.composition_id)
    with tempfile.TemporaryDirectory(prefix="lint-") as tmp:
        (Path(tmp) / "index.html").write_text(
            templates.render_html(found["template"], found["slots"])
        )
        findings = await asyncio.to_thread(engine_for(deps.state).lint, Path(tmp))
    words = (
        "The video reaches nothing outside its own folder."
        if not findings
        else f"{len(findings)} thing(s) in the video reach outside its own folder."
    )
    return Outcome.ok(
        {"composition_id": found["id"], "ok": not findings, "findings": findings}, words
    )


async def _made(
    ctx: ActionContext, cid: str, fmt: str
) -> tuple[Outcome | None, dict[str, Any] | None]:
    """Make the video of a project: (what to return if it did not work, the finished render)."""
    deps = need_deps(ctx)
    manager = manager_for(deps)
    try:
        row = await manager.start(ctx.actor, cid, fmt)
    except Refused as e:
        return Outcome.refused(e.message, e.code), None
    try:
        await manager.wait(row["id"])
    except asyncio.CancelledError:
        await manager.cancel(ctx.actor, row["id"])
        raise
    done = store_for(deps.state).get_render(ctx.actor.tenant_id, ctx.actor.user_id, row["id"])
    if done["status"] != "done" or not done["video_id"]:
        code = "check_failed" if done["check"] and not done["check"]["ok"] else "render_failed"
        return Outcome.error(done["error"] or "The video could not be made.", code), None
    return None, done


async def _render(p: RenderIn, ctx: ActionContext) -> Outcome:
    failed, done = await _made(ctx, p.composition_id, p.format)
    if failed is not None or done is None:
        return failed or Outcome.error("The video could not be made.", "render_failed")
    found = _found(ctx, p.composition_id)
    seconds = int(found["slots"]["seconds"])
    return Outcome.ok(
        {
            "composition_id": found["id"], "render_id": done["id"], "video_id": done["video_id"],
            "product_id": PRODUCT_ID, "uri": f"wasify://creation/video/{done['video_id']}",
            "seconds": seconds, "format": p.format, "checked": bool(done["check"]["ok"]),
        },
        f'The video "{found["title"]}" was made ({seconds} seconds, {p.format}), checked '
        "word for word, and saved to the library.",
    )  # fmt: skip


def _motion(found: dict[str, Any], done: dict[str, Any] | None) -> dict[str, Any]:
    video = done["video_id"] if done else None
    return {
        **_created(found), "video_id": video,
        "video_uri": f"wasify://creation/video/{video}" if video else None,
        "checked": bool(done and done["check"] and done["check"]["ok"]),
    }  # fmt: skip


async def _make(p: MakeIn, ctx: ActionContext) -> Outcome:
    try:
        found = await _create_project(ctx, p.template, p.fields)
    except templates.SlotError as e:
        return Outcome.refused(str(e), "bad_slot")
    if not p.render:
        return Outcome.ok(_motion(found, None), f'The project "{found["title"]}" was written.')
    failed, done = await _made(ctx, found["id"], p.format)
    if failed is not None or done is None:
        text = (failed.text if failed else "The video could not be made.") + (
            " The project was kept; change the words and try again."
        )
        return Outcome.error(text, failed.code if failed else "render_failed")
    return Outcome.ok(
        _motion(found, done),
        f'"{found["title"]}" was made with the {templates.get(found["template"]).title.lower()} '
        f"template ({found['slots']['seconds']} seconds, {p.format}); the words on the screen were "
        "checked against what was given and it is saved to the library.",
    )


async def _revise(p: ReviseIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    current = _found(ctx, p.composition_id)
    try:
        slots = templates.normalize_slots(current["template"], {**current["slots"], **p.fields})
    except templates.SlotError as e:
        return Outcome.refused(str(e), "bad_slot")
    found = await asyncio.to_thread(
        store_for(deps.state).update_composition, ctx.actor.tenant_id, ctx.actor.user_id,
        current["id"], title=templates.title_of(current["template"], slots), slots=slots,
    )  # fmt: skip
    await index_composition(deps, ctx.actor, found)
    if not p.render:
        return Outcome.ok(_motion(found, None), f'The project "{found["title"]}" was changed.')
    failed, done = await _made(ctx, found["id"], p.format)
    if failed is not None or done is None:
        text = (failed.text if failed else "The video could not be made.") + (
            " The change was kept; you can undo it on the Motion graphics screen."
        )
        return Outcome.error(text, failed.code if failed else "render_failed")
    return Outcome.ok(
        _motion(found, done),
        f'"{found["title"]}" was changed and made again ({p.format}); the words on the screen were '
        "checked against what was given.",
    )


# ---- a project of scenes (ADR-0096) --------------------------------------------------------------


def _scenes_out(found: dict[str, Any], scene_id: str | None = None) -> dict[str, Any]:
    document = templates.as_scenes(found["template"], found["slots"])
    return {
        "composition_id": found["id"], "product_id": PRODUCT_ID,
        "uri": f"wasify://creation/composition/{found['id']}", "title": found["title"],
        "shape": document["shape"], "seconds": document["seconds"], "scene_id": scene_id,
        "scenes": [
            {"id": s["id"], "name": s["name"], "kind": s["kind"], "seconds": s["fields"]["seconds"]}
            for s in document["scenes"]
        ],
    }  # fmt: skip


async def _write_scenes(p: WriteScenesIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    try:
        document = templates.normalize_slots(templates.SCENES, p.model_dump())
    except templates.SlotError as e:
        return Outcome.refused(str(e), "bad_slot")
    found = await asyncio.to_thread(
        store_for(deps.state).add_composition, ctx.actor.tenant_id, ctx.actor.user_id,
        title=templates.title_of(templates.SCENES, document), template=templates.SCENES,
        slots=document,
    )  # fmt: skip
    await index_composition(deps, ctx.actor, found)
    return Outcome.ok(
        _scenes_out(found),
        f'The project "{found["title"]}" was written: {len(document["scenes"])} scenes, '
        f"{document['seconds']} seconds. Nothing has been made yet: use video_builder.render to "
        "make the video.",
    )


async def _edit(
    ctx: ActionContext, cid: str, words: str, change: Callable[[dict[str, Any]], Any]
) -> Outcome:
    """One change to a project's scenes: one version. `change` gives the new document, or the new
    document and a scene's id. A project made from a template becomes a project of scenes here."""
    deps = need_deps(ctx)
    current = _found(ctx, cid)
    try:
        made = change(templates.as_scenes(current["template"], current["slots"]))
    except templates.SlotError as e:
        return Outcome.refused(str(e), "bad_slot")
    document, scene_id = made if isinstance(made, tuple) else (made, None)
    found = await asyncio.to_thread(
        store_for(deps.state).update_composition, ctx.actor.tenant_id, ctx.actor.user_id, cid,
        title=templates.title_of(templates.SCENES, document), slots=document,
        template=templates.SCENES,
    )  # fmt: skip
    await index_composition(deps, ctx.actor, found)
    return Outcome.ok(
        _scenes_out(found, scene_id),
        f"{words} The video is now {document['seconds']} seconds, with "
        f"{len(document['scenes'])} scenes. This can be undone.",
    )


async def _add_scene(p: AddSceneIn, ctx: ActionContext) -> Outcome:
    return await _edit(
        ctx, p.composition_id, "The scene was added.",
        lambda d: scenes.add(
            d, p.kind, p.fields, p.name, p.position,
            {"caption": p.caption, "transition": p.transition},
        ),
    )  # fmt: skip


async def _change_scene(p: ChangeSceneIn, ctx: ActionContext) -> Outcome:
    return await _edit(
        ctx, p.composition_id, "The scene was changed.",
        lambda d: scenes.change(
            d, p.scene_id, p.fields, p.name, caption=p.caption, transition=p.transition
        ),
    )  # fmt: skip


async def _move_scene(p: MoveSceneIn, ctx: ActionContext) -> Outcome:
    return await _edit(
        ctx, p.composition_id, "The scene was moved.",
        lambda d: scenes.move(d, p.scene_id, p.position),
    )  # fmt: skip


async def _duplicate_scene(p: SceneRefIn, ctx: ActionContext) -> Outcome:
    return await _edit(
        ctx, p.composition_id, "The scene was copied.", lambda d: scenes.duplicate(d, p.scene_id)
    )


async def _remove_scene(p: SceneRefIn, ctx: ActionContext) -> Outcome:
    return await _edit(
        ctx, p.composition_id, "The scene was removed.", lambda d: scenes.remove(d, p.scene_id)
    )


async def _set_project(p: SetProjectIn, ctx: ActionContext) -> Outcome:
    def change(d: dict[str, Any]) -> dict[str, Any]:
        given = p.model_dump(exclude={"composition_id"}, exclude_none=True)
        return templates.normalize_slots(templates.SCENES, {**d, **given})

    return await _edit(ctx, p.composition_id, "The project was changed.", change)


async def _read_project(p: ReadProjectIn, ctx: ActionContext) -> Outcome:
    found = _found(ctx, p.composition_id)
    document = templates.as_scenes(found["template"], found["slots"])
    return Outcome.ok(
        {
            "composition_id": found["id"], "title": found["title"],
            "brief": editor.brief(document, p.scene_id, _fields_help()),
            "actions": list(editor.ACTIONS),
        },
        f'This is the project "{found["title"]}".',
    )  # fmt: skip


async def _undo(p: CompositionIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    try:
        found = await asyncio.to_thread(
            store_for(deps.state).undo_composition,
            ctx.actor.tenant_id, ctx.actor.user_id, p.composition_id,
        )  # fmt: skip
    except NothingToUndo:
        return Outcome.refused("There is nothing to undo.", "nothing_to_undo")
    await index_composition(deps, ctx.actor, found)
    return Outcome.ok(_scenes_out(found), f'The last change to "{found["title"]}" was undone.')


def _scene_action(
    action_id: str, title: str, summary: str, description: str, given: type[BaseModel],
    example: dict[str, Any], call: Callable[..., Any],
) -> Action:  # fmt: skip
    """A change to a project of scenes: nothing is drawn, so it needs only the product."""
    return Action(
        id=action_id, title=title, summary=summary, description=description, input=given,
        output=ScenesOut, examples=(example,), effect="change",
        requires=(need_product(PRODUCT_ID),), product=PRODUCT_ID,
        bind=CallBinding(call, check=_check_composition), ui="motion",
    )  # fmt: skip


def actions() -> list[Action]:
    return [
        Action(
            id="motion.write_scenes", title="Write a video of several scenes",
            summary="Start a video from a list of scenes, without making it yet.",
            description=(
                "Create a Motion graphics project of several scenes, one after another, for a "
                "promotion, an advert or a social post. Each scene is one of the five templates. "
                "The words are shown exactly as given. Nothing is rendered; call "
                "video_builder.render to make the video. " + _fields_help()
            ),
            input=WriteScenesIn, output=ScenesOut,
            examples=({"name": "Northbean launch", "shape": "portrait", "scenes": [
                {"kind": "title", "name": "Hook", "fields": {"title": "Mornings are hard."}},
                {"kind": "quote", "fields": {"quote": "Smooth, not bitter.", "seconds": 6}},
            ]},),
            effect="make", requires=(need_product(PRODUCT_ID),), product=PRODUCT_ID,
            bind=CallBinding(_write_scenes), ui="motion",
        ),
        Action(
            id="motion.read_project", title="Read a video project",
            summary="What a video project's scenes say, for working on it.",
            description=(
                "Read a Motion graphics project: its shape, length and each scene's id, kind, "
                "words, length and look. The editor's assistant works from this."
            ),
            input=ReadProjectIn, output=ReadProjectOut, examples=({"composition_id": SAMPLE_ID},),
            effect="read", requires=(need_product(PRODUCT_ID),), product=PRODUCT_ID,
            bind=CallBinding(_read_project, check=_check_composition), ui="motion",
        ),
        _scene_action(
            "motion.set_project", "Change the whole project",
            "Change the name or shape of a video project, or write all its scenes.",
            "Change a Motion graphics project's name, shape or letters, or replace all its scenes "
            "at once, as when turning a brief into a first version. Give only what changes. "
            "Nothing is rendered. " + _fields_help(),
            SetProjectIn,
            {"composition_id": SAMPLE_ID, "shape": "square"},
            _set_project,
        ),
        _scene_action(
            "motion.add_scene", "Add a scene",
            "Add a scene to a video project.",
            "Add one scene to a Motion graphics project, at the end or at a position. A project "
            "made from one template becomes a project of scenes. Nothing is rendered.",
            AddSceneIn,
            {"composition_id": SAMPLE_ID, "kind": "title", "fields": {"title": "Try Northbean."}},
            _add_scene,
        ),
        _scene_action(
            "motion.change_scene", "Change a scene",
            "Change the words, length or look of one scene.",
            (
                "Change one scene of a Motion graphics project: give only the fields that change. "
                "The other scenes stay as they are. Nothing is rendered."
            ),
            ChangeSceneIn,
            {"composition_id": SAMPLE_ID, "scene_id": SAMPLE_SCENE, "fields": {"seconds": 4}},
            _change_scene,
        ),
        _scene_action(
            "motion.move_scene", "Move a scene",
            "Move a scene earlier or later in a video project.",
            "Move one scene of a Motion graphics project to a position, from 0.",
            MoveSceneIn,
            {"composition_id": SAMPLE_ID, "scene_id": SAMPLE_SCENE, "position": 0},
            _move_scene,
        ),
        _scene_action(
            "motion.duplicate_scene", "Copy a scene",
            "Copy a scene, right after itself.",
            "Copy one scene of a Motion graphics project, right after itself.",
            SceneRefIn, {"composition_id": SAMPLE_ID, "scene_id": SAMPLE_SCENE}, _duplicate_scene,
        ),
        _scene_action(
            "motion.remove_scene", "Remove a scene",
            "Take a scene out of a video project.",
            (
                "Remove one scene of a Motion graphics project. A project keeps at least one "
                "scene, and motion.undo brings a removed scene back."
            ),
            SceneRefIn, {"composition_id": SAMPLE_ID, "scene_id": SAMPLE_SCENE}, _remove_scene,
        ),
        _scene_action(
            "motion.undo", "Undo the last change",
            "Bring back a video project as it was before the last change.",
            (
                "Undo the last change to a Motion graphics project. Twenty earlier versions are "
                "kept, so it can be used again to go further back."
            ),
            CompositionIn, {"composition_id": SAMPLE_ID}, _undo,
        ),
        Action(
            id="video_builder.create", title="Write a video project",
            summary="Start a video from a template, without making it yet.",
            description=(
                "Create a Motion graphics project from one of five templates and keep it in the "
                "library. Nothing is rendered; call video_builder.render to make the video, or use "
                "motion.make to do both at once. The words are shown exactly as given. "
                + _fields_help()
            ),
            input=CreateIn, output=CompositionOut,
            examples=({"template": "title", "fields": {"title": "Launch day",
                                                      "subtitle": "Wasify AI is here"}},),
            effect="make", requires=(need_product(PRODUCT_ID),), product=PRODUCT_ID,
            bind=CallBinding(_create), ui="motion",
        ),
        Action(
            id="video_builder.lint", title="Check a video project",
            summary="Check that a video project reaches nothing outside its own folder.",
            description=(
                "Check a Motion graphics project before rendering: the page must not load anything "
                "from the internet or from other folders. Returns the findings, if any."
            ),
            input=CompositionIn, output=LintOut, examples=({"composition_id": SAMPLE_ID},),
            effect="read", requires=(need_product(PRODUCT_ID), BUILDER), product=PRODUCT_ID,
            bind=CallBinding(_lint, check=_check_composition), ui="motion",
        ),
        Action(
            id="video_builder.render", title="Make the video",
            summary="Render a video project to a video in the library.",
            description=(
                "Render a Motion graphics project and save it to the library (Your videos). "
                "The words on the screen are checked against what was typed first; a page that "
                "does not say them is not rendered. It runs in a sandbox, takes seconds to a "
                "minute, and only one video is made at a time. Returns a job handle when it is not "
                "done within the wait. Lower thirds and captions can be made transparent (webm or "
                "mov)."
            ),
            input=RenderIn, output=RenderOut, examples=({"composition_id": SAMPLE_ID},),
            effect="make", flags=("costly",), requires=(need_product(PRODUCT_ID), BUILDER),
            long=True, product=PRODUCT_ID,
            bind=CallBinding(_render, check=_check_composition), ui="motion",
        ),
        Action(
            id="motion.make", title="Make a motion graphic",
            summary="Make an animated title, quote, chart, lower third or captions.",
            description=(
                "Make a finished animated graphic in one step: pick the template that fits the "
                "request and give its fields, with the person's words and numbers exactly as they "
                "typed them (never rewrite, correct or translate them). The page is built from a "
                "vetted template, the words on the screen are checked against what was given, and "
                "the video is saved to the library with the project, which stays editable. For "
                "overlays on footage use lower_third or captions with format webm (transparent). "
                "Use image.generate or video.generate for pictures of things. " + _fields_help()
            ),
            input=MakeIn, output=MotionOut,
            examples=(
                {"template": "lower_third",
                 "fields": {"name": "Maya Chen", "role": "Head of Design"}, "format": "webm"},
                {"template": "chart", "fields": {"title": "Sales by region",
                                                 "data": "North, 120\nSouth, 95\nEast, 150"}},
            ),
            effect="make", requires=(need_product(PRODUCT_ID), BUILDER), long=True,
            product=PRODUCT_ID, bind=CallBinding(_make), ui="motion",
        ),
        Action(
            id="motion.revise", title="Change a motion graphic",
            summary="Change the words or the look of a motion graphic and make it again.",
            description=(
                "Change an existing Motion graphics project: give only the fields that change (the "
                "rest stay), and it is made again and checked. The earlier version can be brought "
                "back on the Motion graphics screen. Use for requests like 'make the text bigger' "
                "(change the length or shape), 'use the forest look', or 'fix the typo'."
            ),
            input=ReviseIn, output=MotionOut,
            examples=({"composition_id": SAMPLE_ID, "fields": {"theme": "forest"}},),
            effect="change", requires=(need_product(PRODUCT_ID), BUILDER), long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_revise, check=_check_composition), ui="motion",
        ),
    ]  # fmt: skip


# ---- the library's compositions ---------------------------------------------------------------


def _item(c: dict[str, Any]) -> LibraryItem:
    slots = c["slots"]
    return LibraryItem(
        kind="composition", id=c["id"], title=c["title"][:120], created_at=c["created_at"],
        detail={"seconds": slots.get("seconds"), "shape": slots.get("shape"),
                "template": c["template"]},
    )  # fmt: skip


async def _list(ctx: ActionContext, limit: int) -> list[LibraryItem]:
    rows = await asyncio.to_thread(
        _store(ctx).list_compositions, ctx.actor.tenant_id, ctx.actor.user_id, None, limit
    )
    return [_item(c) for c in rows]


async def _get(ctx: ActionContext, item_id: str) -> LibraryItem | None:
    try:
        return _item(_store(ctx).get_composition(ctx.actor.tenant_id, ctx.actor.user_id, item_id))
    except NotFound:
        return None


async def _delete(ctx: ActionContext, item_id: str) -> bool:
    return await delete_composition(need_deps(ctx), ctx.actor, item_id)


async def _rename(ctx: ActionContext, item_id: str, name: str) -> bool:
    deps = need_deps(ctx)
    try:
        found = _store(ctx).get_composition(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
        primary = templates.get(found["template"]).primary
        if primary is None:
            return False
        slots = templates.normalize_slots(found["template"], {**found["slots"], primary: name})
    except (NotFound, templates.SlotError):
        return False
    updated = _store(ctx).update_composition(
        ctx.actor.tenant_id, ctx.actor.user_id, item_id,
        title=templates.title_of(found["template"], slots), slots=slots,
    )  # fmt: skip
    await index_composition(deps, ctx.actor, updated)
    return True


def library_kinds() -> list[LibraryKind]:
    return [LibraryKind("composition", PRODUCT_ID, "video project", _list, _get, _delete, _rename)]


__all__ = ["actions", "library_kinds"]
