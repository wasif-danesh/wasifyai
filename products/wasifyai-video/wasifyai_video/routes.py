"""The product's read API: a user's clips (ADR-0023, ADR-0037), under /products/wasifyai-video/.

Every query is scoped by tenant, product and user, and every link is signed fresh, so a clip can be
opened any time (the links themselves expire after an hour). A clip still being made has a row but
no files yet; the site polls `GET /videos?status=working` to show "being made" on any page."""

import asyncio
import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    SaveRefused,
    SaveTo,
    build_enhance_router,
    parse_ids,
    write_to_path,
)

from wasifyai_video import prompts
from wasifyai_video.builder.routes import build_builder_routes
from wasifyai_video.guardrail import enhance_guard
from wasifyai_video.index import index_text
from wasifyai_video.schemas import FPS
from wasifyai_video.videos import (
    ClipError,
    PosterError,
    VideoRecord,
    VideoStore,
    import_clip,
    poster_of,
    video_store,
)

log = logging.getLogger(__name__)
PRODUCT_ID = "wasifyai-video"
MAX_IMPORT_BYTES = 200 * 1024 * 1024


class VideoSummary(BaseModel):
    id: str
    prompt: str
    mode: str
    status: Literal["working", "done", "failed"]
    seconds: int
    created_at: datetime
    width: int | None = None
    height: int | None = None
    error: str | None = None  # plain text for the user, only when status is "failed"
    video_url: str | None = None  # only when status is "done"
    poster_url: str | None = None


class Exported(BaseModel):
    name: str
    path: str


class VideoPage(BaseModel):
    videos: list[VideoSummary]
    next_before: datetime | None  # pass as `before` to get the next page; null at the end


MEDIA = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}


def extension_of(video_key: str | None) -> str:
    """The kind of file a clip is (Video Builder can make a transparent WebM or a MOV)."""
    ext = (video_key or "").rsplit(".", 1)[-1].lower()
    return ext if ext in MEDIA else "mp4"


def file_name(prompt: str, ext: str) -> str:
    """A safe, readable file name from the prompt: letters, digits and hyphens only."""
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:48].strip("-") or "video"
    return f"{slug}.{ext}" if ext else slug


def save_copy(folder: Path, stem: str, ext: str, data: bytes) -> Path:
    """Write `data` as `stem.ext` in `folder`, as `stem-2.ext` and so on when that name is taken."""
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"{stem}.{ext}", 1
    while True:
        try:
            with path.open("xb") as f:  # exclusive: never replaces a file
                f.write(data)
            return path
        except FileExistsError:
            n += 1
            path = folder / f"{stem}-{n}.{ext}"


