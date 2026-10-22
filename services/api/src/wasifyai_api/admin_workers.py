"""Admin routes for the engine workers (ADR-0087, P5): which workers are here, which models each
has, and getting a model (or the lip sync engine) onto a worker from the web.

A fetch is an `admin.*` job on the same queue as the work: it runs on whichever worker takes it,
reports how far it is, and the page follows it by its id. Fetching the same thing twice at once
gives the first job's id back."""

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import EngineJob, admin_wire
from wasifyai_platform_sdk.storage import object_key

from wasifyai_api.admin import AuditEntry
from wasifyai_api.engine_workers import WorkerDirectory
from wasifyai_api.identity import Identity, require_admin

log = logging.getLogger("wasifyai_api.admin_workers")

router = APIRouter(prefix="/admin/workers", tags=["admin"])

PRODUCT = "wasifyai-voice"  # the product whose models these are


class ModelRow(BaseModel):
    id: str
    title: str
    state: str
    bytes_missing: int
    licence: str
    commercial_use: str
    tasks: list[str]
    engine: str
    runtime_ready: bool


class WorkerRow(BaseModel):
    id: str
    busy: bool
    seen: float
    can_fetch: bool
    models: list[ModelRow]
    lipsync_engine: dict[str, Any] | None
    components: dict[str, Any]


class WorkerList(BaseModel):
    workers: list[WorkerRow]


class JobStarted(BaseModel):
    job_id: str


class JobState(BaseModel):
    status: str  # working | done | failed | lost
    fraction: float = 0.0
    label: str = ""
    error: str | None = None


def _directory(request: Request) -> WorkerDirectory:
    found = getattr(request.app.state, "engine_workers", None)
    if found is None:
        raise HTTPException(404, "This deployment has no engine workers.")
    return found  # type: ignore[no-any-return]


async def _audit(request: Request, who: Identity, action: str, target: str, **detail: Any) -> None:
    await request.app.state.admin.audit(
        who.tenant_id,
        AuditEntry(
            id="", actor_user_id=who.user_id, action=action, target_type="worker",
            target_id=target, detail=detail,
        ),
    )  # fmt: skip


def _model(m: dict[str, Any]) -> ModelRow:
    return ModelRow(
        id=m["id"], title=m.get("title", m["id"]), state=str(m.get("state", "")),
        bytes_missing=int(m.get("bytes_missing") or 0), licence=str(m.get("licence", "")),
        commercial_use=str(m.get("commercial_use", "unreviewed")),
        tasks=[str(t) for t in m.get("tasks", [])], engine=str(m.get("engine", "")),
        runtime_ready=bool(m.get("runtime_ready", False)),
    )  # fmt: skip


@router.get("", response_model=WorkerList)
async def list_workers(request: Request, who: Identity = Depends(require_admin)) -> WorkerList:
    directory = _directory(request)
    await directory.refresh()
    rows = [
        WorkerRow(
            id=w.id,
            busy=w.busy,
            seen=w.seen,
            can_fetch=admin_wire.FETCH_MODEL in w.kinds,
            models=[_model(m) for m in w.models],
            lipsync_engine=w.components.get(admin_wire.LIPSYNC_COMPONENT),
            components={
                k: {"ready": v.get("ready"), "problem": v.get("problem")}
                for k, v in w.components.items()
                if k != admin_wire.LIPSYNC_COMPONENT
            },
        )
        for w in directory.workers
    ]
    return WorkerList(workers=rows)


async def _start(
    request: Request, who: Identity, kind: str, key: str, params: dict[str, Any]
) -> JobStarted:
    directory = _directory(request)
    queue = directory.queue
    running: dict[str, str] = request.app.state.__dict__.setdefault("admin_fetches", {})
    existing = running.get(f"{who.tenant_id}/{kind}/{key}")
    if existing and await queue.status(existing) == "waiting":
        return JobStarted(job_id=existing)  # already on its way: follow that one
    job_id = str(uuid4())
    await queue.submit(
        EngineJob(
            id=job_id,
            kind=kind,
            tenant_id=who.tenant_id,
            product_id=PRODUCT,
            user_id=who.user_id,
            prefix=object_key(who.tenant_id, PRODUCT, who.user_id, "engine", job_id),
            params=params,
        )  # fmt: skip
    )
    running[f"{who.tenant_id}/{kind}/{key}"] = job_id
    await _audit(request, who, "admin.worker.fetch", key, kind=kind)
    return JobStarted(job_id=job_id)


@router.post("/models/{model_id}/fetch", response_model=JobStarted, status_code=202)
async def fetch_model(
    model_id: str, request: Request, who: Identity = Depends(require_admin)
) -> JobStarted:
    directory = _directory(request)
    await directory.refresh()
    workers = [w for w in directory.workers if admin_wire.FETCH_MODEL in w.kinds]
    if not workers:
        raise HTTPException(409, "No worker is running that can fetch models.")
    listed = [m for w in workers for m in w.models if m.get("id") == model_id]
    if not listed:
        raise HTTPException(404, "No worker lists that model.")
    if all(m.get("state") == "ready" for m in listed):
        raise HTTPException(409, "That model is already on the worker.")
    return await _start(request, who, admin_wire.FETCH_MODEL, model_id, {"model_id": model_id})


@router.post("/engines/{name}/fetch", response_model=JobStarted, status_code=202)
async def fetch_engine(
    name: str, request: Request, who: Identity = Depends(require_admin)
) -> JobStarted:
    if name not in admin_wire.ENGINES:
        raise HTTPException(404, "There is no such component.")
    directory = _directory(request)
    await directory.refresh()
    if not any(admin_wire.FETCH_ENGINE in w.kinds for w in directory.workers):
        raise HTTPException(409, "No worker is running that can set that up.")
    return await _start(request, who, admin_wire.FETCH_ENGINE, name, {"name": name})


@router.get("/jobs/{job_id}", response_model=JobState)
async def job_state(
    job_id: str, request: Request, who: Identity = Depends(require_admin)
) -> JobState:
    queue = _directory(request).queue
    outcome = await queue.peek(job_id)
    if outcome is not None:
        if outcome.ok:
            return JobState(status="done", fraction=1.0)
        return JobState(
            status="failed", error=outcome.error.message if outcome.error else "It did not finish."
        )
    if await queue.status(job_id) == "lost":
        return JobState(status="lost", error="That job is not known to the workers any more.")
    progress = await queue.progress_of(job_id)
    fraction, label = progress or (0.0, "Waiting for the worker")
    return JobState(status="working", fraction=fraction, label=label)
