"""What training can do, for the action catalogue (ADR-0068, ADR-0073): teach a model from a set of
pictures (a long action: `job.status` and `job.cancel` follow and stop it), and the trained models
as a kind of creation (list, look at, rename, delete, save a copy).

A set of pictures is made on the screen (the pictures are the person's files, the description of
each is written by the app, and the person says whose they are), so an agent starts a run on a set
that already exists and is ready."""

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk.actions import (
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

from wasifyai_training.runtime import (
    KIND,
    PRODUCT_ID,
    Refused,
    add_to_search,
    delete_model,
    engine_for,
    model_folder,
    not_ready,
    run_manager_for,
    store_for,
    words_of,
)
from wasifyai_training.store import NotFound

ENGINE = need_runtime("training")
SAMPLE_ID = "0b7c1f9e0000400080000000deadbeef"


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    dataset_id: str = Field(
        min_length=32, max_length=32,
        description="The set of pictures to teach from: made on the Train screen, with its "
        "descriptions written, its magic word chosen and its statement of rights given.",
    )  # fmt: skip


class StartOut(BaseModel):
    run_id: str
    model_id: str
    product_id: str
    uri: str
    name: str
    magic_word: str
    steps: int
    seconds: int
    preview: bool


def _item(row: dict[str, Any]) -> LibraryItem:
    return LibraryItem(
        kind=KIND, id=row["id"], title=row["name"][:120], created_at=row["created_at"],
        detail={"magic_word": row["trigger_word"], "kind": row["kind"], "preview": row["preview"]},
    )  # fmt: skip


async def _start(p: StartIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    engine, store = engine_for(deps.state), store_for(deps.state)
    if not engine.ready():
        return Outcome.refused(not_ready(engine), "not_ready")
    runs = run_manager_for(deps)
    try:
        row = await runs.start(ctx.actor, p.dataset_id)
    except NotFound:
        return Outcome.refused("That set of pictures does not exist.", "not_found")
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    try:
        await runs.wait(row["id"])
    except asyncio.CancelledError:
        await runs.cancel(ctx.actor, row["id"])
        raise
    done = store.get_run(ctx.actor.tenant_id, ctx.actor.user_id, row["id"])
    if done["status"] != "done" or not done["model_id"]:
        return Outcome.error(done["error"] or "The model could not be taught.", "failed")
    model = store.get_model(ctx.actor.tenant_id, ctx.actor.user_id, done["model_id"])
    mins = max(1, round((done["elapsed_s"] or 0) / 60))
    note = (
        " This was a preview: nothing was learnt, and the file is not a model yet."
        if done["preview"]
        else ""
    )
    return Outcome.ok(
        {
            "run_id": done["id"], "model_id": model["id"], "product_id": PRODUCT_ID,
            "uri": f"wasify://creation/lora/{model['id']}", "name": model["name"],
            "magic_word": model["trigger_word"], "steps": done["steps"],
            "seconds": round(done["elapsed_s"] or 0), "preview": done["preview"],
        },
        f'"{model["name"]}" was taught in about {mins} minute{"s" if mins != 1 else ""}. '
        f'Write "{model["trigger_word"]}" in a prompt to draw it.{note}',
    )  # fmt: skip


async def _list(ctx: ActionContext, limit: int) -> list[LibraryItem]:
    deps = need_deps(ctx)
    rows = await asyncio.to_thread(
        store_for(deps.state).list_models, ctx.actor.tenant_id, ctx.actor.user_id, limit
    )
    return [_item(r) for r in rows]


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


async def _adapter(ctx: ActionContext, item_id: str) -> bytes | None:
    state = need_deps(ctx).state
    store = store_for(state)
    try:
        store.get_model(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    except NotFound:
        return None
    path = model_folder(store, ctx.actor, item_id) / "adapter.safetensors"
    return (
        await asyncio.to_thread(path.read_bytes) if await asyncio.to_thread(path.is_file) else None
    )


async def _export(ctx: ActionContext, item_id: str, folder: Path) -> Path | None:
    data = await _adapter(ctx, item_id)
    if data is None:
        return None
    row = store_for(need_deps(ctx).state).get_model(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    stem = (row["trigger_word"] or row["name"] or "lora").lower()
    return await asyncio.to_thread(
        _save, folder, "".join(c for c in stem if c.isalnum()) or "lora", data
    )


def _save(folder: Path, stem: str, data: bytes) -> Path:
    """A copy that never replaces a file: `marlo.safetensors`, then `marlo-2.safetensors`."""
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"{stem}.safetensors", 1
    while True:
        try:
            with path.open("xb") as out:
                out.write(data)
            return path
        except FileExistsError:
            n += 1
            path = folder / f"{stem}-{n}.safetensors"


def actions() -> list[Action]:
    common = {"requires": (need_product(PRODUCT_ID), ENGINE), "product": PRODUCT_ID, "ui": "train"}
    return [
        Action(
            id="train.start",
            title="Teach a character or style",
            summary="Teach the image model a character, style or object from a set of pictures.",
            description=(
                "Teach the image model something of the person's own from a set of their pictures: "
                "a character, a pet, a person (with their agreement), a style or an object. The "
                "set is made on the Train screen: the pictures are added there, the app writes a "
                "description of each, the person chooses a magic word and says whose the pictures "
                "are. This starts the run on a set that is ready and waits for it. It takes about "
                "25 minutes on a Mac and pauses chat and image making, so it is made one at a "
                "time. Then writing the magic word in a prompt draws the result."
            ),
            input=StartIn,
            output=StartOut,
            examples=({"dataset_id": SAMPLE_ID},),
            effect="make",
            flags=("costly",),
            long=True,
            bind=CallBinding(_start),
            **common,
        ),
    ]


def library_kinds() -> list[LibraryKind]:
    return [
        LibraryKind(
            KIND,
            PRODUCT_ID,
            "Trained model",
            _list,
            _get,
            _delete,
            _rename,
            export=_export,
            read=_adapter,
        )
    ]


__all__ = ["actions", "library_kinds"]
