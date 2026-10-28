"""The product's read API: a user's images (ADR-0023, ADR-0036), under /products/wasifyai-image/.

Every query is scoped by tenant, product and user, and every link is signed fresh, so an image can
be opened any time (the links themselves expire after an hour)."""

import asyncio
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    SaveRefused,
    SaveTo,
    build_enhance_router,
    parse_ids,
    write_to_path,
)

from wasifyai_image import prompts
from wasifyai_image.guardrail import enhance_guard
from wasifyai_image.images import ImageRecord, ImageStore, image_store

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


def build_routes(deps: RouteDeps, store: ImageStore | None = None) -> APIRouter:
    """`store` is injectable for tests; production reads the shared database."""
    router = APIRouter(tags=[PRODUCT_ID])
    router.include_router(build_enhance_router(deps, PRODUCT_ID, prompts.load, enhance_guard))

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
        folder = getattr(deps.state, "export_dir", None)
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
                    write_to_path, body.path, data, getattr(deps.state, "desktop_dir", None)
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
