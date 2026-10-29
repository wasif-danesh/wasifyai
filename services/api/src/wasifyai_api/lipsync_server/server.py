"""The lip sync server (ADR-0044): `POST /v1/lipsync` with a picture and a voice gives an MP4.

Run by `scripts/lipsync-server.sh` (natively on a Mac, where a container cannot reach the GPU;
in a CUDA container elsewhere). The models load on the first request and stay loaded."""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Annotated

from engine import Engine, NoFace
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

log = logging.getLogger("lipsync")
MAX_BYTES = 40 * 1024 * 1024

app = FastAPI(title="wasifyai lip sync (MuseTalk)")
engine = Engine()


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "device": engine.device, "loaded": engine._ready}


@app.post("/v1/lipsync")
async def lipsync(
    image: Annotated[UploadFile, File()],
    audio: Annotated[UploadFile, File()],
    fps: Annotated[int, Form()] = 25,
) -> Response:
    picture, voice = await image.read(), await audio.read()
    if not picture or not voice or len(picture) > MAX_BYTES or len(voice) > MAX_BYTES:
        raise HTTPException(422, "a picture and a voice are needed")
    if not 5 <= fps <= 60:
        raise HTTPException(422, "fps out of range")
    with tempfile.TemporaryDirectory(prefix="wasifyai-voice-") as tmp:
        path = Path(tmp) / "voice.wav"
        path.write_bytes(voice)
        try:
            mp4 = await asyncio.to_thread(engine.generate, picture, str(path), fps, 8)
        except NoFace:
            raise HTTPException(422, "no face found in the picture") from None
        except Exception:
            log.exception("lip sync failed")
            raise HTTPException(500, "the lip sync could not be made") from None
    return Response(mp4, media_type="video/mp4")
