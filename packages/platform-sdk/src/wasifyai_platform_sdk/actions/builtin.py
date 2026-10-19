"""The actions that belong to no product: the library across products (`library.*`), what this
computer can do right now (`app.status`), and the handles of long work (`job.*`). They are written
once on the executor's own parts: the product's `LibraryKind`s, the readiness of every action, the
job book."""

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from wasifyai_platform_sdk.actions.executor import ActionContext
from wasifyai_platform_sdk.actions.library import LibraryItem, LibraryKind, creation_uri
from wasifyai_platform_sdk.actions.model import (
    PLATFORM,
    Action,
    ActionRefused,
    CallBinding,
    Outcome,
    surface_of,
)

LIBRARY_KINDS = (
    "image",
    "video",
    "speech",
    "track",
    "transcript",
    "voice",
    "lipsync",
    "notebook",
)
Kind = Literal["image", "video", "speech", "track", "transcript", "voice", "lipsync", "notebook"]
MAX_STATUS_LINES = 12
MAX_WAIT = 50.0


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _kind(ctx: ActionContext, kind: str) -> LibraryKind:
    found = ctx.library.get(kind)
    if found is None:
        raise ActionRefused("unavailable", f"This computer does not keep {kind} creations.")
    return found


def _item_out(item: LibraryItem) -> dict[str, Any]:
    return {**item.model_dump(), "uri": item.uri}


class ItemOut(BaseModel):
    kind: str
    id: str
    uri: str
    title: str
    created_at: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


# ---- library.search ---------------------------------------------------------------------------


class SearchIn(Strict):
    query: str = Field(min_length=1, max_length=200, description="What to look for.")
    limit: int = Field(6, ge=1, le=12, description="How many results at most.")


class Hit(BaseModel):
    kind: str
    product_id: str
    id: str
    uri: str
    text: str | None = None  # what it is about: the words an image was made from, a title


class SearchOut(BaseModel):
    results: list[Hit]


async def _search(p: SearchIn, ctx: ActionContext) -> Outcome:
    query = p.query.strip()
    if not query:
        return Outcome.error("There was nothing to search for.", "empty")
    hits = await ctx.host.search_creations(query, p.limit)
    results = [{**h, "uri": creation_uri(h["kind"], h["id"])} for h in hits]
    if not hits:
        return Outcome.ok({"results": []}, "Nothing matched in the person's library.")
    lines = [f"- {h['kind']}: {h.get('text') or h['id']}" for h in hits]
    return Outcome.ok(
        {"results": results},
        f"Found {len(hits)} in the person's library:\n" + "\n".join(lines),
    )


# ---- library.list / get / export / rename / delete --------------------------------------------


class ListIn(Strict):
    kind: Kind = Field(description="Which sort of creation to list.")
    limit: int = Field(20, ge=1, le=50)


class ListOut(BaseModel):
    items: list[ItemOut]


async def _list(p: ListIn, ctx: ActionContext) -> Outcome:
    items = await _kind(ctx, p.kind).list(ctx, p.limit)
    if not items:
        return Outcome.ok({"items": []}, f"There are no {p.kind} creations yet.")
    lines = [f"- {i.title or i.id}" for i in items]
    return Outcome.ok(
        {"items": [_item_out(i) for i in items]}, f"{len(items)} found:\n" + "\n".join(lines)
    )


class RefIn(Strict):
    kind: Kind
    id: str = Field(min_length=1, max_length=64, description="The id from a search or a list.")


class GetOut(BaseModel):
    item: ItemOut


async def _get(p: RefIn, ctx: ActionContext) -> Outcome:
    item = await _kind(ctx, p.kind).get(ctx, p.id)
    if item is None:
        return Outcome.refused("That is not in the library.", "not_found")
    return Outcome.ok({"item": _item_out(item)}, f'"{item.title or item.id}" ({p.kind}).')


class ExportOut(BaseModel):
    name: str
    path: str


