"""What Meetings can do, for the action catalogue (ADR-0068, ADR-0108 decision 18): make a meeting
from a recording of the library, name a speaker, and meetings as a kind of creation (list, look at,
rename, delete, save as text, read).

Recording (MT2) adds making a meeting from a recording the app made (the window starts and stops
the recording itself: the microphone and the computer's sound are the shell's, never the engine's).
People (MT3) adds the people the app knows, renaming and forgetting one; naming a speaker makes them
a person. Reports (MT4) add writing a report, keeping a template of one's own, and deleting a
report.
Asking (MT5) adds a meeting to a notebook and asks about one, through the notebooks' own actions."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk.actions import (
    CHAT,
    NOTEBOOKS,
    Action,
    ActionContext,
    ActionRefused,
    CallBinding,
    LibraryItem,
    LibraryKind,
    Outcome,
    need_model,
    need_product,
    need_runtime,
)
from wasifyai_platform_sdk.actions.helpers import need_deps

from wasifyai_meetings import asking, people, reports
from wasifyai_meetings.runtime import (
    KIND,
    PRODUCT_ID,
    Refused,
    add_to_search,
    asking_for,
    delete_meeting,
    manager_for,
    recording_in,
    reports_for,
    root_for,
    store_for,
    waiting_recordings,
)
from wasifyai_meetings.store import NotFound

SAMPLE_ID = "5d1c0e7a-0000-4000-8000-000000000000"
OUTPUT_TEXT_CHARS = 6000


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MakeIn(Strict):
    source_kind: Literal["track", "speech"] = Field(
        "track",
        description="Whether the recording is a track (an imported or made sound) or a speech.",
    )
    source_id: str = Field(min_length=1, max_length=64, description="The id of the recording.")
    title: str = Field("", max_length=200, description="A name for the meeting.")
    language: str = Field(
        "", max_length=20,
        description="The language spoken (en, bn, hi ...), when the chosen speech model needs it.",
    )  # fmt: skip


class RecordedIn(Strict):
    name: str = Field(
        "", max_length=80,
        description="The recording's name (rec-....wav); empty takes the newest one waiting.",
    )  # fmt: skip
    title: str = Field("", max_length=200, description="A name for the meeting.")
    language: str = Field(
        "", max_length=20,
        description="The language spoken (en, de ...), when the chosen speech model needs it.",
    )  # fmt: skip


class SpeakerOut(BaseModel):
    key: str
    name: str
    seconds: float


class MeetingOut(BaseModel):
    meeting_id: str
    uri: str
    title: str
    seconds: float
    speakers: list[SpeakerOut]
    text: str  # the start of the transcript, with the speakers' names
    truncated: bool = False


class NameIn(Strict):
    meeting_id: str = Field(min_length=32, max_length=32)
    speaker: str = Field(
        min_length=2, max_length=4, description='The speaker\'s key in the meeting: "S1", "S2" ...'
    )
    name: str = Field(max_length=80, description="Their name; empty gives back Speaker N.")


class NameOut(BaseModel):
    meeting_id: str
    speakers: list[SpeakerOut]


class Empty(Strict):
    pass


class PersonOut(BaseModel):
    person_id: str
    name: str
    meetings: int  # how many meetings they were named in
    voices: int  # how many voiceprints of them are kept


class PeopleOut(BaseModel):
    people: list[PersonOut]


class RenamePersonIn(Strict):
    person_id: str = Field(min_length=32, max_length=32)
    name: str = Field(min_length=1, max_length=80)


class ForgetIn(Strict):
    person_id: str = Field(min_length=32, max_length=32)


class ForgetOut(BaseModel):
    forgotten: bool


class ReportIn(Strict):
    meeting_id: str = Field(min_length=32, max_length=32)
    template: str = Field(
        "summary", min_length=1, max_length=64,
        description=(
            "Which report: summary, minutes, actions, decisions, standup, sales, or the id of "
            "the person's own template (own-...)."
        ),
    )  # fmt: skip


class ReportOut(BaseModel):
    report_id: str
    meeting_id: str
    title: str
    text: str


class TemplateIn(Strict):
    title: str = Field(min_length=1, max_length=80, description="The template's name.")
    instructions: str = Field(
        min_length=1, max_length=4000, description="What the report says, in plain words."
    )


class TemplateOut(BaseModel):
    template_id: str
    title: str


class DeleteReportIn(Strict):
    report_id: str = Field(min_length=32, max_length=32)


class DeleteReportOut(BaseModel):
    deleted: bool


class ToNotebookIn(Strict):
    meeting_id: str = Field(min_length=32, max_length=32)
    notebook_id: str = Field(
        "", max_length=64,
        description="The notebook to add it to (notebook.list gives ids); empty makes a new one.",
    )  # fmt: skip
    title: str = Field(
        "", max_length=200, description="The new notebook's name; empty uses the meeting's title."
    )


class ToNotebookOut(BaseModel):
    meeting_id: str
    notebook_id: str
    notebook_title: str
    document_id: str


class AskIn(Strict):
    meeting_id: str = Field(min_length=32, max_length=32)
    question: str = Field(min_length=1, max_length=4000)


class AskOut(BaseModel):
    meeting_id: str
    question_id: str
    reply: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    notebook_id: str


def _uri(item: str) -> str:
    return f"wasify://creation/{KIND}/{item}"


def _speakers(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": s["key"], "name": s["name"], "seconds": s["seconds"]} for s in row["speakers"]]


async def _make(p: MakeIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    kind = ctx.library.get(p.source_kind)
    if kind is None or kind.read is None:
        return Outcome.refused("Recordings cannot be read here.", "unavailable")
    data = await kind.read(ctx, p.source_id)
    if data is None:
        return Outcome.refused("That recording is not in the library.", "not_found")
    jobs = manager_for(deps)
    got = await kind.get(ctx, p.source_id)
    name = (got.title if got else "") or "Recording"

    def keep(data: bytes) -> Path:
        incoming = root_for(deps.state) / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=incoming, suffix=".audio")
        with open(fd, "wb") as f:
            f.write(data)
        return Path(tmp)

    src = await asyncio.to_thread(keep, data)
    del data
    try:
        row = await jobs.start(
            ctx.actor, src, title=(p.title or name)[:200], source_name=name[:200],
            language=p.language,
        )  # fmt: skip
    except Refused as e:
        await asyncio.to_thread(src.unlink, True)
        return Outcome.refused(e.message, e.code)
    return await _finish(ctx, row)


async def _finish(ctx: ActionContext, row: dict[str, Any]) -> Outcome:
    """Wait for the meeting being made and tell what came of it."""
    deps = need_deps(ctx)
    jobs = manager_for(deps)
    try:
        await jobs.wait(row["id"])
    except asyncio.CancelledError:
        await jobs.cancel(row["id"])
        raise
    done = store_for(deps.state).get(ctx.actor.tenant_id, ctx.actor.user_id, row["id"])
    if done["status"] != "done":
        return Outcome.error(done["error"] or "The meeting could not be made.", "failed")
    text = done["text"]
    who = ", ".join(f"{s['name']} ({round(s['seconds'] / 60, 1)} min)" for s in done["speakers"])
    return Outcome.ok(
        {
            "meeting_id": done["id"], "uri": _uri(done["id"]), "title": done["title"],
            "seconds": float(done["seconds"] or 0), "speakers": _speakers(done),
            "text": text[:OUTPUT_TEXT_CHARS], "truncated": len(text) > OUTPUT_TEXT_CHARS,
        },
        f'The meeting "{done["title"]}" is in Meetings. {len(done["speakers"])} speaker'
        f'{"s" if len(done["speakers"]) != 1 else ""} were told apart: {who}. '
        "Their names can be given on the meeting's page.\n" + text[:OUTPUT_TEXT_CHARS],
    )  # fmt: skip


def _recording(state: Any, name: str) -> Path | None:
    if name:
        return recording_in(state, name)
    waiting = waiting_recordings(state)
    return recording_in(state, waiting[0]["name"]) if waiting else None


async def _make_recorded(p: RecordedIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    src = await asyncio.to_thread(_recording, deps.state, p.name)
    if src is None:
        return Outcome.refused(
            "There is no recording waiting. Record one in Meetings › Record.", "not_found"
        )
    try:
        row = await manager_for(deps).start(
            ctx.actor, src, title=(p.title or "Recorded meeting")[:200], source_name=src.name,
            language=p.language, recorded=True,
        )  # fmt: skip
    except Refused as e:  # the recording stays
        return Outcome.refused(e.message, e.code)
    return await _finish(ctx, row)


async def _check_recorded(p: RecordedIn, ctx: ActionContext) -> None:
    deps = need_deps(ctx)
    if await asyncio.to_thread(_recording, deps.state, p.name) is None:
        raise ActionRefused(
            "not_found", "There is no recording waiting. Record one in Meetings › Record."
        )
    if manager_for(deps).busy(ctx.actor):
        raise ActionRefused("busy", "A meeting is being made. Wait for it to finish.")


async def _check_make(p: MakeIn, ctx: ActionContext) -> None:
    kind = ctx.library.get(p.source_kind)
    if kind is None or await kind.get(ctx, p.source_id) is None:
        raise ActionRefused("not_found", "That recording is not in the library.")
    if manager_for(need_deps(ctx)).busy(ctx.actor):
        raise ActionRefused("busy", "A meeting is being made. Wait for it to finish.")


async def _name(p: NameIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    try:
        row = await asyncio.to_thread(
            people.name_speaker, store_for(deps.state), ctx.actor.tenant_id, ctx.actor.user_id,
            p.meeting_id, p.speaker, p.name,
        )  # fmt: skip
    except NotFound:
        return Outcome.refused("That meeting or speaker is not there.", "not_found")
    await add_to_search(deps.state, ctx.actor, row)
    named = next(s for s in row["speakers"] if s["key"] == p.speaker)
    return Outcome.ok(
        {"meeting_id": row["id"], "speakers": _speakers(row)},
        f'{p.speaker} of "{row["title"]}" is now called {named["name"]}. Their voice is kept '
        "in People, to suggest them in later meetings.",
    )


async def _people(p: Empty, ctx: ActionContext) -> Outcome:
    store = store_for(need_deps(ctx).state)
    rows = await asyncio.to_thread(store.people, ctx.actor.tenant_id, ctx.actor.user_id)
    out = [
        {"person_id": r["id"], "name": r["name"], "meetings": int(r["meetings"] or 0),
         "voices": int(r["voices"] or 0)}
        for r in rows
    ]  # fmt: skip
    said = ", ".join(f"{r['name']} ({r['meetings']} meetings)" for r in out) or "nobody yet"
    return Outcome.ok({"people": out}, f"People the app knows: {said}.")


async def _reindex(ctx: ActionContext, items: list[str]) -> None:
    deps = need_deps(ctx)
    for item in items:
        try:
            row = store_for(deps.state).get(ctx.actor.tenant_id, ctx.actor.user_id, item)
        except NotFound:
            continue
        await add_to_search(deps.state, ctx.actor, row)


async def _rename_person(p: RenamePersonIn, ctx: ActionContext) -> Outcome:
    store = store_for(need_deps(ctx).state)
    try:
        changed = await asyncio.to_thread(
            people.rename_person, store, ctx.actor.tenant_id, ctx.actor.user_id, p.person_id,
            p.name,
        )  # fmt: skip
    except NotFound:
        return Outcome.refused("That person is not in People.", "not_found")
    await _reindex(ctx, changed)
    return Outcome.ok(
        {"people": []}, f"They are now called {p.name.strip()} in {len(changed)} meetings."
    )


async def _forget(p: ForgetIn, ctx: ActionContext) -> Outcome:
    store = store_for(need_deps(ctx).state)
    try:
        changed = await asyncio.to_thread(
            people.forget_person, store, ctx.actor.tenant_id, ctx.actor.user_id, p.person_id
        )
    except NotFound:
        return Outcome.refused("That person is not in People.", "not_found")
    await _reindex(ctx, changed)
    return Outcome.ok(
        {"forgotten": True},
        "They and every voiceprint of them are deleted. Meetings keep the name as words.",
    )


async def _report(p: ReportIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    store = store_for(deps.state)
    try:
        template = reports.template_for(store, ctx.actor, p.template)
    except NotFound:
        return Outcome.refused("There is no such template.", "not_found")
    try:
        store.get(ctx.actor.tenant_id, ctx.actor.user_id, p.meeting_id)
        jobs = reports_for(deps)
        row = jobs.start(ctx.actor, p.meeting_id, template)
    except NotFound:
        return Outcome.refused("That meeting is not there.", "not_found")
    except reports.Refused as e:
        return Outcome.refused(e.message, e.code)
    try:
        await jobs.wait(row["id"])
    except asyncio.CancelledError:
        await jobs.cancel(row["id"])
        raise
    done = store.report(ctx.actor.tenant_id, ctx.actor.user_id, row["id"])
    if done["status"] != "done":
        return Outcome.error(done["error"] or "The report could not be written.", "failed")
    text = done["text"]
    return Outcome.ok(
        {"report_id": done["id"], "meeting_id": p.meeting_id, "title": done["title"],
         "text": text[:OUTPUT_TEXT_CHARS]},
        f'The {done["title"].lower()} is on the meeting\'s page.\n' + text[:OUTPUT_TEXT_CHARS],
    )  # fmt: skip


async def _check_report(p: ReportIn, ctx: ActionContext) -> None:
    deps = need_deps(ctx)
    try:
        row = store_for(deps.state).get(ctx.actor.tenant_id, ctx.actor.user_id, p.meeting_id)
    except NotFound:
        raise ActionRefused("not_found", "That meeting is not there.") from None
    if row["status"] != "done":
        raise ActionRefused("not_ready", "The meeting is not made yet.")
    if reports_for(deps).busy(ctx.actor):
        raise ActionRefused("busy", "A report is being written. Wait for it to finish.")


async def _template(p: TemplateIn, ctx: ActionContext) -> Outcome:
    store = store_for(need_deps(ctx).state)
    t = store.add_template(ctx.actor.tenant_id, ctx.actor.user_id, p.title, p.instructions)
    return Outcome.ok(
        {"template_id": t["id"], "title": t["title"]},
        f'The template "{t["title"]}" is kept; write a report with it (template {t["id"]}).',
    )


async def _delete_report(p: DeleteReportIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    store = store_for(deps.state)
    try:
        r = store.report(ctx.actor.tenant_id, ctx.actor.user_id, p.report_id)
    except NotFound:
        return Outcome.refused("That report is not there.", "not_found")
    await reports_for(deps).cancel(p.report_id)
    store.delete_report(ctx.actor.tenant_id, ctx.actor.user_id, p.report_id)
    await _reindex(ctx, [r["meeting_id"]])
    return Outcome.ok({"deleted": True}, f'The report "{r["title"]}" is deleted.')


async def _check_meeting(p: Any, ctx: ActionContext) -> None:
    try:
        row = store_for(need_deps(ctx).state).get(
            ctx.actor.tenant_id, ctx.actor.user_id, p.meeting_id
        )
    except NotFound:
        raise ActionRefused("not_found", "That meeting is not there.") from None
    if row["status"] != "done":
        raise ActionRefused("not_ready", "The meeting is not made yet.")


async def _to_notebook(p: ToNotebookIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    try:
        got = await asking.add_to_notebook(
            deps, store_for(deps.state), ctx.actor, p.meeting_id, notebook_id=p.notebook_id,
            title=p.title,
        )  # fmt: skip
    except NotFound:
        return Outcome.refused("That meeting is not there.", "not_found")
    except asking.Refused as e:
        return Outcome.refused(e.message, e.code)
    return Outcome.ok(
        {"meeting_id": p.meeting_id, **got},
        f'The meeting is a source of the notebook "{got["notebook_title"]}" now. It is being '
        "read; then it can be asked about there with the other sources (notebook.ask).",
    )


async def _check_ask(p: AskIn, ctx: ActionContext) -> None:
    await _check_meeting(p, ctx)
    if asking_for(need_deps(ctx)).busy(ctx.actor):
        raise ActionRefused("busy", "A question is being answered. Wait for it to finish.")


async def _ask(p: AskIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    jobs = asking_for(deps)
    try:
        q = jobs.start(ctx.actor, p.meeting_id, p.question)
    except NotFound:
        return Outcome.refused("That meeting is not there.", "not_found")
    except asking.Refused as e:
        return Outcome.refused(e.message, e.code)
    try:
        await jobs.wait(q["id"])
    except asyncio.CancelledError:
        await jobs.cancel(q["id"])
        raise
    done = store_for(deps.state).question(ctx.actor.tenant_id, ctx.actor.user_id, q["id"])
    if done["status"] != "done":
        return Outcome.error(done["error"] or "The question could not be answered.", "failed")
    return Outcome.ok(
        {"meeting_id": p.meeting_id, "question_id": done["id"], "reply": done["reply"],
         "citations": done["citations"], "notebook_id": done["notebook_id"]},
        "The answer, from the meeting's transcript, with [n] pointing at its lines:\n"
        + done["reply"],
    )  # fmt: skip


# ---- meetings as a kind of creation -------------------------------------------------------------


def _item(row: dict[str, Any]) -> LibraryItem:
    return LibraryItem(
        kind=KIND, id=row["id"], title=row["title"][:120], created_at=row["created_at"],
        detail={"status": row["status"], "seconds": row["seconds"],
                "speakers": [s["name"] for s in row["speakers"]]},
    )  # fmt: skip


async def _list(ctx: ActionContext, limit: int) -> list[LibraryItem]:
    deps = need_deps(ctx)
    rows = await asyncio.to_thread(
        store_for(deps.state).list_meetings, ctx.actor.tenant_id, ctx.actor.user_id, None, limit
    )
    return [_item(r) for r in rows if r["status"] == "done"]


async def _get(ctx: ActionContext, item_id: str) -> LibraryItem | None:
    try:
        row = store_for(need_deps(ctx).state).get(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    except NotFound:
        return None
    return _item(row)


async def _delete(ctx: ActionContext, item_id: str) -> bool:
    return await delete_meeting(need_deps(ctx), ctx.actor, item_id)


async def _rename(ctx: ActionContext, item_id: str, name: str) -> bool:
    deps = need_deps(ctx)
    try:
        row = store_for(deps.state).rename(ctx.actor.tenant_id, ctx.actor.user_id, item_id, name)
    except NotFound:
        return False
    await add_to_search(deps.state, ctx.actor, row)
    return True


async def _read(ctx: ActionContext, item_id: str) -> bytes | None:
    """The transcript with the speakers' names, as text."""
    try:
        row = store_for(need_deps(ctx).state).get(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    except NotFound:
        return None
    if row["status"] != "done":
        return None
    written = store_for(need_deps(ctx).state).reports_of(
        ctx.actor.tenant_id, ctx.actor.user_id, item_id
    )
    extra = "".join(f"\n\n{r['title']}\n\n{r['text']}" for r in written if r["status"] == "done")
    return f"{row['title']}\n\n{row['text']}{extra}\n".encode()


async def _export(ctx: ActionContext, item_id: str, folder: Path) -> Path | None:
    data = await _read(ctx, item_id)
    if data is None:
        return None
    row = store_for(need_deps(ctx).state).get(ctx.actor.tenant_id, ctx.actor.user_id, item_id)
    stem = "".join(c if c.isalnum() or c in " -_" else "_" for c in row["title"]).strip()
    stem = stem[:80] or "Meeting"

    def write() -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path, n = folder / f"{stem}.txt", 1
        while path.exists():
            n += 1
            path = folder / f"{stem} ({n}).txt"
        path.write_bytes(data)
        return path

    return await asyncio.to_thread(write)


def actions() -> list[Action]:
    return [
        Action(
            id="meetings.make",
            title="Make a meeting from a recording",
            summary="Write down a recording and tell its speakers apart, as a meeting.",
            description=(
                "Make a meeting from a recording of the library (a track or a speech): it is "
                "written down with the chosen speech-to-text model and its speakers are told apart "
                "on this computer (up to 4 in one recording), then kept in Meetings and in search. "
                "It takes about a minute for every 20 minutes of recording. The speakers are "
                "called Speaker 1, Speaker 2 ... until a person names them "
                "(meetings.name_speaker). "
                "Returns the speakers, how long each spoke, and the start of the transcript."
            ),
            input=MakeIn,
            output=MeetingOut,
            examples=({"source_kind": "track", "source_id": SAMPLE_ID},),
            effect="make",
            requires=(need_product(PRODUCT_ID), need_runtime("meetings"), need_model("transcribe")),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_make, check=_check_make),
            ui="meetings.list",
        ),
        Action(
            id="meetings.make_recorded",
            title="Make a meeting from a recording made in the app",
            summary="Make a meeting from a recording of Meetings › Record that is waiting.",
            description=(
                "Make a meeting from a recording made in Meetings › Record that was not made into "
                "one yet (the window was closed, or the speaker model was missing). The person "
                "starts and stops recording themselves in the app; this cannot record. The "
                "microphone is the speaker You and the computer's sound is split into Speaker 2, "
                "3 ... Without a name the newest waiting recording is used. Returns the speakers "
                "and the start of the transcript."
            ),
            input=RecordedIn,
            output=MeetingOut,
            examples=({}, {"name": "rec-1763300000-0a1b2c3d.wav", "title": "Stand-up"}),
            effect="make",
            requires=(need_product(PRODUCT_ID), need_runtime("meetings"), need_model("transcribe")),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_make_recorded, check=_check_recorded),
            ui="meetings.record",
        ),
        Action(
            id="meetings.name_speaker",
            title="Name a speaker",
            summary="Give a speaker of a meeting a name.",
            description=(
                "Give one speaker of a meeting their name. They become that person in People "
                "(one already there with the name, or a new one) and their voice is kept, so "
                "later meetings suggest them. Use it when the person says who a speaker is; never "
                "guess a name from what was said. An empty name gives back Speaker N."
            ),
            input=NameIn,
            output=NameOut,
            examples=({"meeting_id": "0" * 32, "speaker": "S1", "name": "Asha"},),
            effect="change",
            requires=(need_product(PRODUCT_ID), need_runtime("meetings")),
            product=PRODUCT_ID,
            bind=CallBinding(_name),
            ui="meetings.list",
        ),
        Action(
            id="meetings.people",
            title="List the people of meetings",
            summary="The people Meetings knows by voice.",
            description=(
                "The people named in meetings: each with how many meetings they were named in "
                "and how many voiceprints of them are kept. A speaker of a later meeting is "
                "suggested as one of them; the person confirms."
            ),
            input=Empty,
            output=PeopleOut,
            examples=({},),
            effect="read",
            requires=(need_product(PRODUCT_ID), need_runtime("meetings")),
            product=PRODUCT_ID,
            bind=CallBinding(_people),
            ui="meetings.people",
        ),
        Action(
            id="meetings.rename_person",
            title="Rename a person",
            summary="Give a person of People a new name, in every meeting.",
            description=(
                "Change a person's name in People and in every meeting they were named in "
                "(meetings.people gives their id)."
            ),
            input=RenamePersonIn,
            output=PeopleOut,
            examples=({"person_id": "0" * 32, "name": "Asha Rahman"},),
            effect="change",
            requires=(need_product(PRODUCT_ID), need_runtime("meetings")),
            product=PRODUCT_ID,
            bind=CallBinding(_rename_person),
            ui="meetings.people",
        ),
        Action(
            id="meetings.forget_person",
            title="Forget a person",
            summary="Delete a person and every voiceprint of them.",
            description=(
                "Delete a person from People with every voiceprint of them and all that was "
                "learnt of their voice. Meetings keep their name as words. Always asks the "
                "person."
            ),
            input=ForgetIn,
            output=ForgetOut,
            examples=({"person_id": "0" * 32},),
            effect="destroy",
            requires=(need_product(PRODUCT_ID), need_runtime("meetings")),
            product=PRODUCT_ID,
            bind=CallBinding(_forget),
            ui="meetings.people",
        ),
        Action(
            id="meetings.write_report",
            title="Write a report of a meeting",
            summary="A summary, minutes, action items or another report of a meeting.",
            description=(
                "Write a report of a meeting from a template with the chosen chat model: "
                "summary, minutes, actions (action items), decisions, standup, sales (a sales "
                "call), or the person's own template. It uses only what was said, in the "
                "meeting's language. A long meeting is read in parts first. The report is kept "
                "on the meeting's page and found by search. Returns the report."
            ),
            input=ReportIn,
            output=ReportOut,
            examples=({"meeting_id": "0" * 32}, {"meeting_id": "0" * 32, "template": "actions"}),
            effect="make",
            requires=(need_product(PRODUCT_ID), need_runtime("meetings"), CHAT),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_report, check=_check_report),
            ui="meetings.list",
        ),
        Action(
            id="meetings.add_template",
            title="Keep a report template",
            summary="Keep a report template of your own for meetings.",
            description=(
                "Keep a template of the person's own for meeting reports: a name and what the "
                "report says, in plain words. Then write a report with it (meetings.write_report "
                "with the template id this returns)."
            ),
            input=TemplateIn,
            output=TemplateOut,
            examples=(
                {
                    "title": "Client update",
                    "instructions": "What the client asked for, what we promised and by when.",
                },
            ),
            effect="make",
            requires=(need_product(PRODUCT_ID), need_runtime("meetings")),
            product=PRODUCT_ID,
            bind=CallBinding(_template),
            ui="meetings.list",
        ),
        Action(
            id="meetings.delete_report",
            title="Delete a report of a meeting",
            summary="Delete one report of a meeting.",
            description=(
                "Delete one report of a meeting; the meeting stays. Always asks the person."
            ),
            input=DeleteReportIn,
            output=DeleteReportOut,
            examples=({"report_id": "0" * 32},),
            effect="destroy",
            requires=(need_product(PRODUCT_ID), need_runtime("meetings")),
            product=PRODUCT_ID,
            bind=CallBinding(_delete_report),
            ui="meetings.list",
        ),
        Action(
            id="meetings.add_to_notebook",
            title="Add a meeting to a notebook",
            summary="Make a meeting a source of a notebook, to ask across many.",
            description=(
                "Add a meeting (its speakers, transcript and reports) to a notebook as a source, "
                "or to a new notebook. Then it can be asked about there with the notebook's other "
                "sources, with citations (notebook.ask)."
            ),
            input=ToNotebookIn,
            output=ToNotebookOut,
            examples=({"meeting_id": "0" * 32}, {"meeting_id": "0" * 32, "notebook_id": "n1"}),
            effect="change",
            requires=(need_product(PRODUCT_ID), need_runtime("meetings"), NOTEBOOKS),
            product=PRODUCT_ID,
            bind=CallBinding(_to_notebook, check=_check_meeting),
            ui="meetings.list",
        ),
        Action(
            id="meetings.ask",
            title="Ask about a meeting",
            summary="Ask a question that one meeting's transcript answers.",
            description=(
                "Ask about one meeting: who said what, what was decided, what someone asked for. "
                "The answer is written from the meeting's transcript only, with [n] labels that "
                "point at its lines, by a notebook the meeting is in (a new notebook named after "
                "it when it is in none). Use notebook.ask to ask across many meetings."
            ),
            input=AskIn,
            output=AskOut,
            examples=({"meeting_id": "0" * 32, "question": "What did Asha agree to do?"},),
            effect="change",  # a meeting in no notebook is added to a new one first
            requires=(need_product(PRODUCT_ID), need_runtime("meetings"), NOTEBOOKS, CHAT),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_ask, check=_check_ask),
            ui="meetings.list",
        ),
    ]


def library_kinds() -> list[LibraryKind]:
    return [
        LibraryKind(
            KIND, PRODUCT_ID, "meeting", _list, _get, _delete, _rename, export=_export, read=_read
        )
    ]


__all__ = ["actions", "library_kinds"]
