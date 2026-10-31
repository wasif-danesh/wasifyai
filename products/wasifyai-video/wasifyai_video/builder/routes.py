"""Motion graphics' API, under /products/wasifyai-video/builder/: templates, compositions, a still
preview, lint, and renders that run in the background and can be followed and cancelled.

Every query is scoped by tenant and user. A composition has no files until it is previewed or
rendered (they need the component's GSAP); its page is generated from its words and shown as the
code view."""

import asyncio
import contextlib
import hashlib
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from wasifyai_platform_sdk import Identity, RouteDeps, parse_ids

from wasifyai_video.builder import brand, check, live, media, projects, starts, templates
from wasifyai_video.builder.runtime import (
    NotAvailable,
    NotFound,
    Refused,
    add_to_search,
    engine_for,
    index_composition,
    make_draft,
    manager_for,
    not_ready,
    put_files_beside,
    root_for,
    store_for,
)
from wasifyai_video.builder.store import NothingToUndo
from wasifyai_video.videos import video_store

PRODUCT_ID = "wasifyai-video"
PREVIEW_AT_MAX = float(templates.MAX_SECONDS)
LIVE_PIECE_BYTES = 8 * 1024 * 1024  # the most of a file sent for one request from the player


class ProjectIn(BaseModel):
    template: str = Field("title", max_length=40)
    slots: dict[str, Any] = Field(default_factory=dict)


class RenderIn(BaseModel):
    format: str = Field("mp4", max_length=8)
    quality: str | None = Field(None, max_length=12)


class ShapesIn(RenderIn):
    shapes: list[str] = Field(min_length=1, max_length=4)


class StartIn(BaseModel):
    start: str = Field(max_length=40)
    shape: str = Field("portrait", max_length=20)


class UseBrandIn(BaseModel):
    use: bool = True


class ProjectPatch(BaseModel):
    slots: dict[str, Any]
    # "scenes" turns a project made from one template into a project of scenes (ADR-0096)
    template: str | None = Field(None, max_length=40)


class ConversationIn(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=64)


class Attachment(BaseModel):
    name: str = Field("", max_length=200)
    text: str = Field("", max_length=60_000)


class DraftIn(BaseModel):
    prompt: str = Field("", max_length=4000)
    attachment: Attachment | None = None
    shape: str | None = Field(None, max_length=20)


def template_info() -> dict[str, Any]:
    return {
        "templates": [t.info() for t in templates.TEMPLATES.values()],
        "shapes": {k: {"width": w, "height": h} for k, (w, h) in templates.SHAPES.items()},
        "themes": {
            k: {"from": a, "to": b, "ink": c, "accent": d}
            for k, (a, b, c, d) in templates.THEMES.items()
        },
        "fonts": {k: v[0] for k, v in templates.FONTS.items()},
        "starts": starts.info(),
    }