async def _export(p: RefIn, ctx: ActionContext) -> Outcome:
    kind = _kind(ctx, p.kind)
    folder = getattr(getattr(ctx.deps, "state", None), "export_dir", None)
    if kind.export is None or folder is None:
        return Outcome.refused("Saving to a folder is not available here.", "unavailable")
    from pathlib import Path

    written = await kind.export(ctx, p.id, Path(folder))
    if written is None:
        return Outcome.refused("That is not in the library.", "not_found")
    return Outcome.ok(
        {"name": written.name, "path": str(written)},
        f"A copy was saved as {written.name} in the export folder.",
    )


class RenameIn(RefIn):
    title: str = Field(min_length=1, max_length=200, description="The new name.")


async def _rename(p: RenameIn, ctx: ActionContext) -> Outcome:
    kind = _kind(ctx, p.kind)
    if kind.rename is None:
        return Outcome.refused(f"A {kind.noun} has no name to change.", "cannot_rename")
    if not await kind.rename(ctx, p.id, p.title.strip()):
        return Outcome.refused("That is not in the library.", "not_found")
    item = await kind.get(ctx, p.id)
    out = {"item": _item_out(item)} if item else {"item": {"kind": p.kind, "id": p.id}}
    return Outcome.ok(
        out | {"item": out["item"] | {"uri": creation_uri(p.kind, p.id), "title": p.title.strip()}},
        f'It is now called "{p.title.strip()}".',
    )


class DeleteOut(BaseModel):
    deleted: bool
    kind: str
    id: str


async def _delete(p: RefIn, ctx: ActionContext) -> Outcome:
    if not await _kind(ctx, p.kind).delete(ctx, p.id):
        return Outcome.refused("That is not in the library.", "not_found")
    return Outcome.ok({"deleted": True, "kind": p.kind, "id": p.id}, "It was deleted.")


# ---- app.status -------------------------------------------------------------------------------


class StatusIn(Strict):
    domain: str | None = Field(
        None, max_length=20, description="Only the actions of one area, for example 'speech'."
    )


class ActionState(BaseModel):
    id: str
    state: Literal["ready", "needs_setup", "unavailable"]
    step: str = ""
    reason: str = ""


class StatusOut(BaseModel):
    actions: list[ActionState]
    facts: dict[str, Any] = Field(default_factory=dict)


async def _status(p: StatusIn, ctx: ActionContext) -> Outcome:
    surface = surface_of(ctx.origin)
    pool = ctx.registry.for_surface(surface) if surface else ctx.registry.all()
    rows: list[ActionState] = []
    for action in pool:
        if p.domain and action.domain != p.domain:
            continue
        ready = await ctx.executor.readiness(action)
        rows.append(
            ActionState(id=action.id, state=ready.state, step=ready.step, reason=ready.reason)
        )
    not_ready = [r for r in rows if r.state != "ready"]
    lines = [
        f"- {r.id}: {r.step or r.reason}" for r in not_ready[:MAX_STATUS_LINES]
    ]  # a small model reads this: keep it short
    more = len(not_ready) - len(lines)
    text = f"{len(rows) - len(not_ready)} of {len(rows)} actions are ready here."
    if lines:
        text += " Not ready:\n" + "\n".join(lines)
        if more > 0:
            text += f"\n...and {more} more."
    return Outcome.ok(
        {
            "actions": [r.model_dump(exclude_defaults=False) for r in rows],
            "facts": ctx.host.facts(),
        },
        text,
    )


# ---- job.* ------------------------------------------------------------------------------------


class JobIn(Strict):
    job_id: str = Field(min_length=1, max_length=64)


class JobWaitIn(JobIn):
    seconds: float = Field(25, ge=0, le=MAX_WAIT, description="How long to wait at most.")


