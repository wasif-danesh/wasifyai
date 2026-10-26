"""The routes of "Teach my assistant to write like me" (ADR-0074), added to the training router.

GET/POST /writing/sets                  PATCH/DELETE /writing/sets/{id}
GET /writing/sets/{id}                  the set with its examples and the plan of a run
PUT /writing/sets/{id}/examples         replace the examples (a typed grid, a paste, a file)
POST /writing/sets/{id}/runs            start teaching
GET /writing/status                     whether it can run here and the model choices
POST /writing/models/{id}/ask           the same question to the original and to the taught one"""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from wasifyai_platform_sdk import Identity, RouteDeps

from wasifyai_training import bases, gguf_lora, language
from wasifyai_training.runtime import Refused, model_or_none, run_manager_for, store_for
from wasifyai_training.store import QUALITIES, WRITING_RIGHTS, NotFound
from wasifyai_training.writing import KIND, adapter_of, engine_for, manager_for


def clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("tenant_id", "user_id")}


class WritingSetIn(BaseModel):
    name: str = Field("", max_length=60)


class WritingSetPatch(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    quality: str | None = Field(default=None, max_length=10)
    base: str | None = Field(default=None, max_length=80)
    rights: str | None = Field(default=None, max_length=20)


class ExampleIn(BaseModel):
    ask: str = Field(max_length=language.MAX_ASK * 2)
    answer: str = Field(max_length=language.MAX_ANSWER * 2)


class ExamplesIn(BaseModel):
    rows: list[ExampleIn] = Field(max_length=language.MAX_EXAMPLES)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=language.MAX_ASK)


