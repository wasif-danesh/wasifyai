"""Events the window listens to (`GET /desktop/events`, server-sent): an approval an agent is
waiting for (ADR-0069 decision 8), later a job from a connection. One in-process bus, one stream
per open window; nothing is kept, a window that was away reads the pending list on open."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from wasifyai_api.identity import Identity, get_identity

KEEPALIVE_S = 15


class EventBus:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def listeners(self) -> int:
        return len(self._queues)

    def publish(self, kind: str, **data: Any) -> None:
        event = {"kind": kind, **data}
        for q in list(self._queues):
            q.put_nowait(event)

    async def stream(self) -> AsyncIterator[str]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues.add(q)
        try:
            yield ": open\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), KEEPALIVE_S)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"event: {event['kind']}\ndata: {json.dumps(event)}\n\n"
        finally:
            self._queues.discard(q)


router = APIRouter(prefix="/desktop", tags=["desktop"])


@router.get("/events")
async def desktop_events(
    request: Request, _: Identity = Depends(get_identity)
) -> StreamingResponse:
    bus: EventBus = request.app.state.events
    return StreamingResponse(
        bus.stream(), media_type="text/event-stream", headers={"cache-control": "no-cache"}
    )
