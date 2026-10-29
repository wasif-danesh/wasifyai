"""What training can do, for the action catalogue (ADR-0068, ADR-0073): teach a model from a set of
pictures (a long action: `job.status` and `job.cancel` follow and stop it), and the trained models
as a kind of creation (list, look at, rename, delete, save a copy).

A set of pictures is made on the screen (the pictures are the person's files, the description of
each is written by the app), so an agent starts a run on a set
that already exists and is ready."""

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
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

from wasifyai_training.decisions import CannotDecide, decide
from wasifyai_training.decisions import manager_for as decision_manager_for
from wasifyai_training.runtime import (
    KIND,
    PRODUCT_ID,
    NotAvailable,
    Refused,
    add_to_search,
    delete_model,
    engine_for,
    folder_ready,
    not_ready,
    run_manager_for,
    store_for,
    words_of,
)
from wasifyai_training.store import NotFound
from wasifyai_training.video import manager_for as video_manager_for
from wasifyai_training.writing import manager_for as writing_manager_for

ENGINE = need_runtime("training")
DECIDER = need_runtime("decision_training")
SAMPLE_ID = "0b7c1f9e0000400080000000deadbeef"


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    dataset_id: str | None = Field(
        default=None, min_length=32, max_length=32,
        description="The set of pictures to teach from: made on the Train screen, with its "
        "descriptions written and its magic word chosen.",
    )  # fmt: skip
    set_id: str | None = Field(
        default=None, min_length=32, max_length=32,
        description="Or the set of examples to teach a writing model from: made on the Train "
        "screen under 'Teach it from examples', with at least 10 questions and "
        "answers. Give this or dataset_id, not both.",
    )  # fmt: skip
    decision_set_id: str | None = Field(
        default=None, min_length=32, max_length=32,
        description="Or the set of texts and answers to teach a decision model from: made on the "
        "Train screen under 'Teach it to decide', with one question, at least 20 texts with their "
        "answers. Give one of dataset_id, set_id or decision_set_id.",
    )  # fmt: skip
    base: str | None = Field(
        default=None,
        max_length=80,
        description="The model to teach, from the Train screen's 'Choose the model and method'. "
        "Leave it out to use the recommended one.",
    )
    method: str | None = Field(
        default=None,
        max_length=20,
        description="How to teach it: lora, qlora or full. Leave it out for the recommended one "
        "(lora, a small adapter); a method the model cannot use is refused with the reason.",
    )

    @model_validator(mode="after")
    def _one_set(self) -> "StartIn":
        given = [x for x in (self.dataset_id, self.set_id, self.decision_set_id) if x is not None]
        if len(given) != 1:
            raise ValueError(
                "Give exactly one of dataset_id (pictures), set_id (writing examples) or "
                "decision_set_id (texts and answers)."
            )
        return self


class StartOut(BaseModel):
    run_id: str
    model_id: str
    product_id: str
    uri: str
    name: str
    steps: int
    seconds: int
    magic_word: str = ""  # pictures: the word that draws it
    preview: bool = False
    examples: int = 0  # writing: how many examples it learnt from
    passed: bool | None = None  # writing and deciding: whether the check says it learnt
    verdict: str = ""  # writing and deciding: that, in a sentence


class DecideIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    model_id: str = Field(
        min_length=32, max_length=32,
        description="The decision model to ask: one made on the Train screen under 'Teach it to "
        "decide' (its id is in the library).",
    )  # fmt: skip
    texts: list[str] = Field(
        min_length=1, max_length=100,
        description="The texts to decide about, up to 100. Each is answered on its own.",
    )  # fmt: skip


class Decided(BaseModel):
    text: str
    answer: str  # yes or no, one of the categories, or a level
    confidence: float  # how sure it is, 0 to 1


class DecideOut(BaseModel):
    question: str
    kind: str  # yes_no, category or score
    answers: list[str]  # every answer it can give
    results: list[Decided]


