"""Sets to teach from, made from the chat (docs/chat-does-everything-plan.md, CE5).

`train.make_set` does what the Train screen does before its Teach button: a set of pictures from
pictures of the library (an attached photo is kept in the library first, by the chat), with the
screen's checks, its descriptions and a magic word; or a set of examples for "Teach it from
examples" or "Teach it to decide" from an attached table (CSV, or tab separated as pasted from a
spreadsheet). `train.start` then teaches from it."""

import csv
import io
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from wasifyai_platform_sdk.actions import ActionContext, ActionRefused, Outcome
from wasifyai_platform_sdk.actions.helpers import attached_document, need_deps

from wasifyai_training import decision, magic
from wasifyai_training.decisions import manager_for as decision_manager_for
from wasifyai_training.runtime import (
    MAX_PICTURES,
    Refused,
    add_picture,
    caption_manager_for,
    engine_for,
    ready_to_train,
    store_for,
    suggestions,
    word_problem,
)
from wasifyai_training.store import KINDS
from wasifyai_training.writing import manager_for as writing_manager_for

# a first row that names the columns, as the Decide screen leaves out
HEADERS = {
    "answer", "label", "category", "class", "target", "sentiment", "score", "y", "result",
    "verdict", "decision", "question", "ask", "text", "prompt", "response", "output",
}  # fmt: skip


YES_NO = {"yes", "no", "y", "n", "true", "false", "positive", "negative"}


class MakeSetIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    what: Literal["pictures", "writing", "decision"] = Field(
        "pictures",
        description="pictures: a set of pictures to teach the image model a character, style or "
        "object. writing: questions and answers to teach a writing model. decision: texts with "
        "the right answers to teach a decision model.",
    )
    name: str = Field(min_length=1, max_length=60, description="A name for the set, e.g. Marlo.")
    kind: str = Field(
        "character", max_length=12,
        description="pictures: what they show, character (a pet, a person), style or object.",
    )  # fmt: skip
    image_ids: list[str] = Field(
        default_factory=list, max_length=MAX_PICTURES,
        description="pictures: the library pictures to teach from (8 or more; 15 to 25 is "
        "best). An attached photo may be named by its attachment id.",
    )  # fmt: skip
    magic_word: str = Field(
        "", max_length=12,
        description="pictures: a made-up word of 4 to 12 letters that will draw it; left out, "
        "the app picks one.",
    )  # fmt: skip
    attachment_id: str = Field(
        "", max_length=64,
        description="writing or decision: an attached table, one example a row: the question "
        "(or text) in the first column, the answer in the last.",
    )  # fmt: skip
    question: str = Field(
        "", max_length=300,
        description="decision: the question the model answers about every text, e.g. 'Is this "
        "review positive?'",
    )  # fmt: skip

    @model_validator(mode="after")
    def _enough(self) -> "MakeSetIn":
        if self.what == "pictures":
            if not self.image_ids:
                raise ValueError("Give the pictures to teach from in image_ids.")
            if self.kind not in KINDS:
                raise ValueError("kind is character, style or object.")
        elif not self.attachment_id:
            raise ValueError("Give the attached table of examples in attachment_id.")
        if self.what == "decision" and not self.question:
            raise ValueError("Give the question the model should answer about every text.")
        return self


class MakeSetOut(BaseModel):
    what: str
    set_id: str
    name: str
    count: int  # pictures added, or usable examples
    skipped: list[str] = []  # what was left out, in words
    magic_word: str = ""
    described: int = 0  # pictures: how many got a description
    missing: str | None = None  # what stops teaching it, in words; None when it is ready


def rows_of(text: str) -> list[list[str]]:
    """The cells of a table of text, as the Decide screen reads one: tab separated (pasted from a
    spreadsheet), else comma or semicolon separated (a CSV file), quoted cells allowed. A first
    row naming the columns is left out."""
    text = text.lstrip("﻿")
    first = text.split("\n", 1)[0]
    sep = "\t" if "\t" in first else ";" if first.count(";") > first.count(",") else ","
    rows = [
        [c.strip() for c in r]
        for r in csv.reader(io.StringIO(text), delimiter=sep)
        if len(r) >= 2 and r[0].strip() and r[-1].strip()
    ]
    if rows and rows[0][-1].lower() in HEADERS and rows[0][0].lower() in HEADERS:
        rows = rows[1:]
    return rows


def _decision_question(question: str, answers: list[str]) -> dict[str, Any]:
    """The kind of question its answers show: yes or no, a score from 1, or categories."""
    low = {a.lower() for a in answers}
    if low and low <= YES_NO:
        return {"kind": "yes_no", "question": question}
    if low and all(a.isdigit() for a in low):
        top = max(int(a) for a in low)
        if decision.MIN_LEVELS <= top <= decision.MAX_LEVELS:
            return {"kind": "score", "question": question, "levels": top}
    labels = list(dict.fromkeys(a.strip() for a in answers))
    return {"kind": "category", "question": question, "options": [{"label": x} for x in labels]}


