"""The product's read API: a user's images (ADR-0023, ADR-0036), under /products/wasifyai-image/.

Every query is scoped by tenant, product and user, and every link is signed fresh, so an image can
be opened any time (the links themselves expire after an hour)."""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict
from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    SaveRefused,
    SaveTo,
    UploadError,
    build_enhance_router,
    parse_ids,
    process_image,
    write_to_path,
)

from wasifyai_image import prompts
from wasifyai_image.images import ImageRecord, ImageStore, image_store, thumbnail_of
from wasifyai_image.index import index_text

PRODUCT_ID = "wasifyai-image"
CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


class ImageSummary(BaseModel):
    id: str
    prompt: str
    mode: str
    width: int
    height: int
    created_at: datetime
    image_url: str
    thumb_url: str
    recipe: dict | None = None  # null on images made before recipes existed
    favourite: bool = False
    # the picture of the library this one was made from (Edit, Inpaint, Reference), or null
    source_id: str | None = None


class ImageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    favourite: bool


class Exported(BaseModel):
    name: str
    path: str


class ImagePage(BaseModel):
    images: list[ImageSummary]
    next_before: datetime | None  # pass as `before` to get the next page; null at the end


def file_name(prompt: str, ext: str) -> str:
    """A safe, readable file name from the prompt: letters, digits and hyphens only."""
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:48].strip("-") or "image"
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


log = logging.getLogger(__name__)
MAX_IMPORT_BYTES = 40 * 2**20


