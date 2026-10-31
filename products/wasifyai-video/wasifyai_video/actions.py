"""What the video product can do, for the action catalogue (ADR-0068): make a clip from words,
make a picture of the library move, carry on a clip of the library, and the library's clips as a
kind of creation."""

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

from wasifyai_video.builder.actions import actions as builder_actions
from wasifyai_video.builder.actions import library_kinds as builder_library_kinds
from wasifyai_video.routes import extension_of, file_name, save_copy
from wasifyai_video.schemas import MAX_PROMPT_CHARS
from wasifyai_video.videos import VideoRecord, video_store

PRODUCT_ID = "wasifyai-video"
Shape = Literal["landscape", "portrait", "square"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GenerateIn(Strict):
    prompt: str = Field(
        min_length=1, max_length=MAX_PROMPT_CHARS,
        description="What happens in the clip, in clear concrete words, in English.",
    )  # fmt: skip
    shape: Shape = Field("landscape", description="The shape of the picture.")
    seconds: Literal[5, 8] = Field(5, description="How long the clip is.")


class AnimateIn(Strict):
    image_id: str = Field(min_length=1, max_length=64, description="The picture to set moving.")
    prompt: str = Field(
        min_length=1, max_length=MAX_PROMPT_CHARS, description="What should move, in English."
    )
    seconds: Literal[5, 8] = Field(5, description="How long the clip is.")


class ExtendIn(Strict):
    video_id: str = Field(min_length=1, max_length=64, description="The video to carry on.")
    prompt: str = Field(
        min_length=1, max_length=MAX_PROMPT_CHARS,
        description=(
            "What should keep happening, in English. The motion in the last second of the video "
            "carries on whatever this says: it describes, it does not change the action."
        ),
    )  # fmt: skip
    seconds: Literal[5, 8] = Field(5, description="How much is added: about 5 or about 8 seconds.")


class VideoOut(BaseModel):
    video_id: str
    product_id: str
    uri: str
    prompt: str
    seconds: int
    width: int
    height: int


def _made(outputs: dict, prompt: str) -> Outcome | None:
    if outputs.get("status") != "done" or not outputs.get("video_id"):
        return None
    seconds = int(outputs.get("seconds", 0))
    width, height = int(outputs.get("width", 0)), int(outputs.get("height", 0))
    return Outcome.ok(
        {
            "video_id": outputs["video_id"], "product_id": PRODUCT_ID, "prompt": prompt,
            "uri": f"wasify://creation/video/{outputs['video_id']}", "seconds": seconds,
            "width": width, "height": height,
        },
        f'The video was made ({seconds} seconds, {width}x{height}) from "{prompt}" and saved to '
        "the library.",
    )  # fmt: skip


def _generate_input(p: GenerateIn, ctx: ActionContext) -> dict:
    return {"mode": "text", "prompt": p.prompt, "shape": p.shape, "seconds": p.seconds}


def _generate_result(outputs: dict, p: GenerateIn) -> Outcome | None:
    return _made(outputs, p.prompt)


async def _picture_data(ctx: ActionContext, image_id: str) -> bytes:
    """The picture's file, through the library kind the image product declares."""
    kind = ctx.library.get("image")
    data = await kind.read(ctx, image_id) if kind and kind.read else None
    if data is None:
        raise ActionRefused("not_found", "That picture is not in the library.")
    return data


async def _animate_check(p: AnimateIn, ctx: ActionContext) -> None:
    await _picture_data(ctx, p.image_id)


async def _animate_input(p: AnimateIn, ctx: ActionContext) -> dict:
    key = await stage_picture(ctx, PRODUCT_ID, await _picture_data(ctx, p.image_id))
    return {
        "mode": "image", "prompt": p.prompt, "image_key": key, "seconds": p.seconds,
        "source_image_id": p.image_id,
    }  # fmt: skip


def _animate_result(outputs: dict, p: AnimateIn) -> Outcome | None:
    return _made(outputs, p.prompt)


async def _source(ctx: ActionContext, video_id: str) -> VideoRecord:
    found = await video_store(need_deps(ctx).engine).get(
        ctx.actor.tenant_id, ctx.actor.user_id, video_id
    )
    if found is None or found.status != "done" or not found.video_key:
        raise ActionRefused("not_found", "That video is not in the library.")
    return found


async def _extend_check(p: ExtendIn, ctx: ActionContext) -> None:
    await _source(ctx, p.video_id)


def _extend_input(p: ExtendIn, ctx: ActionContext) -> dict:
    return {"mode": "extend", "prompt": p.prompt, "source_id": p.video_id, "seconds": p.seconds}


def _extend_result(outputs: dict, p: ExtendIn) -> Outcome | None:
    return _made(outputs, p.prompt)


def actions() -> list[Action]:
    return [
        Action(
            id="video.generate", title="Make a video",
            summary="Make a short video clip from a description.",
            description=(
                "Make a short video clip (5 or 8 seconds) from a description and save it to the "
                "person's library. It takes minutes on this computer and only one clip is made "
                "at a time, so it returns a job handle when it is not done within the wait. To "
                "set a picture moving, use video.animate."
            ),
            input=GenerateIn, output=VideoOut,
            examples=({"prompt": "waves rolling onto a beach at sunrise"},
                      {"prompt": "a paper boat on a rainy street", "shape": "portrait",
                       "seconds": 5}),
            effect="make", flags=("costly",), requires=(need_product(PRODUCT_ID),), long=True,
            product=PRODUCT_ID,
            bind=RunBinding(PRODUCT_ID, "video", _generate_input, _generate_result),
            ui="video.create",
        ),
        Action(
            id="video.animate", title="Animate a picture",
            summary="Make a picture of the library move.",
            description=(
                "Turn a picture the person has in the library into a short clip (5 or 8 seconds) "
                "by saying what should move. Takes minutes; returns a job handle when it is not "
                "done within the wait."
            ),
            input=AnimateIn, output=VideoOut,
            examples=({"image_id": "0b7c1f9e-0000-4000-8000-000000000000",
                       "prompt": "the clouds drift slowly to the left"},),
            effect="make", flags=("costly",), requires=(need_product(PRODUCT_ID),), long=True,
            product=PRODUCT_ID,
            bind=RunBinding(PRODUCT_ID, "video", _animate_input, _animate_result,
                            check=_animate_check),
            ui="video.animate",
        ),
        Action(
            id="video.extend", title="Extend a video",
            summary="Carry on a video of the library for about 5 or 8 more seconds.",
            description=(
                "Make a video of the library longer: its last second starts a new part, which is "
                "joined on, so the motion carries on (about 5 or 8 seconds more, saved as a new "
                "video; the original stays). It works on a video of any length, and its picture "
                "gets a little softer each time it is carried on, so two or three rounds is a "
                "sensible stop. What the prompt "
                "says steers only weakly: describe what keeps happening, not a change of "
                "action. Takes minutes; returns a job handle when it is not done within the wait."
            ),
            input=ExtendIn, output=VideoOut,
            examples=({"video_id": "0b7c1f9e-0000-4000-8000-000000000000",
                       "prompt": "the fox keeps walking through the snow"},),
            effect="make", flags=("costly",), requires=(need_product(PRODUCT_ID),), long=True,
            product=PRODUCT_ID,
            bind=RunBinding(PRODUCT_ID, "video", _extend_input, _extend_result,
                            check=_extend_check),
            ui="video.extend",
        ),
        *builder_actions(),  # Motion graphics (ADR-0077): videos written as HTML
    ]  # fmt: skip


# ---- the library's clips ----------------------------------------------------------------------


def _item(v: VideoRecord) -> LibraryItem:
    return LibraryItem(
        kind="video", id=v.id, title=v.prompt[:120],
        created_at=v.created_at.isoformat() if v.created_at else None,
        detail={"seconds": v.seconds, "status": v.status, "width": v.width, "height": v.height},
    )  # fmt: skip


async def _list(ctx: ActionContext, limit: int) -> list[LibraryItem]:
    rows = await video_store(need_deps(ctx).engine).list(
        ctx.actor.tenant_id, ctx.actor.user_id, limit, None, None
    )
    return [_item(v) for v in rows]


async def _get(ctx: ActionContext, item_id: str) -> LibraryItem | None:
    found = await video_store(need_deps(ctx).engine).get(
        ctx.actor.tenant_id, ctx.actor.user_id, item_id
    )
    return _item(found) if found else None


async def _delete(ctx: ActionContext, item_id: str) -> bool:
    deps = need_deps(ctx)
    store = video_store(deps.engine)
    video = await store.get(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    if video is None:
        return False
    if video.status == "working":
        raise ActionRefused("busy", "That video is still being made.")
    with deps.acting_as(ctx.actor, PRODUCT_ID):  # its files first, then the record
        for key in (video.video_key, video.poster_key):
            if not key:
                continue
            try:
                await deps.storage.delete(key)
            except FileNotFoundError:
                pass
    await store.delete(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    await deps.unindex(ctx.actor, PRODUCT_ID, item_id)  # out of search too (ADR-0041)
    return True


async def _read(ctx: ActionContext, item_id: str) -> bytes | None:
    """A clip's bytes, for what brings it somewhere else (a project of scenes, ADR-0096)."""
    deps = need_deps(ctx)
    clip = await video_store(deps.engine).get(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    if clip is None or not clip.video_key:
        return None
    with deps.acting_as(ctx.actor, PRODUCT_ID):
        try:
            return await deps.storage.get(clip.video_key)
        except FileNotFoundError:
            return None


async def _export(ctx: ActionContext, item_id: str, folder: Path) -> Path | None:
    deps = need_deps(ctx)
    video = await video_store(deps.engine).get(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    if video is None or video.status != "done" or not video.video_key:
        return None
    with deps.acting_as(ctx.actor, PRODUCT_ID):
        try:
            data = await deps.storage.get(video.video_key)
        except FileNotFoundError:
            return None
    return await asyncio.to_thread(
        save_copy, folder, file_name(video.prompt, ""), extension_of(video.video_key), data
    )


def library_kinds() -> list[LibraryKind]:
    return [
        LibraryKind("video", PRODUCT_ID, "video", _list, _get, _delete, None, _export, _read),
        *builder_library_kinds(),
    ]


__all__ = ["actions", "library_kinds"]
