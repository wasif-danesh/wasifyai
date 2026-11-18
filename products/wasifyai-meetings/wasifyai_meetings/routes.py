"""The meetings product's API, under /products/wasifyai-meetings/: what is set up, making a meeting
from a file, the meetings and their recordings, people, reports and questions. On the desktop and on
the web (stage MT6, a meeting from a file only); where neither is set up every route answers 503 in
words. Every query is scoped by tenant and
user."""

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk import Identity, RouteDeps

from wasifyai_meetings import asking, audio, people, reports
from wasifyai_meetings.runtime import (
    STALE_MIN,
    NotAvailable,
    Refused,
    add_to_search,
    asking_for,
    delete_meeting,
    ensure_prints,
    manager_for,
    recording_in,
    recording_of,
    recording_url,
    reports_for,
    root_for,
    store_for,
    waiting_recordings,
    web_of,
)
from wasifyai_meetings.store import NotFound, new_id

PRODUCT_ID = "wasifyai-meetings"


class Title(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)


class Recorded(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=5, max_length=80)
    title: str | None = Field(None, max_length=200)
    language: str | None = Field(None, max_length=20)


class SpeakerName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field("", max_length=80)
    # one of People (MT3); without it the name finds a person of that name or makes one
    person_id: str | None = Field(None, max_length=40)


class NotPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person_id: str = Field(min_length=1, max_length=40)


class PersonName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)


class ReportAsk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: str = Field(min_length=1, max_length=64)
    title: str | None = Field(None, max_length=200)


class NewTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)
    instructions: str = Field(min_length=1, max_length=4000)


class ToNotebook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # a notebook of the person's; without it a new notebook is made, called `title`
    notebook_id: str | None = Field(None, max_length=64)
    title: str | None = Field(None, max_length=200)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)


def _copy_upload(file: Any, dst: Path, limit: int) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    with dst.open("wb") as out:
        while chunk := file.read(1024 * 1024):
            done += len(chunk)
            if done > limit:
                break
            out.write(chunk)
    if done > limit:
        dst.unlink(missing_ok=True)
    return done


