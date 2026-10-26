"""The training product's API, under /products/wasifyai-training/: datasets and their pictures, the
descriptions the app writes, the runs and the trained models. Where there is no training engine
every route answers 404. Every query is scoped by tenant and user."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    RouteGuard,
    RunContext,
    RunError,
    set_context,
)
from wasifyai_platform_sdk.context import reset_context

from wasifyai_training import bases, evaluation, magic, trainer
from wasifyai_training.decision_routes import add_decision_routes
from wasifyai_training.decisions import estimate_words as decision_estimate
from wasifyai_training.decisions import manager_for as decision_manager_for
from wasifyai_training.runtime import (
    MAX_PICTURES,
    MIN_PICTURES,
    STATEMENTS,
    NotAvailable,
    Refused,
    add_picture,
    add_to_search,
    caption_manager_for,
    delete_dataset,
    delete_model,
    engine_for,
    item_folder,
    model_folder,
    ready_to_train,
    remove_picture,
    run_folder,
    run_manager_for,
    store_for,
    suggestions,
    word_problem,
    words_of,
)
from wasifyai_training.store import FAMILIES, KINDS, RIGHTS, NotFound
from wasifyai_training.video import add_clip, ready_to_teach
from wasifyai_training.video import estimate_words as video_estimate
from wasifyai_training.video import manager_for as video_manager_for
from wasifyai_training.video import plan_of as video_plan
from wasifyai_training.video import seconds_per_step as video_seconds_per_step_tokens
from wasifyai_training.video_routes import add_video_routes, video_status_of
from wasifyai_training.writing import estimate_words as writing_estimate
from wasifyai_training.writing import manager_for as writing_manager_for
from wasifyai_training.writing_routes import add_writing_routes

PRODUCT_ID = "wasifyai-training"
MAX_UPLOAD = 25 * 1024 * 1024


class DatasetIn(BaseModel):
    kind: str = Field("character", max_length=12)
    name: str = Field("", max_length=60)
    family: str = Field("image", max_length=8)  # "video": pictures and clips for the video model


class DatasetPatch(BaseModel):
    kind: str | None = Field(None, max_length=12)
    name: str | None = Field(None, max_length=60)
    trigger_word: str | None = Field(None, max_length=60)
    rights: str | None = Field(None, max_length=12)


class ItemPatch(BaseModel):
    caption: str = Field(max_length=2000)


class CaptionsIn(BaseModel):
    again: bool = False
    item_ids: list[str] | None = Field(default=None, max_length=200)


class RunIn(BaseModel):
    dataset_id: str = Field(min_length=32, max_length=32)
    base: str | None = Field(default=None, max_length=80)  # the person's choice; none = recommended
    method: str | None = Field(default=None, max_length=20)


class CheckedPicture(BaseModel):
    id: str = Field(max_length=40)
    condition: Literal["with_word", "without_word", "without_model"]
    prompt: str = Field(max_length=600)
    same: bool | None = None
    reason: str = Field("", max_length=300)


class EvaluationIn(BaseModel):
    items: list[CheckedPicture] = Field(max_length=12)


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def video_seconds_per_step(settings: dict[str, Any]) -> float:
    """What a step of this video run takes: as planned for its mix, else by its size and frames."""
    from wasifyai_training.video import SIZES, tokens_of

    if settings.get("seconds_per_step"):
        return float(settings["seconds_per_step"])

    width, height = SIZES.get(str(settings.get("size", "square")), SIZES["square"])
    return video_seconds_per_step_tokens(tokens_of(width, height, int(settings.get("frames") or 1)))


def build_routes(deps: RouteDeps) -> APIRouter:
    router = APIRouter(prefix="/train", tags=[PRODUCT_ID])

    def guard() -> Any:
        try:
            return engine_for(deps.state)
        except NotAvailable as e:
            raise HTTPException(404, str(e)) from None

    def refuse(e: Refused) -> HTTPException:
        status = 422 if e.code in ("bad_picture", "bad_kind", "bad_rights", "bad_word") else 409
        return HTTPException(status, {"code": e.code, "message": e.message})

    def dataset_or_404(identity: Identity, item: str) -> dict[str, Any]:
        try:
            return store_for(deps.state).get_dataset(identity.tenant_id, identity.user_id, item)
        except NotFound:
            raise HTTPException(404, "set of pictures not found") from None

    def item_or_404(identity: Identity, dataset: str, item: str) -> dict[str, Any]:
        try:
            row = store_for(deps.state).get_item(identity.tenant_id, identity.user_id, item)
        except NotFound:
            raise HTTPException(404, "picture not found") from None
        if row["dataset_id"] != dataset:
            raise HTTPException(404, "picture not found")
        return row

    def run_or_404(identity: Identity, item: str) -> dict[str, Any]:
        try:
            return store_for(deps.state).get_run(identity.tenant_id, identity.user_id, item)
        except NotFound:
            raise HTTPException(404, "run not found") from None

    def model_or_404(identity: Identity, item: str) -> dict[str, Any]:
        try:
            return store_for(deps.state).get_model(identity.tenant_id, identity.user_id, item)
        except NotFound:
            raise HTTPException(404, "trained model not found") from None

    def clean(row: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in row.items() if k not in ("tenant_id", "user_id")}

    def dataset_out(identity: Identity, row: dict[str, Any]) -> dict[str, Any]:
        store = store_for(deps.state)
        items = store.list_items(identity.tenant_id, identity.user_id, row["id"])
        out = clean(row)
        out["pictures"] = len(items)
        if row["family"] == "video":  # pictures and clips, taught to the video model
            plan = video_plan(items)
            out["clips"] = plan["clips"]
            out["missing"] = ready_to_teach(row, items)
            out["steps"] = plan["steps"]
            out["estimate"] = video_estimate(plan["seconds"])
            out["writing"] = caption_manager_for(deps).busy(row["id"])
            return out
        out["missing"] = ready_to_train(row, items)
        # what teaching this set would take, by its own size: more pictures, more steps
        out["steps"] = trainer.steps_for(row["kind"], len(items))
        out["estimate"] = trainer.estimate_words(out["steps"], row["kind"])
        out["writing"] = caption_manager_for(deps).busy(row["id"])
        return out

    def item_out(row: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in clean(row).items() if k != "dhash"}
        out["suggest_remove"] = any(c["level"] == "warn" for c in row["checks"])
        return out

    def run_out(row: dict[str, Any]) -> dict[str, Any]:
        out = clean(row)
        settings = row.get("settings") or {}
        if settings.get("family") == "language":  # a writing run: its own manager and estimate
            base = bases.descriptor(row["base"]) or bases.descriptors("language")[0]
            out["estimate"] = writing_estimate(row["steps"], base)
            out["live"] = writing_manager_for(deps).active() == row["id"]
            return out
        if settings.get("family") == "video":  # a video run: its own manager and estimate
            out["estimate"] = video_estimate(row["steps"] * video_seconds_per_step(settings) + 60)
            out["live"] = video_manager_for(deps).active() == row["id"]
            return out
        if settings.get("family") == "decision":  # a decision run: its own manager and estimate
            base = bases.descriptor(row["base"]) or bases.descriptors("decision")[0]
            out["estimate"] = decision_estimate(row["steps"], base)
            out["live"] = decision_manager_for(deps).active() == row["id"]
            return out
        out["estimate"] = trainer.estimate_words(row["steps"], settings.get("kind", "character"))
        out["live"] = run_manager_for(deps).active() == row["id"]
        return out

    # ---- status ---------------------------------------------------------------------------

    @router.get("/status")
    async def status(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        engine = guard()
        runs = run_manager_for(deps)
        return {
            "ready": engine.ready(),
            "problem": engine.problem(),
            "preview": bool(getattr(engine, "preview", False)),
            "engine": engine.state(),
            "fit": engine.fit() if engine.ready() else None,
            "preflight": engine.preflight() if hasattr(engine, "preflight") else None,
            "busy": runs.busy()
            or writing_manager_for(deps).busy()
            or decision_manager_for(deps).busy()
            or video_manager_for(deps).busy(),
            "active_run": runs.active()
            or writing_manager_for(deps).active()
            or decision_manager_for(deps).active()
            or video_manager_for(deps).active(),
            "place": "device",
            "min_pictures": MIN_PICTURES,
            "max_pictures": MAX_PICTURES,
            "kinds": list(KINDS),
            "statements": STATEMENTS,
            "base": getattr(engine, "base", trainer.BASE),
            "steps": trainer.PRESETS,
            "estimates": {k: trainer.estimate_words(v, k) for k, v in trainer.PRESETS.items()},
        }

    @router.get("/choices")
    async def choices(
        kind: str = Query("character", max_length=20),
        family: str = Query("image", max_length=8),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        """The base models and methods the person may choose for a kind of teaching."""
        if family == "video":
            return (await video_status_of(deps, kind))["choices"]
        engine = guard()
        found = getattr(deps.state, "desktop_discovery", None)
        installed = [i.public() for i in getattr(found, "items", [])]
        ready = engine.ready()
        return bases.choices(kind, engine.fit() if ready else None, ready, installed)

    # ---- datasets -------------------------------------------------------------------------

    @router.post("/datasets", status_code=201)
    async def make_dataset(
        body: DatasetIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        if body.kind not in KINDS:
            raise HTTPException(
                422, {"code": "bad_kind", "message": "Choose a character, a style or an object."}
            )
        if body.family not in FAMILIES:
            raise HTTPException(422, {"code": "bad_kind", "message": "Choose pictures or video."})
        row = store_for(deps.state).add_dataset(
            identity.tenant_id, identity.user_id, body.kind, body.name, body.family
        )
        return dataset_out(identity, row)

    @router.get("/datasets")
    async def list_datasets(
        limit: int = Query(50, ge=1, le=200),
        family: str | None = Query(None, max_length=8),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:
        guard()
        rows = store_for(deps.state).list_datasets(
            identity.tenant_id, identity.user_id, limit, family if family in FAMILIES else None
        )
        return {"datasets": [dataset_out(identity, r) for r in rows]}

    @router.get("/datasets/{dataset_id}")
    async def get_dataset(
        dataset_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        row = dataset_or_404(identity, dataset_id)
        store = store_for(deps.state)
        items = store.list_items(identity.tenant_id, identity.user_id, dataset_id)
        out = dataset_out(identity, row)
        out["items"] = [item_out(i) for i in items]
        # the picture model's tokenizer judges a picture set's words; a video set has T5's own
        engine = None if row["family"] == "video" else guard()
        out["suggestions"] = await suggestions(store, identity, row, engine)
        return out

    @router.patch("/datasets/{dataset_id}")
    async def patch_dataset(
        dataset_id: str, body: DatasetPatch, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        dataset_or_404(identity, dataset_id)
        fields = body.model_dump(exclude_none=True)
        if "kind" in fields and fields["kind"] not in KINDS:
            raise HTTPException(422, {"code": "bad_kind", "message": "That is not a kind."})
        if "rights" in fields and fields["rights"] not in (*RIGHTS, ""):
            raise HTTPException(
                422, {"code": "bad_rights", "message": "Choose one of the statements."}
            )
        if "trigger_word" in fields:
            word = fields["trigger_word"].strip().lower()
            if word and not magic.valid(word):
                raise HTTPException(
                    422,
                    {
                        "code": "bad_word",
                        "message": "Use a made-up word of 4 to 12 letters, a to z.",
                    },
                )
            is_video = dataset_or_404(identity, dataset_id)["family"] == "video"
            if word and not is_video and (why := await word_problem(guard(), word)):
                raise HTTPException(422, {"code": "bad_word", "message": why})
            fields["trigger_word"] = word
        row = store_for(deps.state).update_dataset(
            identity.tenant_id, identity.user_id, dataset_id, **fields
        )
        return dataset_out(identity, row)

    @router.delete("/datasets/{dataset_id}", status_code=204)
    async def remove_dataset(
        dataset_id: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        guard()
        await delete_dataset(deps, identity, dataset_id)
        return Response(status_code=204)

    # ---- pictures -------------------------------------------------------------------------

    @router.post("/datasets/{dataset_id}/items", status_code=201)
    async def add_item(
        dataset_id: str, request: Request, name: str = Query("", max_length=200),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:  # fmt: skip
        guard()
        dataset_or_404(identity, dataset_id)
        declared = int(request.headers.get("content-length") or 0)
        if declared > MAX_UPLOAD and not request.headers.get("content-type", "").startswith(
            "video/"
        ):
            raise HTTPException(
                422,
                {"code": "bad_picture", "message": "That picture is too big. Use one under 20 MB."},
            )
        data = await request.body()
        wants_clip = request.headers.get("content-type", "").startswith("video/")
        try:
            row = (
                await add_clip(deps, identity, dataset_id, name, data)
                if wants_clip
                else await add_picture(deps, identity, dataset_id, name, data)
            )
        except Refused as e:
            raise refuse(e) from None
        return item_out(row)

    @router.delete("/datasets/{dataset_id}/items/{item_id}", status_code=204)
    async def delete_item(
        dataset_id: str, item_id: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        guard()
        item_or_404(identity, dataset_id, item_id)
        await remove_picture(deps, identity, item_id)
        return Response(status_code=204)

    @router.patch("/datasets/{dataset_id}/items/{item_id}")
    async def edit_caption(
        dataset_id: str, item_id: str, body: ItemPatch, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        item_or_404(identity, dataset_id, item_id)
        text = " ".join(body.caption.split())
        store = store_for(deps.state)
        store.set_caption(item_id, text, "edited" if text else "none")
        return item_out(store.get_item(identity.tenant_id, identity.user_id, item_id))

    @router.get("/datasets/{dataset_id}/items/{item_id}/{which}")
    async def item_picture(
        dataset_id: str, item_id: str, which: str, identity: Identity = Depends(deps.identity)
    ) -> FileResponse:
        guard()
        item_or_404(identity, dataset_id, item_id)
        files = {"picture": ("picture.png", "image/png"), "thumb": ("thumb.jpg", "image/jpeg")}
        if which not in files:
            raise HTTPException(404, "not found")
        name, media = files[which]
        path = item_folder(store_for(deps.state), identity, item_id) / name
        if not await asyncio.to_thread(path.is_file):
            raise HTTPException(404, "not found")
        return FileResponse(path, media_type=media)

    @router.post("/datasets/{dataset_id}/captions", status_code=202)
    async def write_captions(
        dataset_id: str, body: CaptionsIn | None = None,
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:  # fmt: skip
        guard()
        dataset_or_404(identity, dataset_id)
        body = body or CaptionsIn()
        try:
            n = await caption_manager_for(deps).start(
                identity, dataset_id, again=body.again, only=body.item_ids
            )
        except Refused as e:
            raise refuse(e) from None
        return {"writing": n}

    # ---- runs -----------------------------------------------------------------------------

    @router.post("/runs", status_code=202)
    async def start_run(body: RunIn, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        dataset = dataset_or_404(identity, body.dataset_id)
        try:
            manager = (
                video_manager_for(deps) if dataset["family"] == "video" else run_manager_for(deps)
            )
            row = await manager.start(identity, body.dataset_id, body.base, body.method)
        except Refused as e:
            raise refuse(e) from None
        return run_out(row)

    @router.get("/runs")
    async def list_runs(
        limit: int = Query(30, ge=1, le=100),
        identity: Identity = Depends(deps.identity),
    ) -> dict[str, Any]:  # fmt: skip
        guard()
        rows = store_for(deps.state).list_runs(identity.tenant_id, identity.user_id, limit)
        return {"runs": [run_out(r) for r in rows]}

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        return run_out(run_or_404(identity, run_id))

    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(
        run_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        row = run_or_404(identity, run_id)
        if (row.get("settings") or {}).get("family") == "language":
            return {"cancelled": await writing_manager_for(deps).cancel(identity, run_id)}
        if (row.get("settings") or {}).get("family") == "decision":
            return {"cancelled": await decision_manager_for(deps).cancel(identity, run_id)}
        if (row.get("settings") or {}).get("family") == "video":
            return {"cancelled": await video_manager_for(deps).cancel(identity, run_id)}
        return {"cancelled": await run_manager_for(deps).cancel(identity, run_id)}

    @router.post("/runs/{run_id}/pause")
    async def pause_run(run_id: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """Stop for now, keeping the last checkpoint; the run can be resumed."""
        guard()
        run_or_404(identity, run_id)
        return {"paused": await run_manager_for(deps).pause(identity, run_id)}

    @router.post("/runs/{run_id}/resume", status_code=202)
    async def resume_run(
        run_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        run_or_404(identity, run_id)
        try:
            row = await run_manager_for(deps).resume(identity, run_id)
        except Refused as e:
            raise refuse(e) from None
        return run_out(row)

    @router.get("/runs/{run_id}/samples/{name}")
    async def run_sample(
        run_id: str, name: str, identity: Identity = Depends(deps.identity)
    ) -> FileResponse:
        guard()
        row = run_or_404(identity, run_id)
        if name not in row["samples"]:
            raise HTTPException(404, "not found")
        path: Path = run_folder(store_for(deps.state), identity, run_id) / "samples" / name
        if not await asyncio.to_thread(path.is_file):
            raise HTTPException(404, "not found")
        return FileResponse(path, media_type="image/png")

    # ---- trained models -------------------------------------------------------------------

    @router.get("/models")
    async def list_models(
        limit: int = Query(50, ge=1, le=200), identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        rows = store_for(deps.state).list_models(identity.tenant_id, identity.user_id, limit)
        return {"models": [clean(r) for r in rows]}

    @router.get("/models/{model_id}")
    async def get_model(
        model_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        return clean(model_or_404(identity, model_id))

    @router.patch("/models/{model_id}")
    async def rename_model(
        model_id: str, body: RenameIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        model_or_404(identity, model_id)
        row = store_for(deps.state).rename_model(
            identity.tenant_id, identity.user_id, model_id, body.name
        )
        await add_to_search(deps.state, identity, model_id, words_of(row))
        return clean(row)

    # ---- did it learn? ----------------------------------------------------------------------

    @router.get("/models/{model_id}/check")
    async def check_plan(
        model_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """The pictures to draw to find out, and how many reference pictures it has."""
        guard()
        row = model_or_404(identity, model_id)
        folder = model_folder(store_for(deps.state), identity, model_id) / "refs"
        refs = len(await asyncio.to_thread(evaluation.load_refs, folder))
        return {"items": evaluation.check_plan(row["kind"], row["trigger_word"]), "refs": refs}

    @router.post("/models/{model_id}/judge")
    async def judge_picture(
        model_id: str, request: Request, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """The body is one picture it drew: does it look like the pictures it learnt from?"""
        guard()
        row = model_or_404(identity, model_id)
        if int(request.headers.get("content-length") or 0) > MAX_UPLOAD:
            raise HTTPException(
                422, {"code": "bad_picture", "message": "That picture is too big to check."}
            )
        data = await request.body()
        caps = RouteGuard(deps.state, PRODUCT_ID).caps
        if caps is None:
            raise HTTPException(
                409,
                {
                    "code": "no_vision_model",
                    "message": "Choose a model that can read pictures first (in the Model hub).",
                },
            )
        folder = model_folder(store_for(deps.state), identity, model_id) / "refs"
        refs = await asyncio.to_thread(evaluation.load_refs, folder)
        token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
        try:
            return await evaluation.judge(caps, row["kind"], refs, data)
        except RunError as e:
            raise HTTPException(409, {"code": e.code, "message": e.message}) from None
        except OSError:
            raise HTTPException(
                422, {"code": "bad_picture", "message": "That is not a picture it can check."}
            ) from None
        finally:
            reset_context(token)

    @router.put("/models/{model_id}/evaluation")
    async def put_evaluation(
        model_id: str, body: EvaluationIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Keep what the check found on the model's card, as a sentence and a mark."""
        guard()
        row = model_or_404(identity, model_id)
        items = [i.model_dump() for i in body.items]
        at = datetime.now(UTC).isoformat(timespec="seconds")
        result = evaluation.summarize(row["kind"], items, at)
        return clean(
            store_for(deps.state).set_evaluation(
                identity.tenant_id, identity.user_id, model_id, result
            )
        )

    @router.delete("/models/{model_id}", status_code=204)
    async def remove_model(model_id: str, identity: Identity = Depends(deps.identity)) -> Response:
        guard()
        await delete_model(deps, identity, model_id)
        return Response(status_code=204)

    @router.get("/models/{model_id}/file")
    async def model_file(
        model_id: str, identity: Identity = Depends(deps.identity)
    ) -> FileResponse:
        guard()
        row = model_or_404(identity, model_id)
        path = model_folder(store_for(deps.state), identity, model_id) / "adapter.safetensors"
        if not await asyncio.to_thread(path.is_file):
            raise HTTPException(404, "not found")
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=f"{row['trigger_word'] or 'lora'}.safetensors",
        )

    add_writing_routes(router, deps)
    add_decision_routes(router, deps)
    add_video_routes(router, deps)
    return router
