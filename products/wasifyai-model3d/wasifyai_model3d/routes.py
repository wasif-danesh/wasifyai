"""The 3D product's API, under /products/wasifyai-model3d/: the picture and its checks, the models
being made and finished, and their files. Desktop only: where there is no 3D engine every route
answers 404. Every query is scoped by tenant and user."""

import asyncio
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from wasifyai_platform_sdk import Identity, RouteDeps, parse_ids

from wasifyai_model3d import files, pictures
from wasifyai_model3d.runtime import (
    DETAILS,
    NotAvailable,
    Refused,
    add_to_search,
    delete_model,
    engine_for,
    manager_for,
    root_for,
    store_for,
    words_of,
)
from wasifyai_model3d.store import NotFound

PRODUCT_ID = "wasifyai-model3d"


class MakeIn(BaseModel):
    input_id: str = Field(min_length=32, max_length=32)
    title: str = Field("", max_length=200)
    prompt: str = Field("", max_length=1000)
    detail: str = Field("standard", max_length=12)
    seed: int = Field(42, ge=0, le=2**31 - 1)
    rights: bool = Field(False, description="The person says they may use the picture.")


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class Exported(BaseModel):
    name: str
    path: str


def build_routes(deps: RouteDeps) -> APIRouter:
    router = APIRouter(prefix="/m3d", tags=[PRODUCT_ID])

    def guard() -> Any:
        try:
            root_for(deps.state)
            return engine_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(404, str(e)) from None

    def refuse(e: Refused) -> HTTPException:
        status = 422 if e.code in ("bad_detail", "bad_seed", "unusable", "no_rights") else 409
        return HTTPException(status, {"code": e.code, "message": e.message})

    def model_out(row: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in row.items() if k not in ("tenant_id", "user_id")}
        jobs = manager_for(deps)
        out["live"] = bool(jobs.active and jobs.active["id"] == row["id"])
        return out

    def input_out(row: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in row.items() if k not in ("tenant_id", "user_id")}
        out["can_go_on"] = row["status"] == "ready" and not any(
            c["level"] == "stop" for c in row["checks"]
        )
        return out

    def model_or_404(identity: Identity, item: str) -> dict[str, Any]:
        try:
            return store_for(deps.state).get_model(identity.tenant_id, identity.user_id, item)
        except NotFound:
            raise HTTPException(404, "3D model not found") from None

    def input_or_404(identity: Identity, item: str) -> dict[str, Any]:
        try:
            return store_for(deps.state).get_input(identity.tenant_id, identity.user_id, item)
        except NotFound:
            raise HTTPException(404, "picture not found") from None

    def file_of(identity: Identity, kind: str, item: str, name: str) -> Path:
        store = store_for(deps.state)
        try:
            path = store.folder_of(identity.tenant_id, identity.user_id, kind, item) / name
        except ValueError:
            raise HTTPException(404, "not found") from None
        if not path.is_file():
            raise HTTPException(404, "not found")
        return path

    # ---- status ---------------------------------------------------------------------------

    @router.get("/status")
    async def status(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        engine = guard()
        jobs = manager_for(deps)
        return {
            "ready": engine.ready(),
            "problem": engine.problem() if hasattr(engine, "problem") else None,
            "fit": engine.fit() if engine.ready() else None,
            "busy": jobs.busy,
            "active": jobs.active,
            "details": list(DETAILS),
        }

    # ---- the picture ----------------------------------------------------------------------

    @router.post("/inputs", status_code=201)
    async def add_input(
        request: Request, name: str = Query("", max_length=200),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:  # fmt: skip
        """A picture (PNG, JPEG or WebP, the file itself as the body). It is brought to a size the
        engine takes, cut out and looked at in the background; follow it with GET."""
        guard()
        declared = int(request.headers.get("content-length") or 0)
        if declared > pictures.MAX_BYTES:
            raise HTTPException(
                413,
                {"code": "bad_picture", "message": "That picture is too big. Use one under 20 MB."},
            )
        data = await request.body()
        try:
            img = await asyncio.to_thread(pictures.open_picture, data)
        except pictures.BadPicture as e:
            raise HTTPException(422, {"code": "bad_picture", "message": str(e)}) from None
        png = await asyncio.to_thread(pictures.to_png, img)
        store = store_for(deps.state)
        row = store.add_input(identity.tenant_id, identity.user_id, name, img.width, img.height)
        try:
            await manager_for(deps).prepare(identity, row["id"], png)
        except Refused as e:
            store.delete_input(identity.tenant_id, identity.user_id, row["id"])
            raise refuse(e) from None
        return input_out(store.get_input(identity.tenant_id, identity.user_id, row["id"]))

    @router.get("/inputs/{input_id}")
    async def get_input(
        input_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        return input_out(input_or_404(identity, input_id))

    @router.get("/inputs/{input_id}/{which}")
    async def input_picture(
        input_id: str, which: str, identity: Identity = Depends(deps.identity)
    ) -> FileResponse:
        guard()
        if which not in ("picture", "cutout"):
            raise HTTPException(404, "not found")
        input_or_404(identity, input_id)
        path = file_of(identity, "inputs", input_id, f"{which}.png")
        return FileResponse(path, media_type="image/png")

    @router.delete("/inputs/{input_id}", status_code=204)
    async def delete_input(input_id: str, identity: Identity = Depends(deps.identity)) -> Response:
        guard()
        try:
            input_or_404(identity, input_id)
        except HTTPException:
            return Response(status_code=204)  # already gone
        await manager_for(deps).cancel_input(identity, input_id)
        store = store_for(deps.state)
        store.delete_input(identity.tenant_id, identity.user_id, input_id)
        folder = store.folder_of(identity.tenant_id, identity.user_id, "inputs", input_id)
        await asyncio.to_thread(shutil.rmtree, folder, True)
        return Response(status_code=204)

    # ---- models ---------------------------------------------------------------------------

    @router.post("/models", status_code=202)
    async def make_model(
        body: MakeIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        if not body.rights:
            raise HTTPException(
                422,
                {"code": "no_rights", "message": (
                    "Say that you may use this picture, and that it is not a photo of a real "
                    "person who has not agreed.")},
            )  # fmt: skip
        try:
            row = await manager_for(deps).start(
                identity, body.input_id, title=body.title, prompt=body.prompt,
                detail=body.detail, seed=body.seed,
            )  # fmt: skip
        except Refused as e:
            raise refuse(e) from None
        return model_out(row)

    @router.get("/models")
    async def list_models(
        ids: str | None = Query(None, max_length=2000),
        limit: int = Query(50, ge=1, le=200),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        guard()
        rows = await asyncio.to_thread(
            store_for(deps.state).list_models,
            identity.tenant_id, identity.user_id, parse_ids(ids), limit,
        )  # fmt: skip
        return {"items": [model_out(r) for r in rows]}

    @router.get("/models/{model_id}")
    async def get_model(
        model_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        return model_out(model_or_404(identity, model_id))

    @router.get("/models/{model_id}/{which}")
    async def model_file(
        model_id: str, which: str, identity: Identity = Depends(deps.identity)
    ) -> FileResponse:
        """`file` (the GLB), `thumb`, `source` (the picture it came from) or `cutout`."""
        guard()
        row = model_or_404(identity, model_id)
        names = {
            "file": ("model.glb", "model/gltf-binary"), "thumb": ("thumb.jpg", "image/jpeg"),
            "source": ("source.png", "image/png"), "cutout": ("cutout.png", "image/png"),
        }  # fmt: skip
        if which not in names:
            raise HTTPException(404, "not found")
        name, media = names[which]
        if which == "file" and row["status"] != "done":
            raise HTTPException(404, "not made yet")
        path = file_of(identity, "models", model_id, name)
        headers = {}
        if which == "file":
            headers["Content-Disposition"] = (
                f'attachment; filename="{files.file_stem(row["title"])}.glb"'
            )
        return FileResponse(path, media_type=media, headers=headers)

    @router.post("/models/{model_id}/cancel")
    async def cancel_model(
        model_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        model_or_404(identity, model_id)
        stopped = await manager_for(deps).cancel(identity, model_id)
        return {"stopped": stopped, **model_out(model_or_404(identity, model_id))}

    @router.post("/models/{model_id}/again", status_code=202)
    async def make_again(
        model_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Make it again from the same picture with the same seed: the same model, as a new one."""
        guard()
        row = model_or_404(identity, model_id)
        if not row["input_id"]:
            raise HTTPException(409, {"code": "no_picture", "message": "The picture is gone."})
        try:
            made = await manager_for(deps).start_again(identity, row)
        except Refused as e:
            raise refuse(e) from None
        return model_out(made)

    @router.patch("/models/{model_id}")
    async def rename_model(
        model_id: str, body: RenameIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        model_or_404(identity, model_id)
        row = store_for(deps.state).rename_model(
            identity.tenant_id, identity.user_id, model_id, body.title.strip()
        )
        await add_to_search(deps.state, identity, model_id, words_of(row))
        return model_out(row)

    @router.post("/models/{model_id}/export", response_model=Exported)
    async def export_model(model_id: str, identity: Identity = Depends(deps.identity)) -> Exported:
        """Copy the model into the person's export folder (the desktop app sets one)."""
        guard()
        folder = getattr(deps.state, "export_dir", None)
        if folder is None:
            raise HTTPException(404, "saving to a folder is not available here")
        row = model_or_404(identity, model_id)
        if row["status"] != "done":
            raise HTTPException(404, "not made yet")
        source = file_of(identity, "models", model_id, "model.glb")
        path = await asyncio.to_thread(
            files.save_copy, Path(folder), files.file_stem(row["title"]), source
        )
        return Exported(name=path.name, path=str(path))

    @router.delete("/models/{model_id}", status_code=204)
    async def remove_model(model_id: str, identity: Identity = Depends(deps.identity)) -> Response:
        guard()
        await delete_model(deps, identity, model_id)
        return Response(status_code=204)

    return router
