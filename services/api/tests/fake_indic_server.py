"""A stand-in for the Indian-language speech server (`wasifyai_api/indic_server/server.py`), to test
the sidecar without torch. It speaks one second of silence per sentence and writes back what the
file holds; a speaker named `boom` fails with 500. It records what it was sent in `last.json`."""

import io
import json
import struct
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI()
state = {"speak": False, "transcribe": False}


def wav(seconds: float, rate: int = 44100) -> bytes:
    frames = int(seconds * rate)
    body = b"\0\0" * frames
    head = b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVEfmt "
    head += struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data"
    return head + struct.pack("<I", len(body)) + body


def record(**sent: object) -> None:
    (Path(__file__).parent / "last.json").write_text(json.dumps(sent, ensure_ascii=False))


@app.get("/health")
def health() -> dict:
    return {"ok": True, "device": "cpu", "loaded": state}


class Body(BaseModel):
    folder: str
    text: str
    speaker: str
    seed: int | None = None


@app.post("/v1/speech")
def speech(body: Body) -> Response:
    record(**body.model_dump())
    if body.speaker == "boom":
        raise HTTPException(500, "boom")
    state["speak"] = True
    return Response(wav(1.0), media_type="audio/wav")


@app.post("/v1/transcribe")
async def transcribe(
    folder: str = Form(...),
    language: str = Form(...),
    file: UploadFile = File(...),  # noqa: B008
) -> dict:
    data = await file.read()
    record(folder=folder, language=language, bytes=len(data))
    if language == "xx":
        raise HTTPException(422, "no")
    state["transcribe"] = True
    text = io.BytesIO(data).read().decode(errors="replace")[-12:]
    return {"text": text, "segments": [{"text": text, "start": 0, "end": 1.5}], "seconds": 1.5}