def build_routes(deps: RouteDeps) -> APIRouter:
    router = APIRouter(tags=[PRODUCT_ID])

    def guard() -> None:
        try:
            root_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(503, str(e)) from None

    def refuse(e: Refused) -> HTTPException:
        status = 409 if e.code in ("busy", "not_ready", "runtime_missing", "model_missing") else 422
        return HTTPException(status, {"code": e.code, "message": e.message})

    def brief(row: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in row.items() if k not in ("tenant_id", "user_id")}
        out["live"] = manager_for(deps).making(row["id"])
        return out

    def get_or_404(identity: Identity, item: str) -> dict[str, Any]:
        try:
            return store_for(deps.state).get(identity.tenant_id, identity.user_id, item)
        except NotFound:
            raise HTTPException(404, "meeting not found") from None

    @router.get("/status")
    async def status(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        jobs = manager_for(deps)
        return jobs.readiness() | {
            "busy": jobs.busy(identity),
            "active": jobs.active(identity),
            "converter": audio.find_converter() is not None,
            "recordings": await asyncio.to_thread(waiting_recordings, deps.state),
            "formats": list(audio.SUFFIXES),
        }

    @router.post("/meetings", status_code=201)
    async def make_from_file(
        file: UploadFile = File(...),  # noqa: B008
        title: str | None = Form(None, max_length=200),
        language: str | None = Form(None, max_length=20),
        model: str | None = Form(None, max_length=120),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """A meeting from a recording (any sound or video file FFmpeg reads). The work goes on in
        the background; follow it with GET /meetings/{id}."""
        guard()
        jobs = manager_for(deps)
        why = jobs.not_ready()
        if why:
            raise HTTPException(409, {"code": "not_ready", "message": why})
        if jobs.busy(identity):
            raise HTTPException(
                409, {"code": "busy", "message": "A meeting is being made. Wait for it to finish."}
            )
        name = Path(file.filename or "recording").name[:200]
        incoming = root_for(deps.state) / "incoming" / f"{new_id()}{Path(name).suffix[:12]}"
        got = await asyncio.to_thread(_copy_upload, file.file, incoming, audio.MAX_BYTES)
        if got > audio.MAX_BYTES:
            raise HTTPException(
                413, {"code": "too_large", "message": "That file is larger than 2 GB."}
            )
        if got == 0:
            incoming.unlink(missing_ok=True)
            raise HTTPException(422, {"code": "empty", "message": "That file is empty."})
        label = (title or "").strip() or name.rsplit(".", 1)[0] or "Meeting"
        try:
            row = await jobs.start(
                identity, incoming, title=label[:200], source_name=name,
                language=(language or "").strip(), model=model,
            )  # fmt: skip
        except Refused as e:
            incoming.unlink(missing_ok=True)
            raise refuse(e) from None
        return brief(row)

    @router.post("/meetings/recorded", status_code=201)
    async def make_from_recording(
        body: Recorded, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """A meeting from a recording the app made (two channels: the microphone is "You", the
        computer's sound is everyone else), by the name the shell gave it in the meetings folder."""
        guard()
        src = recording_in(deps.state, body.name)
        if src is None:
            raise HTTPException(
                404, {"code": "no_recording", "message": "That recording is not there any more."}
            )
        label = (body.title or "").strip() or "Recorded meeting"
        try:
            row = await manager_for(deps).start(
                identity, src, title=label[:200], source_name=body.name,
                language=(body.language or "").strip(), recorded=True,
            )  # fmt: skip
        except Refused as e:  # the recording stays, to be made into a meeting later
            raise refuse(e) from None
        return brief(row)

    @router.delete("/recordings/{name}", status_code=204)
    async def discard_recording(name: str, identity: Identity = Depends(deps.identity)) -> Response:
        """Throw away a recording that was not made into a meeting."""
        guard()
        src = recording_in(deps.state, name)
        if src is None:
            raise HTTPException(404, "that recording is not there")
        await asyncio.to_thread(src.unlink, True)
        return Response(status_code=204)

    @router.get("/meetings")
    async def list_meetings(
        ids: str | None = Query(None, max_length=4000),
        limit: int = Query(100, ge=1, le=500),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        guard()
        wanted = [i for i in (ids or "").split(",") if i] or None
        store = store_for(deps.state)
        if web_of(deps.state) is not None:  # what a gone replica left going
            await asyncio.to_thread(store.fail_stale, STALE_MIN)
        rows = await asyncio.to_thread(
            store.list_meetings, identity.tenant_id, identity.user_id, wanted, limit
        )
        jobs = manager_for(deps)
        return {"items": [r | {"live": jobs.making(r["id"])} for r in rows]}

    def full(identity: Identity, row: dict[str, Any]) -> dict[str, Any]:
        """A meeting with who its speakers may be (MT3) and its reports (MT4)."""
        store = store_for(deps.state)
        t, u = identity.tenant_id, identity.user_id
        row = people.with_suggestions(store, t, u, row)
        row["reports"] = [reports.report_out(r) for r in store.reports_of(t, u, row["id"])]
        row["notebooks"] = store.in_notebooks(t, u, row["id"])  # MT5
        row["questions"] = [asking.question_out(q) for q in store.questions_of(t, u, row["id"])]
        return brief(row)

    async def full_async(identity: Identity, row: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(full, identity, row)

    @router.get("/meetings/{item}")
    async def get_meeting(item: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """A meeting; its speakers' voiceprints are made first if they are not yet (a meeting
        made before the voiceprint model was fetched)."""
        guard()
        row = get_or_404(identity, item)
        await asyncio.to_thread(ensure_prints, deps.state, identity, row)
        return await full_async(identity, row)

    @router.get("/meetings/{item}/audio")
    async def meeting_audio(item: str, identity: Identity = Depends(deps.identity)) -> Response:
        """The meeting's recording as it was heard (one channel, 16 kHz WAV), for playing back."""
        guard()
        get_or_404(identity, item)
        path = recording_of(deps.state, identity, item)
        if path is None:
            raise HTTPException(404, "the recording is not there")
        return FileResponse(
            path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"}
        )

    @router.get("/meetings/{item}/audio-link")
    async def meeting_audio_link(
        item: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """A signed link to the recording, for a player that reads it in ranges as it plays (the
        desktop's file storage); the route above is the whole file, for where there is none."""
        guard()
        get_or_404(identity, item)
        url = await recording_url(deps.state, identity, item)
        if url is None:
            raise HTTPException(404, "the recording is not there")
        return {"url": url}

    @router.get("/meetings/{item}/export")
    async def export_meeting(item: str, identity: Identity = Depends(deps.identity)) -> Response:
        """The transcript as text: a line per turn with the speaker's name and the time."""
        guard()
        row = get_or_404(identity, item)
        if row["status"] != "done":
            raise HTTPException(409, "the meeting is not ready")
        names = {s["key"]: s["name"] for s in row["speakers"]}

        def clock(s: float) -> str:
            s = int(s)
            return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else (
                f"{s // 60}:{s % 60:02d}")  # fmt: skip

        body = f"{row['title']}\n\n" + "\n\n".join(
            f"[{clock(x['start'])}] {names.get(x['speaker'], x['speaker'])}: {x['text']}"
            for x in row["lines"]
        )
        stem = "".join(c if c.isalnum() or c in " -_" else "_" for c in row["title"]).strip()
        return Response(
            body + "\n", media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem or "meeting"}.txt"',
                     "Cache-Control": "private, no-store"},
        )  # fmt: skip

    @router.patch("/meetings/{item}")
    async def rename_meeting(
        item: str, body: Title, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        try:
            row = store_for(deps.state).rename(
                identity.tenant_id, identity.user_id, item, body.title
            )
        except NotFound:
            raise HTTPException(404, "meeting not found") from None
        if row["status"] == "done":
            await add_to_search(deps.state, identity, row)
        return brief(row)

    @router.patch("/meetings/{item}/speakers/{key}")
    async def name_speaker(
        item: str, key: str, body: SpeakerName, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Name one speaker of this meeting: they become that person of People, and their voice is
        kept for later meetings (an empty name gives back "Speaker N")."""
        guard()
        try:
            row = await asyncio.to_thread(
                people.name_speaker, store_for(deps.state), identity.tenant_id, identity.user_id,
                item, key, body.name, body.person_id,
            )  # fmt: skip
        except NotFound:
            raise HTTPException(404, "speaker or person not found") from None
        await add_to_search(deps.state, identity, row)
        return await full_async(identity, row)

    @router.post("/meetings/{item}/speakers/{key}/not")
    async def not_this_person(
        item: str, key: str, body: NotPerson, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """ "No" to a suggestion: this speaker is not that person."""
        guard()
        try:
            row = await asyncio.to_thread(
                people.not_this_person, store_for(deps.state), identity.tenant_id,
                identity.user_id, item, key, body.person_id,
            )  # fmt: skip
        except NotFound:
            raise HTTPException(404, "speaker or person not found") from None
        return await full_async(identity, row)

    # ---- People (MT3) -------------------------------------------------------------------------

    @router.get("/people")
    async def list_people(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        store = store_for(deps.state)
        items = await asyncio.to_thread(store.people, identity.tenant_id, identity.user_id)
        return {"items": items}

    async def reindex(identity: Identity, items: list[str]) -> None:
        store = store_for(deps.state)
        for item in items:
            try:
                row = store.get(identity.tenant_id, identity.user_id, item)
            except NotFound:
                continue
            if row["status"] == "done":
                await add_to_search(deps.state, identity, row)

    @router.patch("/people/{pid}")
    async def rename_person(
        pid: str, body: PersonName, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """A new name for a person, in every meeting they were named in."""
        guard()
        store = store_for(deps.state)
        try:
            changed = await asyncio.to_thread(
                people.rename_person, store, identity.tenant_id, identity.user_id, pid, body.name
            )
        except NotFound:
            raise HTTPException(404, "person not found") from None
        await reindex(identity, changed)
        return store.person(identity.tenant_id, identity.user_id, pid)

    @router.delete("/people/{pid}", status_code=204)
    async def forget_person(pid: str, identity: Identity = Depends(deps.identity)) -> Response:
        """Delete a person with every voiceprint of them (the meetings keep the name as words)."""
        guard()
        try:
            changed = await asyncio.to_thread(
                people.forget_person, store_for(deps.state), identity.tenant_id,
                identity.user_id, pid,
            )  # fmt: skip
        except NotFound:
            raise HTTPException(404, "person not found") from None
        await reindex(identity, changed)
        return Response(status_code=204)

    # ---- reports and templates (MT4) ----------------------------------------------------------

    @router.get("/templates")
    async def list_templates(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        items = await asyncio.to_thread(reports.all_templates, store_for(deps.state), identity)
        return {"items": items}

    @router.post("/templates", status_code=201)
    async def add_template(
        body: NewTemplate, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        t = store_for(deps.state).add_template(
            identity.tenant_id, identity.user_id, body.title, body.instructions
        )
        return t | {"own": True}

    @router.delete("/templates/{tid}", status_code=204)
    async def delete_template(tid: str, identity: Identity = Depends(deps.identity)) -> Response:
        guard()
        if not store_for(deps.state).delete_template(identity.tenant_id, identity.user_id, tid):
            raise HTTPException(404, "template not found")
        return Response(status_code=204)

    @router.post("/meetings/{item}/reports", status_code=201)
    async def write_report(
        item: str, body: ReportAsk, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Write a report of the meeting from a template, in the background; follow it with
        GET /reports/{id} (or the meeting)."""
        guard()
        get_or_404(identity, item)
        store = store_for(deps.state)
        try:
            template = reports.template_for(store, identity, body.template)
        except NotFound:
            raise HTTPException(404, "template not found") from None
        try:
            row = reports_for(deps).start(identity, item, template, (body.title or "").strip())
        except reports.Refused as e:
            raise HTTPException(409, {"code": e.code, "message": e.message}) from None
        return reports.report_out(row)

    def report_or_404(identity: Identity, rid: str) -> dict[str, Any]:
        try:
            return store_for(deps.state).report(identity.tenant_id, identity.user_id, rid)
        except NotFound:
            raise HTTPException(404, "report not found") from None

    @router.get("/reports/{rid}")
    async def get_report(rid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        return reports.report_out(report_or_404(identity, rid))

    @router.post("/reports/{rid}/stop")
    async def stop_report(rid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        report_or_404(identity, rid)
        await reports_for(deps).cancel(rid)
        return reports.report_out(report_or_404(identity, rid))

    @router.get("/reports/{rid}/export")
    async def export_report(rid: str, identity: Identity = Depends(deps.identity)) -> Response:
        """The report as a Markdown file."""
        guard()
        r = report_or_404(identity, rid)
        if r["status"] != "done":
            raise HTTPException(409, "the report is not written yet")
        stem = "".join(c if c.isalnum() or c in " -_" else "_" for c in r["title"]).strip()
        return Response(
            r["text"] + "\n", media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem or "report"}.md"',
                     "Cache-Control": "private, no-store"},
        )  # fmt: skip

    @router.delete("/reports/{rid}", status_code=204)
    async def delete_report(rid: str, identity: Identity = Depends(deps.identity)) -> Response:
        guard()
        r = report_or_404(identity, rid)
        await reports_for(deps).cancel(rid)
        store_for(deps.state).delete_report(identity.tenant_id, identity.user_id, rid)
        await reindex(identity, [r["meeting_id"]])
        return Response(status_code=204)

    # ---- asking, through notebooks (MT5) -------------------------------------------------------

    def asked(e: asking.Refused) -> HTTPException:
        status = 404 if e.code == "not_found" else 409 if e.code in ("busy", "not_ready") else 422
        return HTTPException(status, {"code": e.code, "message": e.message})

    @router.get("/notebooks")
    async def list_notebooks(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """The person's notebooks, to add a meeting to."""
        guard()
        try:
            return {"items": await asking.notebooks(deps, identity)}
        except asking.Refused as e:
            raise asked(e) from None

    @router.post("/meetings/{item}/notebook")
    async def add_to_notebook(
        item: str, body: ToNotebook, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Add the meeting to a notebook as a source (a new one when no notebook is given)."""
        guard()
        get_or_404(identity, item)
        try:
            return await asking.add_to_notebook(
                deps, store_for(deps.state), identity, item,
                notebook_id=(body.notebook_id or "").strip(), title=(body.title or "").strip(),
            )  # fmt: skip
        except asking.Refused as e:
            raise asked(e) from None

    @router.post("/meetings/{item}/questions", status_code=201)
    async def ask(
        item: str, body: Question, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Ask about the meeting, answered in the background by a notebook it is in; follow it
        with GET /questions/{id} (or the meeting)."""
        guard()
        get_or_404(identity, item)
        try:
            q = asking_for(deps).start(identity, item, body.question)
        except asking.Refused as e:
            raise asked(e) from None
        return asking.question_out(q)

    def question_or_404(identity: Identity, qid: str) -> dict[str, Any]:
        try:
            return store_for(deps.state).question(identity.tenant_id, identity.user_id, qid)
        except NotFound:
            raise HTTPException(404, "question not found") from None

    @router.get("/questions/{qid}")
    async def get_question(qid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        return asking.question_out(question_or_404(identity, qid))

    @router.post("/questions/{qid}/stop")
    async def stop_question(
        qid: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        question_or_404(identity, qid)
        await asking_for(deps).cancel(qid)
        return asking.question_out(question_or_404(identity, qid))

    @router.delete("/questions/{qid}", status_code=204)
    async def delete_question(qid: str, identity: Identity = Depends(deps.identity)) -> Response:
        guard()
        question_or_404(identity, qid)
        await asking_for(deps).cancel(qid)
        store_for(deps.state).delete_question(identity.tenant_id, identity.user_id, qid)
        return Response(status_code=204)

    @router.post("/meetings/{item}/stop")
    async def stop_meeting(
        item: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        get_or_404(identity, item)
        await manager_for(deps).cancel(item)
        return brief(get_or_404(identity, item))

    @router.delete("/meetings/{item}", status_code=204)
    async def remove_meeting(item: str, identity: Identity = Depends(deps.identity)) -> Response:
        guard()
        if not await delete_meeting(deps, identity, item):
            raise HTTPException(404, "meeting not found")
        return Response(status_code=204)

    return router


__all__ = ["build_routes"]