def add_writing_routes(router: APIRouter, deps: RouteDeps) -> None:
    def guard() -> Any:
        try:
            return engine_for(deps.state)
        except Exception:
            raise HTTPException(404, "Teaching a writing model is not available here.") from None

    def set_or_404(identity: Identity, item: str) -> dict[str, Any]:
        try:
            return store_for(deps.state).get_writing_set(identity.tenant_id, identity.user_id, item)
        except NotFound:
            raise HTTPException(404, "set of examples not found") from None

    def set_out(identity: Identity, row: dict[str, Any], full: bool = False) -> dict[str, Any]:
        out = {k: v for k, v in row.items() if k not in ("tenant_id", "user_id")}
        plan = manager_for(deps).plan(identity, row["id"])
        out.update(
            examples=plan["examples"], missing=plan["missing"], steps=plan["steps"],
            estimate=plan["estimate"],
        )  # fmt: skip
        if full:
            out["rows"] = store_for(deps.state).list_examples(
                identity.tenant_id, identity.user_id, row["id"]
            )
            out["plan"] = plan
        return out

    @router.get("/writing/status")
    async def writing_status(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        engine = guard()
        setup = getattr(deps.state, "language_setup", None)
        lang = getattr(deps.state, "desktop_language", None)
        base = bases.descriptors("language")[0]
        ready = engine.ready(base.id)
        return {
            "ready": ready,
            "problem": engine.problem(base.id),
            "engine": engine.state(),
            "fit": engine.fit(base.need_gb) if ready else None,
            "busy": manager_for(deps).busy() or run_manager_for(deps).busy(),
            "active_run": manager_for(deps).active(),
            "place": "device",
            "min_examples": language.MIN_EXAMPLES,
            "good_examples": language.GOOD_EXAMPLES,
            "rights": list(WRITING_RIGHTS),
            "qualities": list(QUALITIES),
            "choices": bases.choices(
                KIND,
                lambda d: engine.fit(d.need_gb) if ready else None,
                ready,
                [],
                lambda d: setup.has_model(spec) if setup and (spec := setup.spec(d.id)) else ready,
            ),
            "in_chat": getattr(getattr(lang, "selected", None), "style", None),
            # what is on this computer for each base, and what getting the rest would cost
            "bases": setup.bases_state() if setup is not None else [],
        }

    @router.post("/writing/sets", status_code=201)
    async def make_set(
        body: WritingSetIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        row = store_for(deps.state).add_writing_set(identity.tenant_id, identity.user_id, body.name)
        return set_out(identity, row, full=True)

    @router.get("/writing/sets")
    async def list_sets(
        limit: int = Query(50, ge=1, le=200), identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        rows = store_for(deps.state).list_writing_sets(identity.tenant_id, identity.user_id, limit)
        return {"sets": [set_out(identity, r) for r in rows]}

    @router.get("/writing/sets/{set_id}")
    async def get_set(set_id: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        return set_out(identity, set_or_404(identity, set_id), full=True)

    @router.patch("/writing/sets/{set_id}")
    async def patch_set(
        set_id: str, body: WritingSetPatch, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        set_or_404(identity, set_id)
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if "quality" in fields and fields["quality"] not in QUALITIES:
            raise HTTPException(422, {"code": "bad_quality", "message": "Choose Quick or Better."})
        if "rights" in fields and fields["rights"] not in (*WRITING_RIGHTS, ""):
            raise HTTPException(
                422, {"code": "bad_rights", "message": "Choose one of the statements."}
            )
        if fields.get("base") and bases.descriptor(fields["base"]) is None:
            raise HTTPException(
                422, {"code": "bad_base", "message": "This model cannot be taught yet."}
            )
        row = store_for(deps.state).update_writing_set(
            identity.tenant_id, identity.user_id, set_id, **fields
        )
        return set_out(identity, row, full=True)

    @router.put("/writing/sets/{set_id}/examples")
    async def put_examples(
        set_id: str, body: ExamplesIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Replace the examples with these rows, as typed: the checks say what will be left out."""
        guard()
        set_or_404(identity, set_id)
        store_for(deps.state).set_examples(
            identity.tenant_id, identity.user_id, set_id, [r.model_dump() for r in body.rows]
        )
        return set_out(identity, set_or_404(identity, set_id), full=True)

    @router.delete("/writing/sets/{set_id}", status_code=204)
    async def remove_set(set_id: str, identity: Identity = Depends(deps.identity)) -> None:
        guard()
        store_for(deps.state).delete_writing_set(identity.tenant_id, identity.user_id, set_id)

    @router.post("/writing/sets/{set_id}/runs", status_code=202)
    async def start_writing_run(
        set_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        set_or_404(identity, set_id)
        try:
            row = await manager_for(deps).start(identity, set_id)
        except Refused as e:
            status = 422 if e.code in ("bad_rights", "not_ready_to_train") else 409
            raise HTTPException(status, {"code": e.code, "message": e.message}) from None
        return clean(row)

    def chat_parts() -> tuple[Any, Any]:
        """The writing setup and the chat's language service, or a refusal in words."""
        setup = getattr(deps.state, "language_setup", None)
        lang = getattr(deps.state, "desktop_language", None)
        if setup is None or lang is None:
            raise HTTPException(404, "Chatting with a taught model is not available here.")
        return setup, lang

    @router.post("/writing/models/{model_id}/use")
    async def use_in_chat(
        model_id: str, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Chat with this taught model: its base with the adapter on top, in the app's own
        language engine. What was chosen before is kept, so `DELETE /writing/use` gives it back."""
        guard()
        setup, lang = chat_parts()
        row = model_or_none(deps, identity, model_id)
        if row is None or row["kind"] != KIND:
            raise HTTPException(404, "trained model not found")
        d = bases.descriptor(row["base"])
        if d is None or not d.architecture:
            raise HTTPException(
                409, {"code": "cannot_serve", "message": "This model cannot be used in chat yet."}
            )
        base = setup.chat_copy(row["base"])
        spec = setup.spec(row["base"])
        if base is None or spec is None:
            raise HTTPException(
                409,
                {"code": "chat_copy_missing", "base": row["base"],
                 "bytes": spec.chat.size if spec else 0,
                 "message": "To chat with it, the app needs the same model in the form the chat "
                 "engine runs. It is downloaded once and kept in the app's own folder."},
            )  # fmt: skip
        if not lang.llama.installed:
            raise HTTPException(
                409,
                {"code": "no_engine", "message": "Set up the language engine in Settings first."},
            )
        folder = adapter_of(store_for(deps.state), identity, model_id)
        target = folder.parent / "adapter.gguf"
        source = folder / "adapters.safetensors"
        if not await asyncio.to_thread(source.is_file):
            raise HTTPException(404, "the taught model's files are gone")
        stale = not await asyncio.to_thread(target.is_file) or (
            await asyncio.to_thread(lambda: target.stat().st_mtime < source.stat().st_mtime)
        )
        if stale:
            try:
                await asyncio.to_thread(gguf_lora.convert, folder, target, d.architecture)
            except gguf_lora.ConvertError as e:
                raise HTTPException(409, {"code": "cannot_serve", "message": str(e)}) from None
        await lang.select_style(base, target, f"My style: {row['name']}", model_id)
        return {"selected": lang.selected.public() if lang.selected else None}

    @router.delete("/writing/use")
    async def stop_using_in_chat(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        """Back to the model that was chosen before."""
        _, lang = chat_parts()
        ended = await lang.end_style()
        return {"ended": ended, "selected": lang.selected.public() if lang.selected else None}

    @router.post("/writing/models/{model_id}/ask")
    async def ask(
        model_id: str, body: AskIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """One question to the original model and to the one taught, side by side."""
        engine = guard()
        row = model_or_none(deps, identity, model_id)
        if row is None or row["kind"] != KIND:
            raise HTTPException(404, "trained model not found")
        if manager_for(deps).busy() or run_manager_for(deps).busy():
            raise HTTPException(
                409, {"code": "busy", "message": "A model is being taught. Wait for it to finish."}
            )
        folder = adapter_of(store_for(deps.state), identity, model_id)
        if not await asyncio.to_thread((folder / "adapters.safetensors").is_file):
            raise HTTPException(404, "the taught model's files are gone")
        try:
            (original,) = await engine.answer(row["base"], [body.question])
            (mine,) = await engine.answer(row["base"], [body.question], folder)
        except RuntimeError as e:
            raise HTTPException(409, {"code": "not_ready", "message": str(e)}) from None
        return {"question": body.question, "original": original, "mine": mine}
