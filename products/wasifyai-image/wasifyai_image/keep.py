"""A picture of the person's added to their library: the Images import button, and a picture
attached in the chat that the person asks to work on (docs/chat-does-everything-plan.md, CE1).

The bytes are untrusted. They are decoded and stored again as a clean PNG (ADR-0035); the file is
never kept as sent. The picture is put in search at once (ADR-0041)."""

import asyncio
import logging
import re
from pathlib import Path
from uuid import uuid4

from wasifyai_platform_sdk import Identity, process_image

from wasifyai_image.images import ImageRecord, ImageStore, thumbnail_of
from wasifyai_image.index import index_text

PRODUCT_ID = "wasifyai-image"
log = logging.getLogger(__name__)


def title_of(name: str | None) -> str:
    """A picture's name from its file name: no extension, no underscores, at most 120 letters."""
    stem = Path(name or "").stem
    title = re.sub(r"\s+", " ", re.sub(r"[_\-\x00-\x1f]+", " ", stem)).strip()[:120]
    return title or "My picture"


async def add_picture(
    deps, store: ImageStore, identity: Identity, data: bytes, title: str
) -> ImageRecord:
    """Store `data` as a new picture of the library and return its record. Raises `UploadError`
    for a file that is not a picture we can read."""
    clean = await asyncio.to_thread(process_image, data)
    width, height, thumb = await thumbnail_of(clean.png)
    image_id = str(uuid4())
    image_key, thumb_key = f"{image_id}/image.png", f"{image_id}/thumb.jpg"
    with deps.acting_as(identity, PRODUCT_ID):
        await deps.storage.put(image_key, clean.png, "image/png")
        await deps.storage.put(thumb_key, thumb, "image/jpeg")
    await store.add(
        ImageRecord(
            id=image_id, tenant_id=identity.tenant_id, product_id=PRODUCT_ID,
            user_id=identity.user_id, thread_id=None, run_id=None, mode="import", prompt=title,
            width=width, height=height, image_key=image_key, thumb_key=thumb_key,
        )
    )  # fmt: skip
    index = deps.state.creation_index
    if index is not None:
        try:
            await index.index(
                identity.tenant_id, PRODUCT_ID, identity.user_id, "image", image_id,
                index_text(title),
            )  # fmt: skip
        except Exception:
            log.warning("the added picture could not be put in search", exc_info=True)
    made = await store.get(identity.tenant_id, identity.user_id, image_id)
    assert made is not None
    return made