def build_routes(deps: RouteDeps, store: VideoStore | None = None) -> APIRouter:
    """`store` is injectable for tests; production reads the shared database."""
    router = APIRouter(tags=[PRODUCT_ID])
    router.include_router(build_enhance_router(deps, PRODUCT_ID, prompts.load, enhance_guard))
    router.include_router(build_builder_routes(deps))  # Video Builder (ADR-0077), desktop only

    def videos() -> VideoStore:
        return store or video_store(deps.engine)

    async def summary(video: VideoRecord) -> VideoSummary:
        assert deps.storage is not None, "object storage is not configured"
        assert video.created_at is not None
        done = video.status == "done" and video.video_key and video.poster_key
        return VideoSummary(
            id=video.id, prompt=video.prompt, mode=video.mode, status=video.status,  # type: ignore[arg-type]
            seconds=video.seconds, created_at=video.created_at, width=video.width,
            height=video.height, error=video.error if video.status == "failed" else None,
            video_url=await deps.storage.url(video.video_key) if done and video.video_key else None,
            poster_url=(
                await deps.storage.url(video.poster_key) if done and video.poster_key else None
            ),
        )  # fmt: skip

    @router.get("/videos", response_model=VideoPage)
    async def list_videos(
        limit: int = Query(20, ge=1, le=50),
        before: datetime | None = None,
        status: Literal["working", "done", "failed"] | None = None,
        ids: str | None = Query(None, max_length=2000),
        identity: Identity = Depends(deps.identity),
    ) -> VideoPage:
        wanted = parse_ids(ids)  # "these clips, in this order": the cards for search results
        if wanted is not None:
            found = [await videos().get(identity.tenant_id, identity.user_id, i) for i in wanted]
            with deps.acting_as(identity, PRODUCT_ID):
                got = [await summary(v) for v in found if v is not None]
            return VideoPage(videos=got, next_before=None)
        rows = await videos().list(identity.tenant_id, identity.user_id, limit + 1, before, status)
        page, more = rows[:limit], len(rows) > limit
        with deps.acting_as(identity, PRODUCT_ID):
            items = [await summary(v) for v in page]
        return VideoPage(videos=items, next_before=page[-1].created_at if more and page else None)

    @router.post("/videos/import", response_model=VideoSummary, status_code=201)
    async def import_video(
        file: UploadFile = File(...),  # noqa: B008
        identity: Identity = Depends(deps.identity),
    ) -> VideoSummary:
        """Add a video file of the person's to their library, made to fit the model (H.264, 24
        frames a second, a multiple of 32 on each side, at most 30 seconds, no sound or tags), so
        it can be carried on in Extend video. ffmpeg decodes it: the file is never kept as sent."""
        if deps.storage is None:
            raise HTTPException(503, "file storage is not available")
        limiter = getattr(deps.state, "upload_limiter", None)
        if limiter is not None and not await limiter.allow(identity.tenant_id, identity.user_id):
            raise HTTPException(429, "Too many uploads. Please wait a while and try again.")
        with tempfile.TemporaryDirectory(prefix="wasifyai-video-") as tmp:
            source, out = Path(tmp) / "added", Path(tmp) / "clip.mp4"
            size = 0
            with source.open("wb") as f:  # to disk in pieces: a video can be large
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_IMPORT_BYTES:
                        raise HTTPException(
                            413,
                            f"That file is too large. The limit is {MAX_IMPORT_BYTES // 2**20} MB.",
                        )
                    await asyncio.to_thread(f.write, chunk)
            if not size:
                raise HTTPException(422, "No file was sent.")
            try:
                width, height, frames = await import_clip(source, out)
                data = await asyncio.to_thread(out.read_bytes)
                _, _, poster = await poster_of(data)
            except (ClipError, PosterError) as exc:
                raise HTTPException(422, str(exc)) from None
        video_id = str(uuid4())
        title = re.sub(r"\s+", " ", re.sub(r"[_\-\x00-\x1f]+", " ", Path(file.filename or "").stem))
        title = title.strip()[:120] or "My video"
        with deps.acting_as(identity, PRODUCT_ID):
            await deps.storage.put(f"{video_id}/video.mp4", data, "video/mp4")
            await deps.storage.put(f"{video_id}/poster.jpg", poster, "image/jpeg")
        await videos().add(
            VideoRecord(
                id=video_id, tenant_id=identity.tenant_id, product_id=PRODUCT_ID,
                user_id=identity.user_id, thread_id=None, run_id=None, mode="import",
                status="working", prompt=title, seconds=max(1, round(frames / FPS)),
                frames=frames, fps=FPS,
            )
        )  # fmt: skip
        await videos().finish(
            identity.tenant_id, video_id, width, height, f"{video_id}/video.mp4",
            f"{video_id}/poster.jpg",
        )  # fmt: skip
        index = getattr(deps.state, "creation_index", None)  # found in search at once (ADR-0041)
        if index is not None:
            try:
                await index.index(
                    identity.tenant_id, PRODUCT_ID, identity.user_id, "video", video_id,
                    index_text(title),
                )  # fmt: skip
            except Exception:
                log.warning("the added video could not be put in search", exc_info=True)
        made = await videos().get(identity.tenant_id, identity.user_id, video_id)
        assert made is not None
        with deps.acting_as(identity, PRODUCT_ID):
            return await summary(made)

    @router.get("/videos/{video_id}", response_model=VideoSummary)
    async def get_video(video_id: str, identity: Identity = Depends(deps.identity)) -> VideoSummary:
        video = await videos().get(identity.tenant_id, identity.user_id, video_id)
        if video is None:  # also what another user's clip looks like: no existence leak
            raise HTTPException(404, "video not found")
        with deps.acting_as(identity, PRODUCT_ID):
            return await summary(video)

    @router.post("/videos/{video_id}/export", response_model=Exported)
    async def export_video(
        video_id: str, body: SaveTo | None = None, identity: Identity = Depends(deps.identity)
    ) -> Exported:
        """Copy the clip to the place the person chose in the Save As box (`path`), or into the
        export folder when there is none: a webview cannot save a file by itself. The folder never
        overwrites: a second copy gets a number."""
        folder = getattr(deps.state, "export_dir", None)
        if (folder is None and not (body and body.path)) or deps.storage is None:
            raise HTTPException(404, "saving to a folder is not available here")
        video = await videos().get(identity.tenant_id, identity.user_id, video_id)
        if video is None or video.status != "done" or not video.video_key:
            raise HTTPException(404, "video not found")
        try:
            with deps.acting_as(identity, PRODUCT_ID):
                data = await deps.storage.get(video.video_key)
        except FileNotFoundError:
            raise HTTPException(404, "video not found") from None
        if body and body.path:
            try:
                path = await asyncio.to_thread(
                    write_to_path, body.path, data, getattr(deps.state, "desktop_dir", None)
                )
            except SaveRefused as exc:
                raise HTTPException(422, str(exc)) from None
        else:
            assert folder is not None  # the check above: no path means a folder
            path = await asyncio.to_thread(
                save_copy,
                Path(folder),
                file_name(video.prompt, ""),
                extension_of(video.video_key),
                data,
            )
        return Exported(name=path.name, path=str(path))

    @router.get("/videos/{video_id}/download")
    async def download(video_id: str, identity: Identity = Depends(deps.identity)) -> Response:
        """The clip as a file the browser saves (browsers ignore `download` on links to the
        storage host, ADR-0034)."""
        assert deps.storage is not None, "object storage is not configured"
        video = await videos().get(identity.tenant_id, identity.user_id, video_id)
        if video is None or video.status != "done" or not video.video_key:
            raise HTTPException(404, "video not found")
        try:
            with deps.acting_as(identity, PRODUCT_ID):
                data = await deps.storage.get(video.video_key)
        except FileNotFoundError:
            raise HTTPException(404, "video not found") from None
        ext = extension_of(video.video_key)
        return Response(
            data,
            media_type=MEDIA[ext],
            headers={
                "Content-Disposition": f'attachment; filename="{file_name(video.prompt, ext)}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.delete("/videos/{video_id}", status_code=204)
    async def delete_video(video_id: str, identity: Identity = Depends(deps.identity)) -> Response:
        """Delete a clip (or dismiss a failed one): its files first, then the record. A clip still
        being made cannot be deleted: its job is running."""
        assert deps.storage is not None, "object storage is not configured"
        video = await videos().get(identity.tenant_id, identity.user_id, video_id)
        if video is None:
            raise HTTPException(404, "video not found")
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
        await videos().delete(identity.tenant_id, identity.user_id, video_id)
        await deps.unindex(identity, PRODUCT_ID, video_id)  # out of search too (ADR-0041)
        return Response(status_code=204)

    return router