def build_builder_routes(deps: RouteDeps) -> APIRouter:
    router = APIRouter(prefix="/builder", tags=[PRODUCT_ID])

    def guard() -> None:
        try:
            engine_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(404, str(e)) from None

    def refuse(e: Refused) -> HTTPException:
        return HTTPException(409, {"code": e.code, "message": e.message})

    def slots_or_422(template: str, raw: dict[str, Any]) -> dict[str, Any]:
        try:
            return templates.normalize_slots(template, raw)
        except templates.SlotError as e:
            raise HTTPException(422, {"code": "bad_slot", "message": str(e)}) from None

    def composition(identity: Identity, cid: str) -> dict[str, Any]:
        try:
            return store_for(deps.state).get_composition(identity.tenant_id, identity.user_id, cid)
        except NotFound:
            raise HTTPException(404, "video project not found") from None

    def write_files(identity: Identity, found: dict[str, Any], engine: Any) -> Path:
        folder = projects.project_dir(
            root_for(deps.state), identity.tenant_id, identity.user_id, found["id"]
        )
        gsap, fonts = engine.gsap(), engine.fonts(templates.FONT_FILES)
        if gsap is None or templates.FONTS[found["slots"]["font"]][1] not in fonts:
            raise HTTPException(
                409, {"code": "not_ready", "message": "Motion graphics needs to be set up again."}
            )
        projects.write_project(folder, found["template"], found["slots"], gsap, fonts)
        return folder

    async def render_out(identity: Identity, row: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in row.items() if k not in ("tenant_id", "user_id")}
        live = manager_for(deps).progress(row["id"])
        if live is not None and row["status"] == "working":
            out["progress"] = live
        out["stage"] = manager_for(deps).stage(row["id"]) if row["status"] == "working" else None
        out["format"] = row["settings"].get("format", "mp4")
        out["shape"] = row["settings"].get("shape")
        out["video_url"] = out["poster_url"] = None
        if row["status"] == "done" and row["video_id"] and deps.storage is not None:
            clip = await video_store(deps.engine).get(
                identity.tenant_id, identity.user_id, row["video_id"]
            )
            if clip is not None and clip.video_key and clip.poster_key:
                with deps.acting_as(identity, PRODUCT_ID):
                    out["video_url"] = await deps.storage.url(clip.video_key)
                    out["poster_url"] = await deps.storage.url(clip.poster_key)
        return out

    async def project_out(
        identity: Identity, found: dict[str, Any], detail: bool
    ) -> dict[str, Any]:
        out = {k: v for k, v in found.items() if k not in ("tenant_id", "user_id")}
        rows = store_for(deps.state).list_renders(identity.tenant_id, identity.user_id, found["id"])
        out["renders"] = [await render_out(identity, r) for r in (rows if detail else rows[:1])]
        out["can_undo"] = store_for(deps.state).version_count(found["id"]) > 0
        out["formats"] = list(templates.formats_of(found["template"], found["slots"]))
        out["preview_times"] = templates.preview_times(found["template"], found["slots"])
        if detail:  # the code view: what the template makes of these words
            out["code"] = templates.render_html(found["template"], found["slots"])
            # every project reads as scenes: one made from a template is one scene
            out["document"] = templates.as_scenes(found["template"], found["slots"])
        return out

    @router.get("/status")
    async def status(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        engine = engine_for(deps.state)
        return {
            "ready": engine.ready(),
            "fit": engine.fit(),
            "busy": manager_for(deps).busy(identity),
            "problem": engine.problem() if hasattr(engine, "problem") else None,
            # where the work is done: on this computer, or on a service's worker
            "place": "device" if deps.state.builder_scratch is None else "service",
        }

    @router.get("/templates")
    async def list_templates(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        return template_info()

    @router.post("/draft")
    async def draft_project(
        body: DraftIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """What a description (and perhaps a CSV file) means as a template and its fields. Nothing
        is saved: the window shows the form filled in, and the person checks it."""
        guard()
        attachment = body.attachment.model_dump() if body.attachment else None
        try:
            return await make_draft(deps, identity, body.prompt, attachment, body.shape)
        except Refused as e:
            status = 422 if e.code in ("bad_draft", "bad_file") else 409
            raise HTTPException(status, {"code": e.code, "message": e.message}) from None

    @router.get("/projects")
    async def list_projects(
        ids: str | None = Query(None, max_length=2000),
        limit: int = Query(50, ge=1, le=200),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        guard()
        found = await asyncio.to_thread(
            store_for(deps.state).list_compositions,
            identity.tenant_id, identity.user_id, parse_ids(ids), limit,
        )  # fmt: skip
        return {"items": [await project_out(identity, c, detail=False) for c in found]}

    @router.post("/projects", status_code=201)
    async def create_project(
        body: ProjectIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        slots = slots_or_422(body.template, body.slots)
        found = await asyncio.to_thread(
            store_for(deps.state).add_composition,
            identity.tenant_id, identity.user_id,
            title=templates.title_of(body.template, slots), template=body.template, slots=slots,
        )  # fmt: skip
        found = await with_brand(identity, found)
        await index_composition(deps, identity, found)
        return await project_out(identity, found, detail=True)

    async def with_brand(identity: Identity, found: dict[str, Any]) -> dict[str, Any]:
        return await brand.on_new_project(
            deps, store_for(deps.state), (identity.tenant_id, PRODUCT_ID, identity.user_id), found
        )

    @router.post("/projects/from-start", status_code=201)
    async def create_from_start(
        body: StartIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """A project from a starting point: a set of scenes with words to replace."""
        guard()
        try:
            wanted = starts.document_of(body.start, body.shape)
        except KeyError:
            raise HTTPException(404, "no such starting point") from None
        slots = slots_or_422(templates.SCENES, wanted)
        found = await asyncio.to_thread(
            store_for(deps.state).add_composition,
            identity.tenant_id, identity.user_id,
            title=templates.title_of(templates.SCENES, slots), template=templates.SCENES,
            slots=slots,
        )  # fmt: skip
        found = await with_brand(identity, found)
        await index_composition(deps, identity, found)
        return await project_out(identity, found, detail=True)

    # ---- the brand kit (ADR-0096 MX7) -----------------------------------------------------------

    @router.get("/brand")
    async def get_brand(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        kit = await asyncio.to_thread(
            store_for(deps.state).get_brand, identity.tenant_id, identity.user_id
        )
        return {"kit": kit}

    @router.put("/brand")
    async def set_brand(
        body: dict[str, Any], identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        store = store_for(deps.state)
        try:
            kit = brand.normalize_kit(body)
        except templates.SlotError as e:
            raise HTTPException(422, {"code": "bad_slot", "message": str(e)}) from None
        before = await asyncio.to_thread(store.get_brand, identity.tenant_id, identity.user_id)
        kit["logo_asset"] = (before or {}).get("logo_asset")
        await asyncio.to_thread(store.set_brand, identity.tenant_id, identity.user_id, kit)
        return {"kit": kit}

    @router.post("/brand/logo", status_code=201)
    async def set_brand_logo(
        file: UploadFile = File(...),  # noqa: B008
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """The logo: a picture, checked as any file is, kept for this person's projects."""
        guard()
        limiter = deps.state.upload_limiter
        if limiter is not None and not await limiter.allow(identity.tenant_id, identity.user_id):
            raise HTTPException(429, "Too many uploads. Please wait a while and try again.")
        data = await file.read(media.MAX_BYTES + 1)
        try:
            checked = await asyncio.to_thread(media.check_upload, data, file.filename or "")
        except media.MediaError as e:
            raise HTTPException(422, {"code": "bad_file", "message": str(e)}) from None
        if checked.asset["kind"] != "image":
            raise HTTPException(422, {"code": "bad_file", "message": "A logo must be a picture."})
        assert deps.storage is not None, "storage is required"
        owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
        await deps.storage.put_for(
            owner, media.rel_path(brand.KIT_FOLDER, checked.asset["file"]), checked.data,
            media.type_of(checked.asset["file"]),
        )  # fmt: skip
        store = store_for(deps.state)
        kit = await asyncio.to_thread(store.get_brand, identity.tenant_id, identity.user_id)
        kit = {**(kit or brand.normalize_kit({})), "logo_asset": checked.asset}
        await asyncio.to_thread(store.set_brand, identity.tenant_id, identity.user_id, kit)
        return {"kit": kit}

    @router.get("/brand/logo")
    async def get_brand_logo(identity: Identity = Depends(deps.identity)) -> Response:
        guard()
        kit = await asyncio.to_thread(
            store_for(deps.state).get_brand, identity.tenant_id, identity.user_id
        )
        logo = (kit or {}).get("logo_asset")
        if not logo or deps.storage is None:
            raise HTTPException(404, "no logo")
        owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
        data = await deps.storage.get_for(owner, media.rel_path(brand.KIT_FOLDER, logo["file"]))
        return Response(
            data, media_type=media.type_of(logo["file"]),
            headers={"X-Content-Type-Options": "nosniff"},
        )  # fmt: skip

    @router.post("/projects/{cid}/brand")
    async def use_brand(
        cid: str, body: UseBrandIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """What this project's document would be with the brand on it, and its files with the logo
        among them. The window puts it in its own document, one Undo step, like a made file."""
        guard()
        found = composition(identity, cid)
        if found["template"] != templates.SCENES:
            raise HTTPException(409, {"code": "not_scenes", "message": "Add more scenes first."})
        store = store_for(deps.state)
        kit = await asyncio.to_thread(store.get_brand, identity.tenant_id, identity.user_id)
        if kit is None:
            raise HTTPException(409, {"code": "no_brand", "message": "Set up your brand first."})
        owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
        document = await brand.use_on(deps, store, owner, found, kit)
        return {"brand": document["brand"], "font": document["font"], "assets": document["assets"]}

    @router.get("/projects/{cid}")
    async def get_project(cid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        return await project_out(identity, composition(identity, cid), detail=True)

    @router.patch("/projects/{cid}")
    async def update_project(
        cid: str, body: ProjectPatch, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        current = composition(identity, cid)
        template, before = current["template"], current["slots"]
        if body.template not in (None, template, templates.SCENES):
            raise HTTPException(422, {"code": "bad_slot", "message": "That cannot be changed."})
        if body.template == templates.SCENES and template != templates.SCENES:
            template, before = templates.SCENES, templates.as_scenes(template, before)
        wanted = dict(body.slots)
        if template == templates.SCENES:  # the files are only changed by adding or removing one
            wanted["assets"] = before.get("assets") or []
        slots = slots_or_422(template, {**before, **wanted})
        found = await asyncio.to_thread(
            store_for(deps.state).update_composition,
            identity.tenant_id, identity.user_id, cid,
            title=templates.title_of(template, slots), slots=slots, template=template,
        )  # fmt: skip
        await index_composition(deps, identity, found)
        return await project_out(identity, found, detail=True)

    @router.post("/projects/{cid}/assets", status_code=201)
    async def add_asset(
        cid: str,
        file: UploadFile = File(...),  # noqa: B008
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """A file for this project: checked, kept under its owner, and listed in the document."""
        guard()
        found = composition(identity, cid)
        if found["template"] != templates.SCENES:
            raise HTTPException(409, {"code": "not_scenes", "message": "Add more scenes first."})
        limiter = deps.state.upload_limiter
        if limiter is not None and not await limiter.allow(identity.tenant_id, identity.user_id):
            raise HTTPException(429, "Too many uploads. Please wait a while and try again.")
        data = await file.read(media.MAX_BYTES + 1)
        try:
            checked = await asyncio.to_thread(media.check_upload, data, file.filename or "")
        except media.MediaError as e:
            raise HTTPException(422, {"code": "bad_file", "message": str(e)}) from None
        assert deps.storage is not None, "storage is required"
        await deps.storage.put_for(
            (identity.tenant_id, PRODUCT_ID, identity.user_id),
            media.rel_path(cid, checked.asset["file"]),
            checked.data,
            media.MEDIA_TYPES.get(Path(checked.asset["file"]).suffix, "application/octet-stream"),
        )
        store = store_for(deps.state)
        assets = [*(found["slots"].get("assets") or []), checked.asset]
        if len(assets) > templates.MAX_ASSETS:
            raise HTTPException(
                422, {"code": "bad_file", "message": "A project can hold 60 files. Remove one."}
            )
        await asyncio.to_thread(store.set_assets, identity.tenant_id, identity.user_id, cid, assets)
        return {"asset": checked.asset, "assets": assets}

    @router.delete("/projects/{cid}/assets/{asset_id}")
    async def remove_asset(
        cid: str, asset_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """A file out of the project, and out of every scene that used it. Undo brings the scenes
        back, not the file."""
        guard()
        found = composition(identity, cid)
        kept = [a for a in found["slots"].get("assets") or [] if a["id"] != asset_id]
        gone = [a for a in found["slots"].get("assets") or [] if a["id"] == asset_id]
        if not gone:
            raise HTTPException(404, "that file is not in this project")
        slots = slots_or_422(templates.SCENES, {**found["slots"], "assets": kept})
        updated = await asyncio.to_thread(
            store_for(deps.state).update_composition,
            identity.tenant_id, identity.user_id, cid,
            title=found["title"], slots=slots,
        )  # fmt: skip
        assert deps.storage is not None, "storage is required"
        owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
        with contextlib.suppress(FileNotFoundError):
            await deps.storage.delete_for(owner, media.rel_path(cid, gone[0]["file"]))
        return await project_out(identity, updated, detail=True)

    @router.put("/projects/{cid}/conversation")
    async def keep_conversation(
        cid: str, body: ConversationIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """The editor's chat for this project (ADR-0096): found again when it is opened."""
        guard()
        composition(identity, cid)
        await asyncio.to_thread(
            store_for(deps.state).set_conversation,
            identity.tenant_id, identity.user_id, cid, body.conversation_id,
        )  # fmt: skip
        return {"conversation_id": body.conversation_id}

    @router.post("/projects/{cid}/undo")
    async def undo_project(cid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """Bring back the version before the last change."""
        guard()
        composition(identity, cid)
        try:
            found = await asyncio.to_thread(
                store_for(deps.state).undo_composition, identity.tenant_id, identity.user_id, cid
            )
        except NothingToUndo:
            raise HTTPException(
                409, {"code": "nothing_to_undo", "message": "There is nothing to undo."}
            ) from None
        await index_composition(deps, identity, found)
        return await project_out(identity, found, detail=True)

    @router.post("/projects/{cid}/check")
    async def check_project(
        cid: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """The exact-text check: does the screen say what was typed (ADR-0079 decision 7)."""
        guard()
        engine = engine_for(deps.state)
        found = composition(identity, cid)
        if not engine.ready():
            raise HTTPException(409, {"code": "not_ready", "message": not_ready(engine)})
        if manager_for(deps).busy(identity):
            raise HTTPException(
                409, {"code": "busy", "message": "A video is being made. Try again in a moment."}
            )
        folder = await asyncio.to_thread(write_files, identity, found, engine)
        await put_files_beside(deps, identity, found, folder, engine)
        with deps.acting_as(identity, PRODUCT_ID):
            return await check.run_check(engine, folder, found["template"], found["slots"])

    @router.delete("/projects/{cid}", status_code=204)
    async def delete_project(cid: str, identity: Identity = Depends(deps.identity)) -> Response:
        guard()
        await delete_composition(deps, identity, cid)
        return Response(status_code=204)

    @router.post("/projects/{cid}/lint")
    async def lint_project(cid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        found = composition(identity, cid)
        with tempfile.TemporaryDirectory(prefix="lint-") as tmp:
            folder = Path(tmp)
            (folder / "index.html").write_text(
                templates.render_html(found["template"], found["slots"])
            )
            engine = engine_for(deps.state)
            with deps.acting_as(identity, PRODUCT_ID):
                if asyncio.iscoroutinefunction(engine.lint):  # a worker's engine
                    findings = await engine.lint(folder)
                else:
                    findings = await asyncio.to_thread(engine.lint, folder)
        return {"ok": not findings, "findings": findings}

    async def live_asset(
        found: dict[str, Any], file: str, request: Request, headers: dict[str, str]
    ) -> Response:
        """One of the project's files, for the player: in pieces, as a media element asks."""
        if not any(a["file"] == file for a in found["slots"].get("assets") or []):
            raise HTTPException(404, "not part of this preview")
        assert deps.storage is not None, "storage is required"
        owner = (found["tenant_id"], PRODUCT_ID, found["user_id"])
        rel = media.rel_path(found["id"], file)
        kind = media.MEDIA_TYPES.get(Path(file).suffix, "application/octet-stream")
        out = {**headers, "Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
        try:
            size = await deps.storage.size_for(owner, rel)
            try:
                asked = media.parse_range(request.headers.get("range"), size, LIVE_PIECE_BYTES)
            except ValueError:
                raise HTTPException(
                    416, "outside the file", headers={"Content-Range": f"bytes */{size}"}
                ) from None
            if asked is None:
                data = await deps.storage.get_for(owner, rel)
                return Response(data, media_type=kind, headers=out)
            first, last = asked
            data = await deps.storage.read_range_for(owner, rel, first, last)
        except FileNotFoundError:
            raise HTTPException(404, "not part of this preview") from None
        out["Content-Range"] = f"bytes {first}-{last}/{size}"
        return Response(data, status_code=206, media_type=kind, headers=out)

    def make_answer(result: Any) -> dict[str, Any]:
        """A make as the window follows it: working, done, or why not, in words."""
        if result.status == "running":
            return {"state": "working", "job_id": result.job_id}
        if result.status == "ok":
            return {"state": "done", **result.output}
        text = result.setup.step if result.setup else result.text
        raise HTTPException(
            422, {"code": result.code or "not_made", "message": text or "That could not be made."}
        )

    @router.post("/projects/{cid}/make")
    async def make_file(
        cid: str, body: dict[str, Any], identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Make something for this project: the person pressed the button, so nothing asks again.
        A long make is a job; the window puts the file where it wants it, so its own saves and
        this cannot overwrite each other (ADR-0096 MX6)."""
        guard()
        composition(identity, cid)
        executor = deps.state.actions
        if executor is None:
            raise HTTPException(
                409, {"code": "not_ready", "message": "That is not available here."}
            )
        params = {**body, "composition_id": cid, "use": "none"}
        return make_answer(
            await executor.run_action(
                "motion.make_file", params, "window", actor=identity, person_approved=True,
                wait_seconds=1.0,
            )
        )  # fmt: skip

    @router.get("/make-jobs/{job_id}")
    async def make_status(
        job_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        executor = deps.state.actions
        if executor is None:
            raise HTTPException(
                409, {"code": "not_ready", "message": "That is not available here."}
            )
        found = await executor.run_action(
            "job.status", {"job_id": job_id}, "window", actor=identity
        )
        if found.status != "ok":
            raise HTTPException(404, "no such job")
        done = found.output.get("result")
        if done is None:
            progress = found.output.get("progress") or {}
            return {"state": "working", "job_id": job_id, "progress": progress.get("progress")}
        if done.get("status") == "ok":
            return {"state": "done", **done.get("output", {})}
        raise HTTPException(
            422,
            {"code": done.get("code") or "not_made", "message": done.get("text") or "Not made."},
        )

    @router.post("/make-jobs/{job_id}/cancel")
    async def make_cancel(
        job_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        executor = deps.state.actions
        if executor is not None:
            await executor.run_action("job.cancel", {"job_id": job_id}, "window", actor=identity)
        return {"state": "stopped"}

    @router.get("/voices")
    async def voices(identity: Identity = Depends(deps.identity)) -> list[dict[str, str]]:
        """The person's saved voices, for a voiceover. None where speech is not served."""
        guard()
        executor = deps.state.actions
        if executor is None:
            return []
        found = await executor.run_action("voice.list", {}, "window", actor=identity)
        rows = found.output.get("voices", []) if found.status == "ok" else []
        return [{"id": v["voice_id"], "name": v["name"]} for v in rows]

    @router.post("/projects/{cid}/live")
    async def live_address(cid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """Where the player finds this project (ADR-0096 decision 3): a frame cannot send the
        person's token in a header, so a short-lived signed one is in the address."""
        guard()
        composition(identity, cid)
        key = await asyncio.to_thread(store_for(deps.state).live_key)
        expires = int(time.time()) + live.LIFETIME_S
        token = live.sign(key, cid, expires)
        return {
            "path": f"/products/{PRODUCT_ID}/builder/live/{token}/index.html",
            "expires_at": expires,
        }

    @router.get("/live/{token}/{name:path}")
    async def live_file(token: str, name: str, request: Request) -> Response:
        """The project's page and the few files it needs, for the player's frame. The token says
        which project, and was signed for its owner; nothing else is served here."""
        guard()
        store = store_for(deps.state)
        key = await asyncio.to_thread(store.live_key)
        cid = live.verify(key, token, time.time())
        found = await asyncio.to_thread(store.owned_composition, cid) if cid else None
        if found is None:
            raise HTTPException(403, "This preview has run out. Open the project again.")
        headers = {"Content-Security-Policy": live.CONTENT_POLICY, **live.NO_SNIFF}
        if name == "index.html":
            parts = (
                templates.live_parts(found["slots"])
                if found["template"] == templates.SCENES
                else None
            )
            page = live.with_runtime(
                templates.render_html(found["template"], found["slots"]), parts
            )
            return Response(
                page, media_type="text/html", headers={**headers, "Cache-Control": "no-store"}
            )
        if name.startswith("assets/"):
            return await live_asset(found, name.removeprefix("assets/"), request, headers)
        owner = Identity(found["tenant_id"], found["user_id"])
        with deps.acting_as(owner, PRODUCT_ID):
            try:
                kit = await engine_for(deps.state).live_kit()
            except RuntimeError as e:
                raise HTTPException(409, {"code": "not_ready", "message": str(e)}) from None
        data = kit.get(name.removeprefix("vendor/")) if name.startswith("vendor/") else None
        if data is None:
            raise HTTPException(404, "not part of this preview")
        return Response(
            data, media_type=live.media_type(name),
            headers={**headers, "Cache-Control": "private, max-age=3600"},
        )  # fmt: skip

    @router.get("/projects/{cid}/preview")
    async def preview(
        cid: str,
        at: float | None = Query(None, ge=0, le=PREVIEW_AT_MAX),
        identity: Identity = Depends(deps.identity),
    ) -> Response:
        """One still of the composition at `at` seconds, made in the same sandbox as a render."""
        guard()
        engine = engine_for(deps.state)
        found = composition(identity, cid)
        if not engine.ready():
            raise HTTPException(409, {"code": "not_ready", "message": not_ready(engine)})
        if at is None:
            at = templates.preview_times(found["template"], found["slots"])[1]
        at = min(at, float(found["slots"]["seconds"]))
        folder = await asyncio.to_thread(write_files, identity, found, engine)
        await put_files_beside(deps, identity, found, folder, engine)
        key = hashlib.sha256(f"{found['template']}|{found['slots']}|{at:g}".encode()).hexdigest()[
            :16
        ]
        cached = folder / "previews" / f"{key}.png"
        if not cached.is_file():
            if manager_for(deps).busy(identity):
                raise HTTPException(
                    409,
                    {"code": "busy", "message": "A video is being made. Try again in a moment."},
                )
            work = folder / "previews" / f"work-{key}"
            with deps.acting_as(identity, PRODUCT_ID):
                result = await engine.snapshot(folder, work, at)
            if not result.ok:
                raise HTTPException(
                    502, {"code": "preview_failed", "message": result.message or "No preview."}
                )
            pngs = sorted(work.rglob("*.png"))
            if not pngs:
                raise HTTPException(502, {"code": "preview_failed", "message": "No preview."})
            cached.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(pngs[0].replace, cached)
            await asyncio.to_thread(_rmtree, work)
        data = await asyncio.to_thread(cached.read_bytes)
        return Response(
            data, media_type="image/png",
            headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"},
        )  # fmt: skip

    @router.post("/projects/{cid}/render", status_code=202)
    async def start_render(
        cid: str,
        body: RenderIn | None = None,
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        guard()
        composition(identity, cid)
        try:
            row = await manager_for(deps).start(
                identity, cid, body.format if body else "mp4", body.quality if body else None
            )
        except Refused as e:
            raise refuse(e) from None
        return await render_out(identity, row)

    @router.post("/projects/{cid}/render-shapes", status_code=202)
    async def start_render_shapes(
        cid: str, body: ShapesIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        composition(identity, cid)
        try:
            rows = await manager_for(deps).start_shapes(
                identity, cid, body.shapes, body.format, body.quality
            )
        except Refused as e:
            raise refuse(e) from None
        return {"renders": [await render_out(identity, r) for r in rows]}

    @router.get("/renders/{rid}")
    async def get_render(rid: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        try:
            row = store_for(deps.state).get_render(identity.tenant_id, identity.user_id, rid)
        except NotFound:
            raise HTTPException(404, "render not found") from None
        return await render_out(identity, row)

    @router.post("/renders/{rid}/cancel")
    async def cancel_render(
        rid: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        try:
            stopped = await manager_for(deps).cancel(identity, rid)
            row = store_for(deps.state).get_render(identity.tenant_id, identity.user_id, rid)
        except NotFound:
            raise HTTPException(404, "render not found") from None
        return {"stopped": stopped, **await render_out(identity, row)}

    return router


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


async def delete_composition(deps: RouteDeps, identity: Identity, cid: str) -> bool:
    """Remove a composition: stop a render in progress, delete the clips it made (their files and
    rows, and out of search), its folder, and the composition itself. False if there is none."""
    store = store_for(deps.state)
    try:
        found = store.get_composition(identity.tenant_id, identity.user_id, cid)
    except NotFound:
        return False
    manager = manager_for(deps)
    for render in store.list_renders(identity.tenant_id, identity.user_id, cid):
        if render["status"] == "working":
            await manager.cancel(identity, render["id"])
    renders = await asyncio.to_thread(
        store.delete_composition, identity.tenant_id, identity.user_id, cid
    )
    clips = video_store(deps.engine)
    for render in renders:
        vid = render.get("video_id")
        if not vid:
            continue
        clip = await clips.get(identity.tenant_id, identity.user_id, vid)
        if clip is not None and deps.storage is not None:
            with deps.acting_as(identity, PRODUCT_ID):
                for key in (clip.video_key, clip.poster_key):
                    if key:
                        try:
                            await deps.storage.delete(key)
                        except FileNotFoundError:
                            pass
        await clips.delete(identity.tenant_id, identity.user_id, vid)
        await deps.unindex(identity, PRODUCT_ID, vid)
    folder = projects.project_dir(root_for(deps.state), identity.tenant_id, identity.user_id, cid)
    await asyncio.to_thread(projects.remove_project, folder)
    for shape in templates.SHAPES:  # one a restart left behind
        variant = projects.project_dir(
            root_for(deps.state), identity.tenant_id, identity.user_id, cid, shape
        )
        await asyncio.to_thread(projects.remove_project, variant)
    if deps.storage is not None:
        owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
        for asset in found["slots"].get("assets") or []:
            with contextlib.suppress(FileNotFoundError):
                await deps.storage.delete_for(owner, media.rel_path(cid, asset["file"]))
    await deps.unindex(identity, PRODUCT_ID, cid)
    return True


__all__ = ["build_builder_routes", "delete_composition", "add_to_search"]
