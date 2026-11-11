"""A stand-in for the lip sync server (`wasifyai_api/lipsync_server/server.py`), to test the sidecar
without torch or EchoMimic. A picture of `noface` is refused with 422, `boom` fails with 500, `slow`
never answers; every answer records what it was sent in `last.json`."""

import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

app = FastAPI()
state = {"loaded": False}


def mp4(w: int, h: int) -> bytes:
    """A few bytes that read as an MP4 with a video track header of this size."""
    tkhd = bytes([0]) + b"\0\0\0" + b"\0" * 20 + b"\0" * 52
    tkhd += (w << 16).to_bytes(4, "big") + (h << 16).to_bytes(4, "big")
    return b"\x00\x00\x00\x18ftypmp42" + b"\x00\x00\x00\x5ctkhd" + tkhd + b"\0" * 8


@app.get("/health")
def health() -> dict:
    return {
        "ok": True, "device": "cpu", "loaded": state["loaded"],
        "dir": os.environ.get("ECHOMIMIC_DIR"), "weights": os.environ.get("LIPSYNC_WEIGHTS"),
    }  # fmt: skip


@app.post("/v1/lipsync")
async def lipsync(
    image: UploadFile = File(...),  # noqa: B008
    audio: UploadFile = File(...),  # noqa: B008
    fps: int = Form(25),
    width: int = Form(0),
    height: int = Form(0),
) -> Response:
    pic, voice = await image.read(), await audio.read()
    if pic == b"noface":
        raise HTTPException(422, "the picture could not be read")
    if pic == b"boom":
        raise HTTPException(500, "the lip sync could not be made")
    if pic == b"slow":
        await asyncio.sleep(60)
    note = {"fps": fps, "pic": len(pic), "voice": len(voice), "width": width, "height": height}
    await asyncio.to_thread(Path("last.json").write_text, json.dumps(note))
    state["loaded"] = True
    return Response(mp4(width or 640, height or 480), media_type="video/mp4")