class JobOut(BaseModel):
    job_id: str
    action: str
    status: Literal["running", "ok", "refused", "error", "cancelled", "unknown"]
    seconds: float | None = None
    progress: dict[str, Any] | None = None
    result: dict[str, Any] | None = None  # the action's own result, once it has ended


def _job_out(job: Any) -> Outcome:
    out: dict[str, Any] = {"job_id": job.id, "action": job.action_id, "status": job.status}
    out["seconds"] = job.seconds
    if job.progress:
        out["progress"] = job.progress
    if job.result is not None:
        out["result"] = job.result.model_dump(mode="json", exclude_none=True)
        return Outcome.ok(out, job.result.text or f"Job {job.id} ended: {job.status}.")
    pct = job.progress.get("progress") if job.progress else None
    more = f" About {round(float(pct) * 100)} percent done." if pct else ""
    return Outcome.ok(
        out, f"Job {job.id} ({job.action_id}) is still running after {job.seconds:.0f} s.{more}"
    )


async def _remembered(p: JobIn, ctx: ActionContext) -> Outcome:
    """A job the book does not hold (the app restarted): what the audit log last saw of it."""
    seen = await ctx.executor.audit.last_for_job(ctx.actor.tenant_id, ctx.actor.user_id, p.job_id)
    if seen is None:
        return Outcome.refused("There is no such job.", "unknown_job")
    ended = seen.status in ("ok", "refused", "error")
    text = (
        f"Job {p.job_id} ended: {seen.status}. Look in the library for what it made."
        if ended
        else f"Job {p.job_id} was running when the app last closed; it may not have finished. "
        "Look in the library."
    )
    return Outcome.ok(
        {
            "job_id": p.job_id,
            "action": seen.action_id,
            "status": seen.status if ended else "unknown",
        },
        text,
    )


async def _job_status(p: JobIn, ctx: ActionContext) -> Outcome:
    job = ctx.jobs.get(ctx.actor.tenant_id, ctx.actor.user_id, p.job_id)
    return _job_out(job) if job else await _remembered(p, ctx)


async def _job_wait(p: JobWaitIn, ctx: ActionContext) -> Outcome:
    job = ctx.jobs.get(ctx.actor.tenant_id, ctx.actor.user_id, p.job_id)
    if job is None:
        return await _remembered(p, ctx)
    await ctx.jobs.wait(job, p.seconds)
    return _job_out(job)


async def _job_cancel(p: JobIn, ctx: ActionContext) -> Outcome:
    job = ctx.jobs.get(ctx.actor.tenant_id, ctx.actor.user_id, p.job_id)
    if job is None:
        return await _remembered(p, ctx)
    if job.status != "running":
        return _job_out(job)
    if not await ctx.executor.cancel_job(job):
        return Outcome.refused(
            f"Job {job.id} cannot be stopped once it has started. It will finish and be saved to "
            "the library; the person can delete it there.",
            "not_cancellable",
        )
    await asyncio.sleep(0)
    return _job_out(job)