def build_routes(deps: RouteDeps, store: ImageStore | None = None) -> APIRouter:
    """`store` is injectable for tests; production reads the shared database."""
    router = APIRouter(tags=[PRODUCT_ID])
    router.include_router(build_enhance_router(deps, PRODUCT_ID, prompts.load))

    def images() -> ImageStore:
        return store or image_store(deps.engine)

    async def summary(image: ImageRecord) -> ImageSummary:
        assert deps.storage is not None, "object storage is not configured"
        assert image.created_at is not None
        return ImageSummary(
            id=image.id, prompt=image.prompt, mode=image.mode, width=image.width,
            height=image.height, created_at=image.created_at,
            image_url=await deps.storage.url(image.image_key),
            thumb_url=await deps.storage.url(image.thumb_key),
            recipe=image.recipe, favourite=image.favourite, source_id=image.source_id,
        )  # fmt: skip

    @router.post("/images/import", response_model=ImageSummary, status_code=201)
    async def import_image(
        file: UploadFile = File(...),  # noqa: B008
        identity: Identity = Depends(deps.identity),
    ) -> ImageSummary:
        """Add a picture of the person's to their library. It is decoded and stored again as a clean
        PNG: the file is never kept as sent."""
        if deps.storage is None:
            raise HTTPException(503, "file storage is not available")
        limiter = deps.state.upload_limiter
        if limiter is not None and not await limiter.allow(identity.tenant_id, identity.user_id):
            raise HTTPException(429, "Too many uploads. Please wait a while and try again.")
        data = await file.read(MAX_IMPORT_BYTES + 1)
        if not data:
            raise HTTPException(422, "No file was sent.")
        if len(data) > MAX_IMPORT_BYTES:
            raise HTTPException(
                413, f"That file is too large. The limit is {MAX_IMPORT_BYTES // 2**20} MB."
            )
        try:
            clean = await asyncio.to_thread(process_image, data)
        except UploadError as e:
            raise HTTPException(e.status, e.message) from None
        width, height, thumb = await thumbnail_of(clean.png)
        image_id = str(uuid4())
        title = re.sub(r"\s+", " ", re.sub(r"[_\-\x00-\x1f]+", " ", Path(file.filename or "").stem))
        title = title.strip()[:120] or "My picture"
        image_key, thumb_key = f"{image_id}/image.png", f"{image_id}/thumb.jpg"
        with deps.acting_as(identity, PRODUCT_ID):
            await deps.storage.put(image_key, clean.png, "image/png")
            await deps.storage.put(thumb_key, thumb, "image/jpeg")
        await images().add(
            ImageRecord(
                id=image_id, tenant_id=identity.tenant_id, product_id=PRODUCT_ID,
                user_id=identity.user_id, thread_id=None, run_id=None, mode="import", prompt=title,
                width=width, height=height, image_key=image_key, thumb_key=thumb_key,
            )
        )  # fmt: skip
        index = deps.state.creation_index  # found in search at once (ADR-0041)
        if index is not None:
            try:
                await index.index(
                    identity.tenant_id, PRODUCT_ID, identity.user_id, "image", image_id,
                    index_text(title),
                )  # fmt: skip
            except Exception:
                log.warning("the added picture could not be put in search", exc_info=True)
        made = await images().get(identity.tenant_id, identity.user_id, image_id)
        assert made is not None
        with deps.acting_as(identity, PRODUCT_ID):
            return await summary(made)

    @router.get("/images", response_model=ImagePage)
    async def list_images(
        limit: int = Query(20, ge=1, le=50),
        before: datetime | None = None,
        ids: str | None = Query(None, max_length=2000),
        favourites: bool = False,
        source: str | None = Query(None, max_length=64),  # the pictures made from this one
        identity: Identity = Depends(deps.identity),
    ) -> ImagePage:
        wanted = parse_ids(ids)  # "these images, in this order": the cards for search results
        if wanted is not None:
            found = [await images().get(identity.tenant_id, identity.user_id, i) for i in wanted]
            with deps.acting_as(identity, PRODUCT_ID):
                got = [await summary(i) for i in found if i is not None]
            return ImagePage(images=got, next_before=None)
        rows = await images().list(
            identity.tenant_id,
            identity.user_id,
            limit + 1,
            before,
            favourites_only=favourites,
            source_id=source,
        )
        page, more = rows[:limit], len(rows) > limit
        with deps.acting_as(identity, PRODUCT_ID):
            items = [await summary(i) for i in page]
        return ImagePage(images=items, next_before=page[-1].created_at if more and page else None)

    @router.get("/images/{image_id}", response_model=ImageSummary)
    async def get_image(image_id: str, identity: Identity = Depends(deps.identity)) -> ImageSummary:
        image = await images().get(identity.tenant_id, identity.user_id, image_id)
        if image is None:  # also what another user's image looks like: no existence leak
            raise HTTPException(404, "image not found")
        with deps.acting_as(identity, PRODUCT_ID):
            return await summary(image)

    @router.patch("/images/{image_id}", response_model=ImageSummary)
    async def update_image(
        image_id: str, body: ImageUpdate, identity: Identity = Depends(deps.identity)
    ) -> ImageSummary:
        """Mark or unmark a favourite."""
        found = await images().set_favourite(
            identity.tenant_id, identity.user_id, image_id, body.favourite
        )
        image = await images().get(identity.tenant_id, identity.user_id, image_id)
        if not found or image is None:
            raise HTTPException(404, "image not found")
        with deps.acting_as(identity, PRODUCT_ID):
            return await summary(image)

    @router.post("/images/{image_id}/export", response_model=Exported)
    async def export_image(
        image_id: str, body: SaveTo | None = None, identity: Identity = Depends(deps.identity)
    ) -> Exported:
        """Copy the image to the place the person chose in the Save As box (`path`), or into the
        export folder when there is none: a webview cannot save a file by itself. The folder never
        overwrites: a second copy gets a number."""
        folder = deps.state.export_dir
        if (folder is None and not (body and body.path)) or deps.storage is None:
            raise HTTPException(404, "saving to a folder is not available here")
        image = await images().get(identity.tenant_id, identity.user_id, image_id)
        if image is None:
            raise HTTPException(404, "image not found")
        try:
            with deps.acting_as(identity, PRODUCT_ID):
                data = await deps.storage.get(image.image_key)
        except FileNotFoundError:
            raise HTTPException(404, "image not found") from None
        ext = image.image_key.rsplit(".", 1)[-1].lower()
        if body and body.path:
            try:
                path = await asyncio.to_thread(
                    write_to_path, body.path, data, deps.state.desktop_dir
                )
            except SaveRefused as exc:
                raise HTTPException(422, str(exc)) from None
        else:
            assert folder is not None  # the check above: no path means a folder
            path = await asyncio.to_thread(
                save_copy, Path(folder), file_name(image.prompt, ""), ext, data
            )
        return Exported(name=path.name, path=str(path))

    @router.get("/images/{image_id}/download")
    async def download(image_id: str, identity: Identity = Depends(deps.identity)) -> Response:
        """The image as a file the browser saves (browsers ignore `download` on links to the
        storage host, ADR-0034)."""
        assert deps.storage is not None, "object storage is not configured"
        image = await images().get(identity.tenant_id, identity.user_id, image_id)
        if image is None:
            raise HTTPException(404, "image not found")
        try:
            with deps.acting_as(identity, PRODUCT_ID):
                data = await deps.storage.get(image.image_key)
        except FileNotFoundError:
            raise HTTPException(404, "image not found") from None
        ext = image.image_key.rsplit(".", 1)[-1].lower()
        return Response(
            data,
            media_type=CONTENT_TYPES.get(ext, "application/octet-stream"),
            headers={
                "Content-Disposition": f'attachment; filename="{file_name(image.prompt, ext)}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.delete("/images/{image_id}", status_code=204)
    async def delete_image(image_id: str, identity: Identity = Depends(deps.identity)) -> Response:
        """Delete an image: its files first, then the record."""
        assert deps.storage is not None, "object storage is not configured"
        image = await images().get(identity.tenant_id, identity.user_id, image_id)
        if image is None:
            raise HTTPException(404, "image not found")
        with deps.acting_as(identity, PRODUCT_ID):
            for key in (image.image_key, image.thumb_key):
                try:
                    await deps.storage.delete(key)
                except FileNotFoundError:
                    pass
        await images().delete(identity.tenant_id, identity.user_id, image_id)
        await deps.unindex(identity, PRODUCT_ID, image_id)  # out of search too (ADR-0041)
        return Response(status_code=204)

    return router
