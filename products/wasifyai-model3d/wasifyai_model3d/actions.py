"""What 3D can do, for the action catalogue (ADR-0068, ADR-0080): make a model from a picture of the
library, and the models as a kind of creation (list, look at, rename, delete, save a copy, read).

`model3d.generate` takes a picture of the library (an image the person made or kept). Making a model
from words goes through a picture first (the person picks one of four candidates on the screen,
ADR-0080 decision 2); an agent that has the words makes the picture with `image.generate` and
passes it here."""

import asyncio
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
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

from wasifyai_model3d import files, pictures
from wasifyai_model3d.runtime import (
    KIND,
    PRODUCT_ID,
    Refused,
    add_to_search,
    delete_model,
    engine_for,
    manager_for,
    not_ready,
    store_for,
    words_of,
)
from wasifyai_model3d.store import NotFound

ENGINE = need_runtime("model3d")
SAMPLE_ID = "0b7c1f9e-0000-4000-8000-000000000000"


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    image_id: str = Field(
        min_length=1, max_length=64,
        description="The picture of the library to make a model of: one object, straight on, "
        "on a plain background works best.",
    )  # fmt: skip
    title: str = Field("", max_length=200, description="A name for the model.")
    prompt: str = Field("", max_length=1000, description="The words the picture was made from.")
    detail: Literal["light", "standard", "detailed"] = Field(
        "standard", description="The size of the texture: light, standard or detailed."
    )
    seed: int = Field(42, ge=0, le=2**31 - 1, description="The same seed gives the same model.")


class GenerateOut(BaseModel):
    model_id: str
    product_id: str
    uri: str
    title: str
    seconds: int
    triangles_about: int


def _item(row: dict[str, Any]) -> LibraryItem:
    return LibraryItem(
        kind=KIND, id=row["id"], title=row["title"][:120], created_at=row["created_at"],
        detail={"status": row["status"], "detail": row["detail"], "bytes": row["glb_bytes"]},
    )  # fmt: skip


def _picture_kind(ctx: ActionContext) -> Any:
    kind = ctx.library.get("image")
    if kind is None or kind.read is None:
        raise ActionRefused("unavailable", "Pictures cannot be read here.")
    return kind


async def _generate(p: GenerateIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    engine, store = engine_for(deps.state), store_for(deps.state)
    if not engine.ready():
        return Outcome.refused(not_ready(engine), "not_ready")
    data = await _picture_kind(ctx).read(ctx, p.image_id)
    if data is None:
        return Outcome.refused("That picture is not in the library.", "not_found")
    try:
        img = await asyncio.to_thread(pictures.open_picture, data)
        png = await asyncio.to_thread(pictures.to_png, img)
    except pictures.BadPicture as e:
        return Outcome.refused(str(e), "bad_picture")
    jobs = manager_for(deps)
    row = store.add_input(ctx.actor.tenant_id, ctx.actor.user_id, "library picture", *img.size)
    try:
        await jobs.prepare(ctx.actor, row["id"], png)
        await jobs.wait(row["id"])
        checked = store.get_input(ctx.actor.tenant_id, ctx.actor.user_id, row["id"])
        if checked["status"] != "ready":
            return Outcome.error(checked["error"] or "The picture could not be cut out.", "cutout")
        stops = [c["message"] for c in checked["checks"] if c["level"] == "stop"]
        if stops:
            return Outcome.refused(stops[0], "unusable")
        made = await jobs.start(
            ctx.actor, row["id"], title=p.title, prompt=p.prompt, detail=p.detail, seed=p.seed
        )
        try:
            await jobs.wait(made["id"])
        except asyncio.CancelledError:
            await jobs.cancel(ctx.actor, made["id"])
            raise
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    done = store.get_model(ctx.actor.tenant_id, ctx.actor.user_id, made["id"])
    if done["status"] != "done":
        return Outcome.error(done["error"] or "The 3D model could not be made.", "failed")
    mins = max(1, round((done["elapsed_s"] or 0) / 60))
    return Outcome.ok(
        {
            "model_id": done["id"],
            "product_id": PRODUCT_ID,
            "uri": f"wasify://creation/model3d/{done['id']}",
            "title": done["title"],
            "seconds": round(done["elapsed_s"] or 0),
            "triangles_about": 1_000_000,
        },
        f'The 3D model "{done["title"]}" was made in about {mins} minute{"s" if mins != 1 else ""} '
        "and is in the library. It can be opened in the 3D viewer or saved as a GLB file.",
    )


async def _list(ctx: ActionContext, limit: int) -> list[LibraryItem]:
    deps = need_deps(ctx)
    rows = await asyncio.to_thread(
        store_for(deps.state).list_models, ctx.actor.tenant_id, ctx.actor.user_id, None, limit
    )
    return [_item(r) for r in rows if r["status"] == "done"]


async def _get(ctx: ActionContext, item_id: str) -> LibraryItem | None:
    try:
        row = store_for(need_deps(ctx).state).get_model(
            ctx.actor.tenant_id, ctx.actor.user_id, item_id
        )
    except NotFound:
        return None
    return _item(row)


async def _delete(ctx: ActionContext, item_id: str) -> bool:
    return await delete_model(need_deps(ctx), ctx.actor, item_id)


async def _rename(ctx: ActionContext, item_id: str, name: str) -> bool:
    deps = need_deps(ctx)
    try:
        row = store_for(deps.state).rename_model(
            ctx.actor.tenant_id, ctx.actor.user_id, item_id, name
        )
    except NotFound:
        return False
    await add_to_search(deps.state, ctx.actor, item_id, words_of(row))
    return True


async def _glb(ctx: ActionContext, item_id: str) -> Path | None:
    store = store_for(need_deps(ctx).state)
    try:
        row = store.get_model(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    except NotFound:
        return None
    if row["status"] != "done":
        return None
    path = store.folder_of(ctx.actor.tenant_id, ctx.actor.user_id, "models", item_id) / "model.glb"
    return path if path.is_file() else None


async def _export(ctx: ActionContext, item_id: str, folder: Path) -> Path | None:
    path = await _glb(ctx, item_id)
    if path is None:
        return None
    row = store_for(need_deps(ctx).state).get_model(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    return await asyncio.to_thread(files.save_copy, folder, files.file_stem(row["title"]), path)


async def _read(ctx: ActionContext, item_id: str) -> bytes | None:
    path = await _glb(ctx, item_id)
    return await asyncio.to_thread(path.read_bytes) if path else None


def actions() -> list[Action]:
    return [
        Action(
            id="model3d.generate",
            title="Make a 3D model",
            summary="Make a 3D model (a GLB file) from a picture in the library.",
            description=(
                "Make a 3D model of the object in a picture of the library: the picture is cut "
                "out, checked, and turned into a textured model of about a million triangles (a "
                "GLB file) on this computer. It takes about 5 to 25 minutes and about 19 GB of "
                "memory, so it is made one at a time. A picture of one object, straight on at "
                "eye level on a plain background works best; glass, mirrors, thin parts and "
                "several objects do not come out well. To make a model from words, make the "
                "picture first with image.generate and pass it here."
            ),
            input=GenerateIn,
            output=GenerateOut,
            examples=({"image_id": SAMPLE_ID},),
            effect="make",
            flags=("costly",),
            requires=(need_product(PRODUCT_ID), ENGINE),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_generate),
            ui="images.model3d",
        ),
    ]


def library_kinds() -> list[LibraryKind]:
    return [
        LibraryKind(
            KIND, PRODUCT_ID, "3D model", _list, _get, _delete, _rename, export=_export, read=_read
        )
    ]


__all__ = ["actions", "library_kinds"]
