"""The product's read API: a user's lip syncs (ADR-0044), under /products/wasifyai-lipsync/.

Every query is scoped by tenant, product and user, and every link is signed fresh, so a clip can be
opened any time (the links themselves expire after an hour). A clip still being made has a row but
no files yet; the site polls `GET /lipsyncs?status=working` to show "being made" on any page."""

import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity, RouteDeps, parse_ids

from wasifyai_lipsync.lipsyncs import LipSyncRecord, LipSyncStore, PostgresLipSyncStore

PRODUCT_ID = "wasifyai-lipsync"


class LipSyncSummary(BaseModel):
    id: str
    text: str  # the script, or the words of the voice when they were checked; may be empty
    style: str
    source: str
    status: Literal["working", "done", "failed"]
    seconds: float
    created_at: datetime
    width: int | None = None
    height: int | None = None
    error: str | None = None  # plain text for the user, only when status is "failed"
    video_url: str | None = None  # only when status is "done"
    poster_url: str | None = None


class LipSyncPage(BaseModel):
    lipsyncs: list[LipSyncSummary]
    next_before: datetime | None  # pass as `before` to get the next page; null at the end


def file_name(text: str, ext: str) -> str:
    """A safe, readable file name from the words: letters, digits and hyphens only."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48].strip("-") or "lip-sync"
    return f"{slug}.{ext}" if ext else slug


def build_routes(deps: RouteDeps, store: LipSyncStore | None = None) -> APIRouter:
    """`store` is injectable for tests; production reads the shared database."""
    router = APIRouter(tags=[PRODUCT_ID])

    def store_() -> LipSyncStore:
        return store or PostgresLipSyncStore(deps.engine)

    async def summary(video: LipSyncRecord) -> LipSyncSummary:
        assert deps.storage is not None, "object storage is not configured"
        assert video.created_at is not None
        done = video.status == "done" and video.video_key and video.poster_key
        return LipSyncSummary(
            id=video.id, text=video.script or video.transcript, style=video.style,
            source=video.source, status=video.status,  # type: ignore[arg-type]
            seconds=video.seconds, created_at=video.created_at, width=video.width,
            height=video.height, error=video.error if video.status == "failed" else None,
            video_url=await deps.storage.url(video.video_key) if done and video.video_key else None,
            poster_url=(
                await deps.storage.url(video.poster_key) if done and video.poster_key else None
            ),
        )  # fmt: skip

    @router.get("/lipsyncs", response_model=LipSyncPage)
    async def list_lipsyncs(
        limit: int = Query(20, ge=1, le=50),
        before: datetime | None = None,
        status: Literal["working", "done", "failed"] | None = None,
        ids: str | None = Query(None, max_length=2000),
        identity: Identity = Depends(deps.identity),
    ) -> LipSyncPage:
        wanted = parse_ids(ids)  # "these clips, in this order": the cards for search results
        if wanted is not None:
            found = [await store_().get(identity.tenant_id, identity.user_id, i) for i in wanted]
            with deps.acting_as(identity, PRODUCT_ID):
                got = [await summary(v) for v in found if v is not None]
            return LipSyncPage(lipsyncs=got, next_before=None)
        rows = await store_().list(identity.tenant_id, identity.user_id, limit + 1, before, status)
        page, more = rows[:limit], len(rows) > limit
        with deps.acting_as(identity, PRODUCT_ID):
            items = [await summary(v) for v in page]
        return LipSyncPage(
            lipsyncs=items, next_before=page[-1].created_at if more and page else None
        )

    @router.get("/lipsyncs/{video_id}", response_model=LipSyncSummary)
    async def get_lipsync(
        video_id: str, identity: Identity = Depends(deps.identity)
    ) -> LipSyncSummary:
        video = await store_().get(identity.tenant_id, identity.user_id, video_id)
        if video is None:  # also what another user's clip looks like: no existence leak
            raise HTTPException(404, "lip sync not found")
        with deps.acting_as(identity, PRODUCT_ID):
            return await summary(video)

    @router.get("/lipsyncs/{video_id}/download")
    async def download(video_id: str, identity: Identity = Depends(deps.identity)) -> Response:
        """The clip as a file the browser saves (browsers ignore `download` on links to the
        storage host, ADR-0034)."""
        assert deps.storage is not None, "object storage is not configured"
        video = await store_().get(identity.tenant_id, identity.user_id, video_id)
        if video is None or video.status != "done" or not video.video_key:
            raise HTTPException(404, "lip sync not found")
        try:
            with deps.acting_as(identity, PRODUCT_ID):
                data = await deps.storage.get(video.video_key)
        except FileNotFoundError:
            raise HTTPException(404, "lip sync not found") from None
        name = file_name(video.script or video.transcript, "mp4")
        return Response(
            data,
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.delete("/lipsyncs/{video_id}", status_code=204)
    async def delete_lipsync(
        video_id: str, identity: Identity = Depends(deps.identity)
    ) -> Response:
        """Delete a clip (or dismiss a failed one): its files first, then the record. A clip still
        being made cannot be deleted: its job is running."""
        assert deps.storage is not None, "object storage is not configured"
        video = await store_().get(identity.tenant_id, identity.user_id, video_id)
        if video is None:
            raise HTTPException(404, "lip sync not found")
        if video.status == "working":
            raise HTTPException(409, "That video is still being made.")
        with deps.acting_as(identity, PRODUCT_ID):
            for key in (video.video_key, video.poster_key):
                if not key:
                    continue
                try:
                    await deps.storage.delete(key)
                except FileNotFoundError:
                    pass
        await store_().delete(identity.tenant_id, identity.user_id, video_id)
        await deps.unindex(identity, PRODUCT_ID, video_id)  # out of search too (ADR-0041)
        return Response(status_code=204)

    return router