async def _decide(p: DecideIn, ctx: ActionContext) -> Outcome:
    try:
        got = await decide(need_deps(ctx), ctx.actor, p.model_id, p.texts)
    except CannotDecide as e:
        return Outcome.refused(e.message, e.code)
    results = [
        {"text": t, "answer": r["answer"], "confidence": r["confidence"]}
        for t, r in zip(p.texts, got["results"], strict=True)
    ]
    first = results[0]
    one = (
        f"{got['question']} {first['answer']} ({round(first['confidence'] * 100)} percent sure)."
        if len(results) == 1
        else f"Decided {len(results)} texts: {got['question']}"
    )
    return Outcome.ok(
        {
            "question": got["question"], "kind": got["kind"],
            "answers": got["answers"], "results": results,
        },
        one,
    )  # fmt: skip


def _item(row: dict[str, Any]) -> LibraryItem:
    return LibraryItem(
        kind=KIND, id=row["id"], title=row["name"][:120], created_at=row["created_at"],
        detail={"magic_word": row["trigger_word"], "kind": row["kind"], "preview": row["preview"]},
    )  # fmt: skip


async def _start_writing(p: StartIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    store = store_for(deps.state)
    runs = writing_manager_for(deps)
    try:
        row = await runs.start(ctx.actor, str(p.set_id))
    except NotFound:
        return Outcome.refused("That set of examples does not exist.", "not_found")
    except (Refused, NotAvailable) as e:
        return Outcome.refused(str(getattr(e, "message", e)), getattr(e, "code", "not_ready"))
    try:
        await runs.wait(row["id"])
    except asyncio.CancelledError:
        await runs.cancel(ctx.actor, row["id"])
        raise
    done = store.get_run(ctx.actor.tenant_id, ctx.actor.user_id, row["id"])
    if done["status"] != "done" or not done["model_id"]:
        return Outcome.error(done["error"] or "The model could not be taught.", "failed")
    model = store.get_model(ctx.actor.tenant_id, ctx.actor.user_id, done["model_id"])
    verdict = model["card"]["evaluation"]
    examples = model["card"]["dataset"]["examples"]
    return Outcome.ok(
        {
            "run_id": done["id"], "model_id": model["id"], "product_id": PRODUCT_ID,
            "uri": f"wasify://creation/lora/{model['id']}", "name": model["name"],
            "steps": done["steps"], "seconds": round(done["elapsed_s"] or 0),
            "examples": examples, "passed": verdict["passed"], "verdict": verdict["note"],
        },
        f'"{model["name"]}" was taught from {examples} examples. {verdict["note"]}',
    )  # fmt: skip


async def _start_decision(p: StartIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    store = store_for(deps.state)
    runs = decision_manager_for(deps)
    try:
        row = await runs.start(ctx.actor, str(p.decision_set_id))
    except NotFound:
        return Outcome.refused("That set of examples does not exist.", "not_found")
    except (Refused, NotAvailable) as e:
        return Outcome.refused(str(getattr(e, "message", e)), getattr(e, "code", "not_ready"))
    try:
        await runs.wait(row["id"])
    except asyncio.CancelledError:
        await runs.cancel(ctx.actor, row["id"])
        raise
    done = store.get_run(ctx.actor.tenant_id, ctx.actor.user_id, row["id"])
    if done["status"] != "done" or not done["model_id"]:
        return Outcome.error(done["error"] or "The model could not be taught.", "failed")
    model = store.get_model(ctx.actor.tenant_id, ctx.actor.user_id, done["model_id"])
    verdict = model["card"]["evaluation"]
    examples = model["card"]["dataset"]["examples"]
    return Outcome.ok(
        {
            "run_id": done["id"], "model_id": model["id"], "product_id": PRODUCT_ID,
            "uri": f"wasify://creation/lora/{model['id']}", "name": model["name"],
            "steps": done["steps"], "seconds": round(done["elapsed_s"] or 0),
            "examples": examples, "passed": verdict["passed"], "verdict": verdict["note"],
        },
        f'"{model["name"]}" was taught from {examples} examples. {verdict["note"]}',
    )  # fmt: skip


async def _start_video(p: StartIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    store = store_for(deps.state)
    runs = video_manager_for(deps)
    try:
        row = await runs.start(ctx.actor, str(p.dataset_id), p.base, p.method)
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
    return Outcome.ok(
        {
            "run_id": done["id"], "model_id": model["id"], "product_id": PRODUCT_ID,
            "uri": f"wasify://creation/lora/{model['id']}", "name": model["name"],
            "magic_word": model["trigger_word"], "steps": done["steps"],
            "seconds": round(done["elapsed_s"] or 0), "preview": False,
        },
        f'"{model["name"]}" was taught for video in about {mins} minute{"s" if mins != 1 else ""}. '
        f'Write "{model["trigger_word"]}" in a video prompt and choose it under My looks.',
    )  # fmt: skip


async def _start(p: StartIn, ctx: ActionContext) -> Outcome:
    if p.decision_set_id is not None:
        return await _start_decision(p, ctx)
    if p.set_id is not None:
        return await _start_writing(p, ctx)
    deps = need_deps(ctx)
    try:
        family = store_for(deps.state).get_dataset(
            ctx.actor.tenant_id, ctx.actor.user_id, str(p.dataset_id)
        )["family"]
    except NotFound:
        return Outcome.refused("That set of pictures does not exist.", "not_found")
    if family == "video":
        return await _start_video(p, ctx)
    engine, store = engine_for(deps.state), store_for(deps.state)
    if not engine.ready():
        return Outcome.refused(not_ready(engine), "not_ready")
    runs = run_manager_for(deps)
    try:
        row = await runs.start(ctx.actor, str(p.dataset_id), p.base, p.method)
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
    path = await folder_ready(state, ctx.actor, "models", item_id) / "adapter.safetensors"
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
                "a character, a pet, a person, a style or an object. The "
                "set is made on the Train screen: the pictures are added there, the app writes a "
                "description of each, the person chooses a magic word. This starts the run on a "
                "set that is ready and waits for it. It takes about "
                "25 minutes on a Mac and pauses chat and image making, so it is made one at a "
                "time. Then writing the magic word in a prompt draws the result. Or, with "
                "set_id, it teaches a small language model to answer the way the person's own "
                "examples do, from a set of questions and answers (made under 'Teach it from "
                "examples' on the same screen): it takes a minute or two and ends with the "
                "same questions answered before and after and a mark that says whether it "
                "learnt. Or, when the set was made under 'Make my own look or motion for video' "
                "(pictures and short clips), it teaches the video model a look, a motion or a "
                "subject: it takes about half an hour to an hour and pauses chat, image and video "
                "making, and the result is chosen under My looks on a Video screen."
            ),
            input=StartIn,
            output=StartOut,
            examples=({"dataset_id": SAMPLE_ID}, {"set_id": SAMPLE_ID}),
            effect="make",
            flags=("costly",),
            long=True,
            bind=CallBinding(_start),
            **common,
        ),
        Action(
            id="decision.decide",
            title="Decide with a model I taught",
            summary="Ask a decision model for its answer to a question about some texts.",
            description=(
                "Ask a decision model the person taught (under 'Teach it to decide' on the Train "
                "screen) to answer its question about one or more texts. The question was chosen "
                "when it was taught: yes or no ('Is this review positive?'), one of several "
                "categories ('billing, bug or other') or a score ('how angry, 1 to 5'). Each text "
                "comes back with its answer and how sure the model is, from 0 to 1, which can be "
                "trusted about as much as the model's own report says. It is quick (a second or "
                "two for a hundred texts, after the model loads) and runs on this computer. It "
                "is not for deciding about a person's job, credit or safety."
            ),
            input=DecideIn,
            output=DecideOut,
            examples=({"model_id": SAMPLE_ID, "texts": ["I was charged twice this month."]},),
            effect="read",
            flags=(),
            bind=CallBinding(_decide),
            requires=(need_product(PRODUCT_ID), DECIDER),
            product=PRODUCT_ID,
            ui="train",
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