async def _pictures(p: MakeSetIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    a = ctx.actor
    engine, store = engine_for(deps.state), store_for(deps.state)
    library = ctx.library.get("image")
    if library is None or library.read is None:
        raise ActionRefused("unavailable", "Pictures of the library cannot be read here.")
    files: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    for ident in dict.fromkeys(p.image_ids):
        data = await library.read(ctx, ident)
        if data is None:
            skipped.append(f"{ident} is not a picture of the library")
            continue
        item = await library.get(ctx, ident)
        files.append((item.title if item else "picture", data))
    if not files:
        raise ActionRefused("not_found", "None of those pictures is in the library.")
    row = store.add_dataset(a.tenant_id, a.user_id, p.kind, p.name, "image")
    for title, data in files:
        try:
            await add_picture(deps, a, row["id"], title, data)
        except Refused as e:
            skipped.append(f"{title}: {e.message}")
    word = p.magic_word.lower()
    if word and (not magic.valid(word) or await word_problem(engine, word)):
        skipped.append(f'the magic word "{word}" is a poor one, so the app chose another')
        word = ""
    if not word:
        word = next(iter(await suggestions(store, a, row, engine)), "")
    row = store.update_dataset(a.tenant_id, a.user_id, row["id"], trigger_word=word)
    captions = caption_manager_for(deps)
    try:
        if await captions.start(a, row["id"]):
            await captions.wait(row["id"])
    except Refused as e:
        skipped.append(f"no descriptions: {e.message}")
    items = store.list_items(a.tenant_id, a.user_id, row["id"])
    described = sum(1 for i in items if i["caption_state"] in ("done", "edited"))
    missing = ready_to_train(row, items)
    warned = sum(1 for i in items if any(c["level"] == "warn" for c in i["checks"]))
    said = (
        f'The set "{row["name"]}" has {len(items)} pictures, {described} described; its magic '
        f'word is "{word}" (dataset_id {row["id"]}).'
    )
    if warned:
        said += f" The Train screen suggests removing {warned} of them (blurry or repeated)."
    if skipped:
        said += " Left out: " + "; ".join(skipped) + "."
    said += (
        f" Not ready yet: {missing}"
        if missing
        else " It is ready: teach it with train.start and this dataset_id (about 25 minutes)."
    )
    return Outcome.ok(
        {
            "what": "pictures", "set_id": row["id"], "name": row["name"], "count": len(items),
            "skipped": skipped, "magic_word": word, "described": described, "missing": missing,
        },
        said,
    )  # fmt: skip


async def _examples(p: MakeSetIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    a = ctx.actor
    store = store_for(deps.state)
    rows = rows_of(await attached_document(ctx, p.attachment_id))
    if not rows:
        raise ActionRefused(
            "invalid_input",
            "No examples were found in that file: put one a row, the question (or text) first "
            "and the answer last, separated by commas or tabs.",
        )
    if p.what == "writing":
        made = store.add_writing_set(a.tenant_id, a.user_id, p.name)
        store.set_examples(
            a.tenant_id, a.user_id, made["id"],
            [{"ask": r[0], "answer": r[-1]} for r in rows],
        )  # fmt: skip
        plan = writing_manager_for(deps).plan(a, made["id"])
        key = "set_id"
    else:
        made = store.add_decision_set(a.tenant_id, a.user_id, p.name)
        store.update_decision_set(
            a.tenant_id, a.user_id, made["id"],
            **_decision_question(p.question, [r[-1] for r in rows]),
        )  # fmt: skip
        store.set_decision_examples(
            a.tenant_id, a.user_id, made["id"], [{"text": r[0], "answer": r[-1]} for r in rows]
        )
        plan = decision_manager_for(deps).plan(a, made["id"])
        key = "decision_set_id"
    missing = plan["missing"] or None
    said = f'The set "{made["name"]}" has {plan["examples"]} examples ({key} {made["id"]}).'
    said += (
        f" Not ready yet: {missing}"
        if missing
        else f" It is ready: teach it with train.start and this {key} (a few minutes)."
    )
    return Outcome.ok(
        {
            "what": p.what, "set_id": made["id"], "name": made["name"],
            "count": plan["examples"], "missing": missing,
        },
        said,
    )  # fmt: skip


async def make_set(p: MakeSetIn, ctx: ActionContext) -> Outcome:
    if p.what == "pictures":
        return await _pictures(p, ctx)
    return await _examples(p, ctx)
