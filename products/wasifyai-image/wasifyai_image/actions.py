"""What the image product can do, for the action catalogue (ADR-0068): make a picture from words,
change a picture of the library, and the library's pictures as a kind of creation.

Adding an action is adding to `actions()`: the executor, the assistant and MCP read it there."""

import asyncio
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk.actions import (
    Action,
    ActionContext,
    ActionRefused,
    LibraryItem,
    LibraryKind,
    Outcome,
    RunBinding,
    need_product,
)
from wasifyai_platform_sdk.actions.helpers import need_deps, stage_picture

from wasifyai_image.images import ImageRecord, image_store
from wasifyai_image.routes import file_name, save_copy
from wasifyai_image.schemas import MAX_PROMPT_CHARS

PRODUCT_ID = "wasifyai-image"
Size = Literal["square", "landscape", "portrait", "wide", "tall"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GenerateIn(Strict):
    prompt: str = Field(
        min_length=1, max_length=MAX_PROMPT_CHARS,
        description="A clear, concrete description of the picture, in English.",
    )  # fmt: skip
    size: Size = Field("square", description="The shape of the picture.")


class EditIn(Strict):
    image_id: str = Field(min_length=1, max_length=64, description="The picture to change.")
    prompt: str = Field(
        min_length=1, max_length=MAX_PROMPT_CHARS, description="What to change, in English."
    )


class ImageOut(BaseModel):
    image_id: str
    product_id: str
    uri: str
    prompt: str
    width: int
    height: int


def _made(outputs: dict, prompt: str, verb: str) -> Outcome | None:
    if outputs.get("status") != "done" or not outputs.get("image_id"):
        return None
    width, height = int(outputs.get("width", 0)), int(outputs.get("height", 0))
    return Outcome.ok(
        {
            "image_id": outputs["image_id"], "product_id": PRODUCT_ID, "prompt": prompt,
            "uri": f"wasify://creation/image/{outputs['image_id']}", "width": width,
            "height": height,
        },
        f'The image was {verb} ({width}x{height}) from "{prompt}" and saved to the library.',
    )  # fmt: skip


def _generate_input(p: GenerateIn, ctx: ActionContext) -> dict:
    return {"mode": "text", "prompt": p.prompt, "size": p.size}


def _generate_result(outputs: dict, p: GenerateIn) -> Outcome | None:
    return _made(outputs, p.prompt, "made")


async def _edit_input(p: EditIn, ctx: ActionContext) -> dict:
    data = await _read(ctx, p.image_id)
    if data is None:
        raise ActionRefused("not_found", "That picture is not in the library.")
    key = await stage_picture(ctx, PRODUCT_ID, data)
    return {"mode": "image", "prompt": p.prompt, "image_key": key}


def _edit_result(outputs: dict, p: EditIn) -> Outcome | None:
    return _made(outputs, p.prompt, "changed")


async def _edit_check(p: EditIn, ctx: ActionContext) -> None:
    deps = need_deps(ctx)
    if (
        await image_store(deps.engine).get(ctx.actor.tenant_id, ctx.actor.user_id, p.image_id)
        is None
    ):
        raise ActionRefused("not_found", "That picture is not in the library.")


def actions() -> list[Action]:
    return [
        Action(
            id="image.generate", title="Make a picture",
            summary="Make a new picture from a description.",
            description=(
                "Make a new picture from a description and save it to the person's library. Use "
                "it when the person asks you to draw, paint, make or generate an image. Write the "
                "prompt as a clear, concrete description in English. Returns the picture's id and "
                "size. To change a picture that exists, use image.edit."
            ),
            input=GenerateIn, output=ImageOut,
            examples=({"prompt": "a red teapot on a wooden table"},
                      {"prompt": "a cat dressed as an astronaut on the moon", "size": "wide"}),
            effect="make", requires=(need_product(PRODUCT_ID),), long=True, product=PRODUCT_ID,
            bind=RunBinding(PRODUCT_ID, "image", _generate_input, _generate_result),
            ui="images.create",
        ),
        Action(
            id="image.edit", title="Change a picture",
            summary="Change a picture of the library by describing the change.",
            description=(
                "Change a picture the person already has in the library: say what to change. It "
                "makes a new picture and keeps the original. Use image.generate for a new one."
            ),
            input=EditIn, output=ImageOut,
            examples=({"image_id": "0b7c1f9e-0000-4000-8000-000000000000",
                       "prompt": "make the sky a sunset"},),
            effect="make", requires=(need_product(PRODUCT_ID),), long=True, product=PRODUCT_ID,
            bind=RunBinding(PRODUCT_ID, "image", _edit_input, _edit_result, check=_edit_check),
            ui="images.edit",
        ),
    ]  # fmt: skip


# ---- the library's pictures -------------------------------------------------------------------


def _item(i: ImageRecord) -> LibraryItem:
    return LibraryItem(
        kind="image", id=i.id, title=i.prompt[:120],
        created_at=i.created_at.isoformat() if i.created_at else None,
        detail={"width": i.width, "height": i.height, "favourite": i.favourite},
    )  # fmt: skip


async def _list(ctx: ActionContext, limit: int) -> list[LibraryItem]:
    rows = await image_store(need_deps(ctx).engine).list(
        ctx.actor.tenant_id, ctx.actor.user_id, limit, None
    )
    return [_item(i) for i in rows]


async def _get(ctx: ActionContext, item_id: str) -> LibraryItem | None:
    found = await image_store(need_deps(ctx).engine).get(
        ctx.actor.tenant_id, ctx.actor.user_id, item_id
    )
    return _item(found) if found else None


async def _delete(ctx: ActionContext, item_id: str) -> bool:
    deps = need_deps(ctx)
    store = image_store(deps.engine)
    image = await store.get(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    if image is None:
        return False
    with deps.acting_as(ctx.actor, PRODUCT_ID):  # its files first, then the record
        for key in (image.image_key, image.thumb_key):
            try:
                await deps.storage.delete(key)
            except FileNotFoundError:
                pass
    await store.delete(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    await deps.unindex(ctx.actor, PRODUCT_ID, item_id)  # out of search too (ADR-0041)
    return True


async def _export(ctx: ActionContext, item_id: str, folder: Path) -> Path | None:
    deps = need_deps(ctx)
    image = await image_store(deps.engine).get(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    if image is None:
        return None
    with deps.acting_as(ctx.actor, PRODUCT_ID):
        try:
            data = await deps.storage.get(image.image_key)
        except FileNotFoundError:
            return None
    ext = image.image_key.rsplit(".", 1)[-1].lower()
    return await asyncio.to_thread(save_copy, folder, file_name(image.prompt, ""), ext, data)


async def _read(ctx: ActionContext, item_id: str) -> bytes | None:
    deps = need_deps(ctx)
    image = await image_store(deps.engine).get(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    if image is None:
        return None
    with deps.acting_as(ctx.actor, PRODUCT_ID):
        try:
            return await deps.storage.get(image.image_key)
        except FileNotFoundError:
            return None


def library_kinds() -> list[LibraryKind]:
    return [LibraryKind("image", PRODUCT_ID, "picture", _list, _get, _delete, None, _export, _read)]


__all__ = ["actions", "library_kinds"]
