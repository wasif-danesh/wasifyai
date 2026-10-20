from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from wasifyai_contracts import TERMINAL_EVENTS, ResumeRequest, RunRequest, format_sse_dict
from wasifyai_platform_sdk import RunRecord

from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.runs import RunIdTaken

router = APIRouter()
HEARTBEAT_S = 15

SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def _state(request: Request) -> Any:
    return request.app.state


async def _stream(st: Any, rec: RunRecord, after: int) -> AsyncIterator[str]:
    """Read the run's events from the shared log until the run ends or waits for the user."""
    sent = after
    block_ms = max(int(st.heartbeat_s * 1000), 1)
    while True:
        events = await st.runs.log.read(rec.tenant_id, rec.run_id, sent, block_ms)
        if not events:
            current = await st.runs.store.get(rec.tenant_id, rec.run_id)
            last = await st.runs.log.last_seq(rec.tenant_id, rec.run_id)
            if current and current.status in ("done", "error", "cancelled") and sent >= last:
                return
            yield ": ping\n\n"
            continue
        for ev in events:
            yield format_sse_dict(ev)
            sent = ev["seq"]
            if ev["event"] in TERMINAL_EVENTS:
                return
            if ev["event"] == "interrupt":
                current = await st.runs.store.get(rec.tenant_id, rec.run_id)
                last = await st.runs.log.last_seq(rec.tenant_id, rec.run_id)
                if current and current.awaiting and ev["seq"] == last:
                    return


def _sse(request: Request, rec: RunRecord, after: int = 0) -> StreamingResponse:
    return StreamingResponse(
        _stream(_state(request), rec, after),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def _owned_run(request: Request, run_id: UUID, identity: Identity) -> RunRecord:
    rec = await _state(request).runs.store.get(identity.tenant_id, str(run_id))
    if rec is None or rec.user_id != identity.user_id:
        raise HTTPException(404, "run not found")
    return rec


@router.post("/products/{product_id}/runs")
async def start_run(
    product_id: str,
    body: RunRequest,
    request: Request,
    identity: Identity = Depends(get_identity),
):
    st: Any = _state(request)
    # served here: registered, and not left out by PRODUCTS_ENABLED
    if product_id not in st.registry.products() or product_id not in st.runs.graphs:
        raise HTTPException(404, "unknown product")
    try:
        rec = await st.runs.start(
            product_id,
            identity.tenant_id,
            identity.user_id,
            body.thread_id,
            body.input,
            body.run_id,
        )
    except RunIdTaken:
        raise HTTPException(409, "that run id is already in use") from None
    return _sse(
        request, rec
    )  # a repeated start under the same run id replays that run from its first event


@router.get("/runs/{run_id}/events")
async def run_events(run_id: UUID, request: Request, identity: Identity = Depends(get_identity)):
    rec = await _owned_run(request, run_id, identity)
    last = request.headers.get("last-event-id", "0")
    return _sse(request, rec, int(last) if last.isdigit() else 0)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: UUID, request: Request, identity: Identity = Depends(get_identity)):
    """Stop a run (the Stop button). A run that is already over is not an error: the answer says
    how it ended."""
    st: Any = _state(request)
    rec = await _owned_run(request, run_id, identity)
    return {"run_id": rec.run_id, "status": await st.runs.cancel(rec)}


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: UUID,
    body: ResumeRequest,
    request: Request,
    identity: Identity = Depends(get_identity),
):
    st: Any = _state(request)
    rec = await _owned_run(request, run_id, identity)
    # Atomic: two concurrent resumes cannot both win.
    if await st.runs.store.take_awaiting(rec.tenant_id, rec.run_id) is None:
        raise HTTPException(409, "run is not waiting for input")
    after = await st.runs.log.last_seq(rec.tenant_id, rec.run_id)
    st.runs.resume(rec, body.value)
    return _sse(request, rec, after)