def builtin_actions() -> list[Action]:
    return [
        Action(
            id="library.search", title="Search my creations",
            summary="Find things the person made earlier by what they were about.",
            description=(
                "Find things the person made earlier (images, videos, songs, speech, transcripts, "
                "voices, notebooks) by what they were about. It names the things it finds but "
                "does not read inside documents: to learn what their documents say, use "
                "notebook.search. Returns kind, id and a short text for each."
            ),
            input=SearchIn, output=SearchOut,
            examples=({"query": "the song I made about the rain"},),
            effect="read", flags=("private",), bind=CallBinding(_search), product=PLATFORM,
            ui="library",
        ),
        Action(
            id="library.list", title="List my creations",
            summary="List the newest creations of one kind.",
            description=(
                "List the newest creations of one kind (image, video, speech, track, transcript, "
                "voice, lipsync, notebook). Use library.search to find something by what it is "
                "about. Returns kind, id, title and small facts for each."
            ),
            input=ListIn, output=ListOut, examples=({"kind": "image", "limit": 5},),
            effect="read", flags=("private",), bind=CallBinding(_list), ui="library",
        ),
        Action(
            id="library.get", title="Look at one creation",
            summary="Show what is known about one creation.",
            description="Get one creation by kind and id: its title, its date and its size.",
            input=RefIn, output=GetOut, examples=({"kind": "track", "id": "0b7c1f9e"},),
            effect="read", flags=("private",), bind=CallBinding(_get), ui="library",
        ),
        Action(
            id="library.export", title="Save a copy to a folder",
            summary="Copy a creation into the export folder.",
            description=(
                "Copy a creation out of the library into the person's export folder and return "
                "the file's name and path. It never replaces a file. This is the only way a file "
                "leaves the library."
            ),
            input=RefIn, output=ExportOut, examples=({"kind": "image", "id": "0b7c1f9e"},),
            effect="change", flags=("private",), bind=CallBinding(_export), ui="library",
        ),
        Action(
            id="library.rename", title="Rename a creation",
            summary="Give a creation a new name.",
            description=(
                "Change the name of a creation that has one (a song, a transcript, a voice, a "
                "notebook, a talking video). Images, videos and speech have no name to change."
            ),
            input=RenameIn, output=GetOut,
            examples=({"kind": "track", "id": "0b7c1f9e", "title": "Rain song"},),
            effect="change", flags=("private",), bind=CallBinding(_rename), ui="library",
        ),
        Action(
            id="library.delete", title="Delete a creation",
            summary="Delete a creation and its files for good.",
            description=(
                "Delete one creation and its files. It cannot be undone, so the person is always "
                "asked in the app first."
            ),
            input=RefIn, output=DeleteOut, examples=({"kind": "image", "id": "0b7c1f9e"},),
            effect="destroy", flags=("private",), bind=CallBinding(_delete), ui="library",
        ),
        Action(
            id="app.status", title="What this computer can do",
            summary="Which actions are ready, which need a step, which cannot run here.",
            description=(
                "What this computer can do right now: for each action ready, needs_setup (with "
                "the step that fixes it) or unavailable (with the reason), and small facts such "
                "as free disk. Call it before telling a person how to do something, so the answer "
                "says what is missing."
            ),
            input=StatusIn, output=StatusOut, examples=({}, {"domain": "speech"}),
            effect="read", bind=CallBinding(_status),
            ui_exempt="It answers a question and is not a screen: screens show their own state.",
        ),
        Action(
            id="job.status", title="Check a long job",
            summary="How a job that was started earlier is going.",
            description="The status of a job: the job_id an action returned while it was running.",
            input=JobIn, output=JobOut, examples=({"job_id": "a1b2c3d4e5f60718"},),
            effect="read", bind=CallBinding(_job_status),
            ui_exempt="A job is shown where it was started: on its card or its screen.",
        ),
        Action(
            id="job.wait", title="Wait for a long job",
            summary="Wait a little while for a job to end.",
            description=(
                "Wait up to a number of seconds (at most 50) for a job to end, then give its "
                "status or its result. If it is still running, call it again."
            ),
            input=JobWaitIn, output=JobOut,
            examples=({"job_id": "a1b2c3d4e5f60718", "seconds": 25},),
            effect="read", bind=CallBinding(_job_wait),
            ui_exempt="A job is shown where it was started: on its card or its screen.",
        ),
        Action(
            id="job.cancel", title="Stop a long job",
            summary="Stop a job that can still be stopped.",
            description=(
                "Stop a job. Work that already runs as a product's own run cannot be stopped: "
                "it finishes and is saved to the library. The answer says which it was."
            ),
            input=JobIn, output=JobOut, examples=({"job_id": "a1b2c3d4e5f60718"},),
            effect="change", bind=CallBinding(_job_cancel),
            ui_exempt="A job is shown where it was started: on its card or its screen.",
        ),
    ]  # fmt: skip
