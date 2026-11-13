"""The 3D product's API, under /products/wasifyai-model3d/: the picture and its checks, the models
being made and finished, and their files. Desktop only: where there is no 3D engine every route
answers 404. Every query is scoped by tenant and user."""

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    SaveRefused,
    SaveTo,
    copy_to_path,
    parse_ids,
)

from wasifyai_model3d import files, pictures
from wasifyai_model3d.runtime import (
    DETAILS,
    NotAvailable,
    Refused,
    add_to_search,
    blobs_for,
    delete_model,
    engine_for,
    manager_for,
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


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class Exported(BaseModel):
    name: str
    path: str


def build_routes(deps: RouteDeps) -> APIRouter:
    router = APIRouter(prefix="/m3d", tags=[PRODUCT_ID])

    def guard() -> Any:
        try:
            return engine_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(404, str(e)) from None

    def refuse(e: Refused) -> HTTPException:
        status = 422 if e.code in ("bad_detail", "bad_seed", "unusable") else 409
        return HTTPException(status, {"code": e.code, "message": e.message})

    def model_out(row: dict[str, Any], identity: Identity) -> dict[str, Any]:
        out = {k: v for k, v in row.items() if k not in ("tenant_id", "user_id")}
        active = manager_for(deps).active(identity)
        out["live"] = bool(active and active["id"] == row["id"])
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

    # ---- status ---------------------------------------------------------------------------

    @router.get("/status")
    async def status(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        engine = guard()
        jobs = manager_for(deps)
        return {
            "ready": engine.ready(),
            "problem": engine.problem() if hasattr(engine, "problem") else None,
            "fit": engine.fit() if engine.ready() else None,
            "busy": jobs.busy(identity),
            "active": jobs.active(identity),
            "details": list(DETAILS),
            # where the work is done: on this computer, or on a service's worker
            "place": "device" if getattr(blobs_for(deps.state), "local", True) else "service",
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
    ) -> Response:
        guard()
        if which not in ("picture", "cutout"):
            raise HTTPException(404, "not found")
        input_or_404(identity, input_id)
        return await blobs_for(deps.state).response(
            identity, "inputs", input_id, f"{which}.png", "image/png"
        )

    @router.delete("/inputs/{input_id}", status_code=204)
    async def delete_input(input_id: str, identity: Identity = Depends(deps.identity)) -> Response:
        guard()
        try:
            input_or_404(identity, input_id)
        except HTTPException:
            return Response(status_code=204)  # already gone
        await manager_for(deps).cancel_input(identity, input_id)
        store_for(deps.state).delete_input(identity.tenant_id, identity.user_id, input_id)
        await blobs_for(deps.state).remove(identity, "inputs", input_id)
        return Response(status_code=204)

    # ---- models ---------------------------------------------------------------------------

    @router.post("/models", status_code=202)
    async def make_model(
        body: MakeIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        try:
            row = await manager_for(deps).start(
                identity, body.input_id, title=body.title, prompt=body.prompt,
                detail=body.detail, seed=body.seed,
            )  # fmt: skip
        except Refused as e:
            raise refuse(e) from None
        return model_out(row, identity)

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
        return {"items": [model_out(r, identity) for r in rows]}

    @router.get("/models/{model_id}")
    async def get_model(
        model_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        return model_out(model_or_404(identity, model_id), identity)

    @router.get("/models/{model_id}/{which}")
    async def model_file(
        model_id: str, which: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
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
        headers = {}
        if which == "file":
            headers["Content-Disposition"] = (
                f'attachment; filename="{files.file_stem(row["title"])}.glb"'
            )
        return await blobs_for(deps.state).response(
            identity, "models", model_id, name, media, headers
        )

    @router.post("/models/{model_id}/cancel")
    async def cancel_model(
        model_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        model_or_404(identity, model_id)
        stopped = await manager_for(deps).cancel(identity, model_id)
        return {"stopped": stopped, **model_out(model_or_404(identity, model_id), identity)}

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
        return model_out(made, identity)

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
        return model_out(row, identity)

    @router.post("/models/{model_id}/export", response_model=Exported)
    async def export_model(
        model_id: str, body: SaveTo | None = None, identity: Identity = Depends(deps.identity)
    ) -> Exported:
        """Copy the model to the place the person chose in the Save As box (`path`), or into the
        export folder when there is none."""
        guard()
        folder = deps.state.export_dir
        if folder is None and not (body and body.path):
            raise HTTPException(404, "saving to a folder is not available here")
        row = model_or_404(identity, model_id)
        if row["status"] != "done":
            raise HTTPException(404, "not made yet")
        source = blobs_for(deps.state).local_path(identity, "models", model_id, "model.glb")
        if source is None:
            raise HTTPException(404, "saving to a folder is not available here")
        if body and body.path:
            try:
                path = await asyncio.to_thread(
                    copy_to_path, body.path, source, deps.state.desktop_dir
                )
            except SaveRefused as exc:
                raise HTTPException(422, str(exc)) from None
        else:
            assert folder is not None  # the check above: no path means a folder
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
