"""Documents attached to a chat message (ADR-0083, stage CO2).

A picture goes through the ordinary hardened upload (`uploads.py`, ADR-0035). A document is read
here, on the engine, into plain text: what the person attached is the words in it, never the file.
The stored copy is that text (a `.txt` under the user's prefix), so nothing a hostile file carries
(macros, scripts, embedded objects) ever reaches the model or the window.

Text, Markdown, CSV and HTML are read with the notebooks' built-in reader; PDF and Office files go
to the notebooks' document reader when it is installed (a separate process with a timeout), and are
refused in words when it is not. The file's name is kept only to show it back to the person."""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import (
    UPLOAD_CREATED,
    ScopedStorage,
    UploadError,
    UploadLimiter,
    UsageEvent,
    UsageRecorder,
    new_upload,
)
from wasifyai_platform_sdk.usage import record_safely

from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.metrics import UPLOADS
from wasifyai_api.services import services_of
from wasifyai_api.uploads import read_capped

log = logging.getLogger(__name__)
router = APIRouter(tags=["attachments"])

PRODUCT_ID = "wasifyai-assistant"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 200_000  # what is kept of a long document; the model is given less (the graph)
NAME_CHARS = 120


class AttachmentResult(BaseModel):
    id: str  # what a run names it by (`attachments: [{id, name}]`)
    kind: str  # "document"
    name: str
    chars: int
    pages: int | None = None
    truncated: bool = False  # more words than are kept


def clean_name(raw: str | None) -> str:
    """A file name to show back: its last part, no control characters, not long."""
    base = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(c for c in base if c.isprintable()).strip()
    return base[:NAME_CHARS] or "document"


async def read_document(state: Any, path: Path, filename: str) -> tuple[str, int | None]:
    """The words of a checked file, and its page count when the reader says. Raises
    `UploadError` with a sentence for the person."""
    from wasifyai_notebooks.hardening import Refused, check_file
    from wasifyai_notebooks.reading import BuiltinReader, ReadError, Unavailable, needs_reader

    try:
        checked = await asyncio.to_thread(check_file, path, filename)
    except Refused as e:
        raise UploadError(415, str(e)) from None
    if checked.mime.startswith("image/"):
        raise UploadError(415, "Pictures are attached with the picture button.")
    try:
        if needs_reader(checked.suffix):
            from wasifyai_notebooks.reading import RoutingReader
            from wasifyai_notebooks.runtime import NotAvailable, runtime_for

            try:
                reader = RoutingReader(runtime_for(state).components)
            except NotAvailable:
                raise UploadError(415, "This kind of file cannot be attached here.") from None
            try:
                result = await reader.read(path, checked.suffix)
            finally:
                await reader.close()
        else:
            result = await BuiltinReader().read(path, checked.suffix)
    except Unavailable:
        raise UploadError(
            422,
            "To attach this kind of file, set up the document reader first (in Notebooks, when "
            "you add a PDF or Office file).",
        ) from None
    except ReadError as e:
        raise UploadError(422, str(e)) from None
    except UploadError:
        raise
    except Exception:
        log.exception("an attached document could not be read")
        raise UploadError(422, "That file could not be read.") from None
    text = result.markdown.strip()
    if not text:
        raise UploadError(422, "There are no words in that file that could be read.")
    return text, result.pages


@router.post(
    f"/products/{PRODUCT_ID}/attachments", response_model=AttachmentResult, status_code=201
)
async def attach_document(
    request: Request, identity: Identity = Depends(get_identity)
) -> AttachmentResult:
    """A document for a chat message: the body is the file, `x-file-name` its name."""
    state: Any = services_of(request)
    limiter: UploadLimiter = state.upload_limiter
    if not await limiter.allow(identity.tenant_id, identity.user_id):
        raise HTTPException(429, "Too many uploads. Please wait a while and try again.")
    storage: ScopedStorage | None = state.storage
    if storage is None:
        raise HTTPException(503, "file storage is not available")
    # the window sends the name percent-encoded: a header carries only plain characters
    name = clean_name(unquote(request.headers.get("x-file-name", "")))
    try:
        data = await read_capped(request, MAX_FILE_BYTES)
        with tempfile.TemporaryDirectory(prefix="attach-") as tmp:
            path = Path(tmp) / "file"
            await asyncio.to_thread(path.write_bytes, data)
            # a file name's extension says which reader; the bytes must agree (the notebooks' check)
            suffix = Path(name).suffix or ".txt"
            text, pages = await read_document(state, path, f"file{suffix}")
    except UploadError as exc:
        UPLOADS.labels("document", "refused").inc()
        raise HTTPException(exc.status, exc.message) from None
    truncated = len(text) > MAX_TEXT_CHARS
    kept = text[:MAX_TEXT_CHARS].encode("utf-8")
    UPLOADS.labels("document", "accepted").inc()
    record = new_upload(identity.tenant_id, PRODUCT_ID, identity.user_id, len(kept), "text")
    await storage.put_for(record.owner, record.key, kept, "text/plain; charset=utf-8")
    await state.uploads.add(record)
    recorder: UsageRecorder = state.usage
    await record_safely(
        recorder,
        UsageEvent(
            tenant_id=record.tenant_id, product_id=PRODUCT_ID, user_id=record.user_id,
            kind=UPLOAD_CREATED, quantity=record.bytes, unit="bytes", meta={"kind": "document"},
        ),
    )  # fmt: skip
    return AttachmentResult(
        id=record.id,
        kind="document",
        name=name,
        chars=min(len(text), MAX_TEXT_CHARS),
        pages=pages,
        truncated=truncated,
    )
