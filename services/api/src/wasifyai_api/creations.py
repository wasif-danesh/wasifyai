"""Search over a user's own creations (ADR-0041): `GET /creations/search`.

The answer is a ranked list of references (kind, product, id); the web asks each product's list
route for the cards, because only a product can sign its files' links. Every query is scoped to
the caller."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import UploadLimiter, UsageEvent, UsageRecorder
from wasifyai_platform_sdk.usage import record_safely

from wasifyai_api.creation_index import PLATFORM, CreationIndex, long_enough
from wasifyai_api.identity import Identity, get_identity

router = APIRouter(tags=["creations"])
SEARCHED = "creation.searched"


class SearchHit(BaseModel):
    kind: Literal["song", "image", "video", "speech", "transcript", "lipsync"]
    product_id: str
    id: str
    score: float
    match: Literal["words", "meaning"]


class SearchResponse(BaseModel):
    query: str
    degraded: bool  # the embedder did not answer: only exact words were searched
    results: list[SearchHit]


@router.get("/creations/search", response_model=SearchResponse)
async def search_creations(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    kind: Literal["song", "image", "video", "speech", "transcript", "lipsync"] | None = None,
    limit: int = Query(20, ge=1, le=50),
    identity: Identity = Depends(get_identity),
) -> SearchResponse:
    state: Any = request.app.state
    index: CreationIndex | None = getattr(state, "creation_index", None)
    query = " ".join(q.split())
    if index is None:
        raise HTTPException(503, "Search is not available right now.")
    if not long_enough(query):
        raise HTTPException(422, "Please type at least two characters.")
    limiter: UploadLimiter = state.search_limiter
    if not await limiter.allow(identity.tenant_id, identity.user_id):
        raise HTTPException(429, "You've searched a lot. Please wait a while and try again.")
    hits, degraded = await index.search(identity.tenant_id, identity.user_id, query, kind, limit)
    recorder: UsageRecorder = state.usage
    await record_safely(
        recorder,
        UsageEvent(
            tenant_id=identity.tenant_id, product_id=PLATFORM, user_id=identity.user_id,
            kind=SEARCHED, quantity=1, unit="searches", meta={"results": len(hits), "kind": kind},
        ),
    )  # fmt: skip
    return SearchResponse(
        query=query,
        degraded=degraded,
        results=[
            SearchHit(
                kind=h.kind,  # type: ignore[arg-type]
                product_id=h.product_id,
                id=h.item_id,
                score=round(h.score, 4),
                match=h.match,  # type: ignore[arg-type]
            )
            for h in hits
        ],
    )
