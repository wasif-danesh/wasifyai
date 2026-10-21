"""Save a file where the person chose, for the screens that already hold the file (desktop only).

The window's Save As box (the system's) gives a path; the window sends the bytes with it, and the
engine writes them there, because the window cannot write a file itself. Screens whose file lives in
the engine's own storage use the export route of their product with the same `path` instead."""

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from wasifyai_platform_sdk import SaveRefused
from wasifyai_platform_sdk.saving import chosen_path

from wasifyai_api.identity import Identity, get_identity

router = APIRouter(tags=["desktop"])

MAX_SAVE_BYTES = 2 * 1024**3


class Saved(BaseModel):
    name: str
    path: str


@router.post("/desktop/save", response_model=Saved)
async def save_file(
    request: Request,
    path: str = Form(...),
    file: UploadFile = File(...),  # noqa: B008
    _: Identity = Depends(get_identity),
) -> Saved:
    """Write the sent file at `path`, replacing a file there (the Save As box asked)."""
    protect = getattr(request.app.state, "desktop_dir", None)
    try:
        target = chosen_path(path, Path(protect) if protect else None)
    except SaveRefused as exc:
        raise HTTPException(422, str(exc)) from None
    part = target.with_name(f".{target.name}.part")
    size = 0
    try:
        with part.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_SAVE_BYTES:
                    raise HTTPException(413, "That file is too large to save.")
                await asyncio.to_thread(out.write, chunk)
        os.replace(part, target)
    except OSError:
        part.unlink(missing_ok=True)
        raise HTTPException(
            422, "The file could not be saved there. Choose another place."
        ) from None
    except HTTPException:
        part.unlink(missing_ok=True)
        raise
    return Saved(name=target.name, path=str(target))
