"""Small things many products' actions need, written once."""

import asyncio
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk.actions.model import ActionRefused
from wasifyai_platform_sdk.uploads import UPLOAD_CREATED, UploadError, new_upload, process_image
from wasifyai_platform_sdk.usage import UsageEvent, record_safely


def need_deps(ctx: Any) -> Any:
    """The route deps of the engine (stores, storage, search), or a refusal where there are none."""
    deps = ctx.deps
    if deps is None or getattr(deps, "state", None) is None:
        raise ActionRefused("unavailable", "This is not available here.")
    return deps


CHAT_PRODUCT = "wasifyai-assistant"  # whose uploads the chat's attachments are (ADR-0083)


async def attached_document(ctx: Any, attachment_id: str) -> str:
    """The words of a document the person attached in the chat, or a refusal in words
    (docs/chat-does-everything-plan.md, CE4 and CE5). Only the person's own uploads are found."""
    deps = need_deps(ctx)
    a = ctx.actor
    gone = "That attached document is not there any more. Please attach it again."
    uploads, storage = getattr(deps.state, "uploads", None), deps.storage
    record = None
    if uploads is not None and storage is not None:
        key = f"uploads/{attachment_id.strip()}.txt"
        record = await uploads.find(a.tenant_id, CHAT_PRODUCT, a.user_id, key)
    if record is None or storage is None:
        raise ActionRefused("not_found", gone)
    try:
        with deps.acting_as(a, CHAT_PRODUCT):
            data = await storage.get(record.key)
    except FileNotFoundError:
        raise ActionRefused("not_found", gone) from None
    return data.decode("utf-8", errors="replace")


async def stage_picture(ctx: Any, product_id: str, data: bytes) -> str:
    """Put a picture of the library where a product's graph expects an uploaded one, as the upload
    route does (re-encoded, with nothing of the original's metadata), and return the key a run
    passes as `image_key`. The graph deletes it when it is done."""
    deps = need_deps(ctx)
    state = deps.state
    if state.storage is None or state.uploads is None:
        raise ActionRefused("unavailable", "Pictures cannot be used here.")
    try:
        image = await asyncio.to_thread(process_image, data)
    except UploadError as e:
        raise ActionRefused("unreadable_picture", e.message) from None
    record = new_upload(ctx.actor.tenant_id, product_id, ctx.actor.user_id, len(image.png))
    await state.storage.put_for(record.owner, record.key, image.png, "image/png")
    await state.uploads.add(record)
    if state.usage is not None:
        await record_safely(
            state.usage,
            UsageEvent(
                tenant_id=record.tenant_id, product_id=product_id, user_id=record.user_id,
                kind=UPLOAD_CREATED, quantity=record.bytes, unit="bytes",
                meta={"kind": "image", "from": "library"},
            ),
        )  # fmt: skip
    return record.key


def save_copy(folder: Path, stem: str, ext: str, data: bytes) -> Path:
    """Write `data` as `stem.ext` in `folder`, as `stem-2.ext` and so on when that name is taken:
    a copy never replaces a file."""
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"{stem}.{ext}", 1
    while True:
        try:
            with path.open("xb") as f:
                f.write(data)
            return path
        except FileExistsError:
            n += 1
            path = folder / f"{stem}-{n}.{ext}"
