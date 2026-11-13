"""The routes of "Teach it to decide" (ADR-0075), added to the training router.

GET/POST /decision/sets                 PATCH/DELETE /decision/sets/{id}
GET /decision/sets/{id}                 the set with its examples and the plan of a run
PUT /decision/sets/{id}/examples        replace the examples (a typed grid, a paste, a file)
POST /decision/sets/{id}/runs           start teaching
GET /decision/status                    whether it can run here and the model choices
POST /decision/models/{id}/ask          one text, to the taught model and to the untaught one
POST /decision/models/{id}/sort         many texts, to the taught model"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from wasifyai_platform_sdk import Identity, RouteDeps

from wasifyai_training import bases, decision
from wasifyai_training.decisions import (
    CannotDecide,
    decide,
    engine_for,
    manager_for,
)
from wasifyai_training.runtime import NotAvailable, Refused, store_for
from wasifyai_training.store import DECISION_KINDS, QUALITIES, NotFound

MAX_SORT = 2000


def clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("tenant_id", "user_id")}


class OptionIn(BaseModel):
    label: str = Field(max_length=60)
    about: str = Field("", max_length=200)


class DecisionSetIn(BaseModel):
    name: str = Field("", max_length=60)


class DecisionSetPatch(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    kind: str | None = Field(default=None, max_length=12)
    question: str | None = Field(default=None, max_length=300)
    options: list[OptionIn] | None = Field(default=None, max_length=30)
    levels: int | None = Field(default=None, ge=2, le=20)
    low: str | None = Field(default=None, max_length=200)
    high: str | None = Field(default=None, max_length=200)
    quality: str | None = Field(default=None, max_length=10)
    base: str | None = Field(default=None, max_length=80)


class RowIn(BaseModel):
    text: str = Field(max_length=decision.MAX_TEXT * 2)
    answer: str = Field(max_length=200)


class RowsIn(BaseModel):
    rows: list[RowIn] = Field(max_length=decision.MAX_EXAMPLES)


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=decision.MAX_TEXT)


class SortIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_SORT)


def add_decision_routes(router: APIRouter, deps: RouteDeps) -> None:
    def guard() -> Any:
        try:
            return engine_for(deps.state)
        except NotAvailable:
            raise HTTPException(404, "Teaching it to decide is not available here.") from None

    def set_or_404(identity: Identity, item: str) -> dict[str, Any]:
        try:
            return store_for(deps.state).get_decision_set(
                identity.tenant_id, identity.user_id, item
            )
        except NotFound:
            raise HTTPException(404, "set of examples not found") from None

    def set_out(identity: Identity, row: dict[str, Any], full: bool = False) -> dict[str, Any]:
        out = clean(row)
        plan = manager_for(deps).plan(identity, row["id"])
        out.update(
            examples=plan["examples"], missing=plan["missing"], steps=plan["steps"],
            estimate=plan["estimate"],
        )  # fmt: skip
        if full:
            out["rows"] = store_for(deps.state).list_decision_examples(
                identity.tenant_id, identity.user_id, row["id"]
            )
            out["plan"] = plan
            out["answers"] = decision.question_from(row).answers()
            out["problem"] = decision.question_from(row).problem()
        return out

    @router.get("/decision/status")
    async def decision_status(identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        engine = guard()
        setup = deps.state.decision_setup
        base = bases.descriptors("decision")[0]
        ready = engine.ready(base.id)
        return {
            "ready": ready,
            "problem": engine.problem(base.id),
            "engine": engine.state(),
            "fit": engine.fit(base.need_gb) if ready else None,
            "busy": manager_for(deps).busy() or manager_for(deps).others_busy(),
            "active_run": manager_for(deps).active(),
            "place": getattr(engine, "place", "device"),
            "min_examples": decision.MIN_EXAMPLES,
            "good_examples": decision.GOOD_EXAMPLES,
            "min_per_answer": decision.PER_ANSWER,
            "max_options": decision.MAX_OPTIONS,
            "levels": [decision.MIN_LEVELS, decision.MAX_LEVELS, decision.DEFAULT_LEVELS],
            "kinds": list(DECISION_KINDS),
            "qualities": list(QUALITIES),
            "choices": bases.choices(
                "decision",
                lambda d: engine.fit(d.need_gb) if ready else None,
                ready,
                [],
                lambda d: setup.has_model(spec) if setup and (spec := setup.spec(d.id)) else ready,
            ),
            "bases": setup.bases_state() if setup is not None else [],
        }

    @router.post("/decision/sets", status_code=201)
    async def make_set(
        body: DecisionSetIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        row = store_for(deps.state).add_decision_set(
            identity.tenant_id, identity.user_id, body.name
        )
        return set_out(identity, row, full=True)

    @router.get("/decision/sets")
    async def list_sets(
        limit: int = Query(50, ge=1, le=200), identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        rows = store_for(deps.state).list_decision_sets(identity.tenant_id, identity.user_id, limit)
        return {"sets": [set_out(identity, r) for r in rows]}

    @router.get("/decision/sets/{set_id}")
    async def get_set(set_id: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        return set_out(identity, set_or_404(identity, set_id), full=True)

    @router.patch("/decision/sets/{set_id}")
    async def patch_set(
        set_id: str, body: DecisionSetPatch, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        guard()
        set_or_404(identity, set_id)
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if fields.get("kind") and fields["kind"] not in DECISION_KINDS:
            raise HTTPException(
                422, {"code": "bad_kind", "message": "Choose yes or no, a category or a score."}
            )
        if "quality" in fields and fields["quality"] not in QUALITIES:
            raise HTTPException(422, {"code": "bad_quality", "message": "Choose Quick or Better."})
        if fields.get("base") and bases.descriptor(fields["base"]) is None:
            raise HTTPException(
                422, {"code": "bad_base", "message": "This model cannot be taught yet."}
            )
        row = store_for(deps.state).update_decision_set(
            identity.tenant_id, identity.user_id, set_id, **fields
        )
        return set_out(identity, row, full=True)

    @router.put("/decision/sets/{set_id}/examples")
    async def put_examples(
        set_id: str, body: RowsIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Replace the examples with these rows, as typed: the checks say what will be left out."""
        guard()
        set_or_404(identity, set_id)
        store_for(deps.state).set_decision_examples(
            identity.tenant_id, identity.user_id, set_id, [r.model_dump() for r in body.rows]
        )
        return set_out(identity, set_or_404(identity, set_id), full=True)

    @router.delete("/decision/sets/{set_id}", status_code=204)
    async def remove_set(set_id: str, identity: Identity = Depends(deps.identity)) -> None:
        guard()
        store_for(deps.state).delete_decision_set(identity.tenant_id, identity.user_id, set_id)

    @router.post("/decision/sets/{set_id}/runs", status_code=202)
    async def start_run(set_id: str, identity: Identity = Depends(deps.identity)) -> dict[str, Any]:
        guard()
        set_or_404(identity, set_id)
        try:
            row = await manager_for(deps).start(identity, set_id)
        except Refused as e:
            status = 422 if e.code == "not_ready_to_train" else 409
            raise HTTPException(status, {"code": e.code, "message": e.message}) from None
        return clean(row)

    async def run_decide(
        identity: Identity, model_id: str, texts: list[str], original: bool
    ) -> dict[str, Any]:
        guard()
        try:
            return await decide(deps, identity, model_id, texts, original)
        except CannotDecide as e:
            status = 404 if e.code in ("not_found", "gone") else 409
            raise HTTPException(status, {"code": e.code, "message": e.message}) from None

    @router.post("/decision/models/{model_id}/ask")
    async def ask(
        model_id: str, body: AskIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """One text, to the model that was taught and to the one it started from, side by side."""
        got = await run_decide(identity, model_id, [body.text], True)
        return {
            "question": got["question"], "kind": got["kind"], "answers": got["answers"],
            "mine": got["results"][0],
            "original": (got.get("original") or [None])[0],
        }  # fmt: skip

    @router.post("/decision/models/{model_id}/sort")
    async def sort(
        model_id: str, body: SortIn, identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        """Many texts, each with its answer and how sure the model is."""
        texts = [decision.tidy(t)[: decision.MAX_TEXT] or "-" for t in body.texts]
        got = await run_decide(identity, model_id, texts, False)
        return {
            "question": got["question"], "kind": got["kind"], "answers": got["answers"],
            "results": got["results"],
        }  # fmt: skip
