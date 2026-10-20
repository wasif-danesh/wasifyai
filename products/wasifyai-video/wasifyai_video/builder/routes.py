"""Video Builder's API, under /products/wasifyai-video/builder/: templates, compositions, a still
preview, lint, and renders that run in the background and can be followed and cancelled.

Every query is scoped by tenant and user. A composition has no files until it is previewed or
rendered (they need the component's GSAP); its page is generated from its words and shown as the
code view."""

import asyncio
import hashlib
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from wasifyai_platform_sdk import Identity, RouteDeps, parse_ids

from wasifyai_video.builder import check, projects, templates
from wasifyai_video.builder.runtime import (
    NotAvailable,
    NotFound,
    Refused,
    add_to_search,
    engine_for,
    index_composition,
    manager_for,
    root_for,
    store_for,
)
from wasifyai_video.builder.store import NothingToUndo
from wasifyai_video.videos import video_store

PRODUCT_ID = "wasifyai-video"
PREVIEW_AT_MAX = 12.0


class ProjectIn(BaseModel):
    template: str = Field("title", max_length=40)
    slots: dict[str, Any] = Field(default_factory=dict)


class RenderIn(BaseModel):
    format: str = Field("mp4", max_length=8)


class ProjectPatch(BaseModel):
    slots: dict[str, Any]


def template_info() -> dict[str, Any]:
    return {
        "templates": [t.info() for t in templates.TEMPLATES.values()],
        "shapes": {k: {"width": w, "height": h} for k, (w, h) in templates.SHAPES.items()},
        "themes": {
            k: {"from": a, "to": b, "ink": c, "accent": d}
            for k, (a, b, c, d) in templates.THEMES.items()
        },
        "fonts": {k: v[0] for k, v in templates.FONTS.items()},
    }


def build_builder_routes(deps: RouteDeps) -> APIRouter:
    router = APIRouter(prefix="/builder", tags=[PRODUCT_ID])

    def guard() -> None:
        try:
            engine_for(deps.state)
            root_for(deps.state)
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
                409, {"code": "not_ready", "message": "Video Builder needs to be set up again."}
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
        t = templates.get(found["template"])
        out["can_undo"] = store_for(deps.state).version_count(found["id"]) > 0
        out["formats"] = list(t.formats)
        out["preview_times"] = templates.preview_times(found["template"], found["slots"])
        if detail:  # the code view: what the template makes of these words
            out["code"] = templates.render_html(found["template"], found["slots"])
        return out

    @router.get("/status")
    async def status(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        engine = engine_for(deps.state)
        return {"ready": engine.ready(), "fit": engine.fit(), "busy": manager_for(deps).busy}

    @router.get("/templates")
    async def list_templates(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        return template_info()

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
        await index_composition(deps, identity, found)
        return await project_out(identity, found, detail=True)

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
        slots = slots_or_422(current["template"], {**current["slots"], **body.slots})
        found = await asyncio.to_thread(
            store_for(deps.state).update_composition,
            identity.tenant_id, identity.user_id, cid,
            title=templates.title_of(current["template"], slots), slots=slots,
        )  # fmt: skip
        await index_composition(deps, identity, found)
        return await project_out(identity, found, detail=True)

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
            raise HTTPException(
                409, {"code": "not_ready", "message": "Video Builder is not set up yet."}
            )
        if manager_for(deps).busy:
            raise HTTPException(
                409, {"code": "busy", "message": "A video is being made. Try again in a moment."}
            )
        folder = await asyncio.to_thread(write_files, identity, found, engine)
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
            findings = await asyncio.to_thread(engine_for(deps.state).lint, folder)
        return {"ok": not findings, "findings": findings}

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
            raise HTTPException(
                409, {"code": "not_ready", "message": "Video Builder is not set up yet."}
            )
        if at is None:
            at = templates.preview_times(found["template"], found["slots"])[1]
        at = min(at, float(found["slots"]["seconds"]))
        folder = await asyncio.to_thread(write_files, identity, found, engine)
        key = hashlib.sha256(f"{found['template']}|{found['slots']}|{at:g}".encode()).hexdigest()[
            :16
        ]
        cached = folder / "previews" / f"{key}.png"
        if not cached.is_file():
            if manager_for(deps).busy:
                raise HTTPException(
                    409,
                    {"code": "busy", "message": "A video is being made. Try again in a moment."},
                )
            work = folder / "previews" / f"work-{key}"
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
            row = await manager_for(deps).start(identity, cid, body.format if body else "mp4")
        except Refused as e:
            raise refuse(e) from None
        return await render_out(identity, row)

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
        store.get_composition(identity.tenant_id, identity.user_id, cid)
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
    await deps.unindex(identity, PRODUCT_ID, cid)
    return True


__all__ = ["build_builder_routes", "delete_composition", "add_to_search"]
