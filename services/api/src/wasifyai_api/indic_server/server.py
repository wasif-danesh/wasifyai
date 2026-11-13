"""The Indian-language speech server (docs/voice-languages-plan.md, L5 and L6), run by the engine
as a sidecar on loopback (`indic_runtime.IndicSidecar`):

    POST /v1/speech      {"folder", "text", "speaker", "seed"?}  -> audio/wav
    POST /v1/transcribe  form: folder, language, file           -> {"text", "segments", "seconds"}

`folder` is where the engine laid out the model's files. The models load on the first request."""

import asyncio
import logging
from typing import Annotated

from engine import Speaker, Writer, pick_device
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

log = logging.getLogger("indic")
MAX_BYTES = 200 * 1024 * 1024
# the languages IndicConformer writes (its own codes); the app offers bn, hi, mr, te, ta, gu
CONFORMER_LANGUAGES = {
    "as", "bn", "brx", "doi", "gu", "hi", "kn", "kok", "ks", "mai", "ml", "mni", "mr", "ne", "or",
    "pa", "sa", "sat", "sd", "ta", "te", "ur",
}  # fmt: skip

app = FastAPI(title="wasifyai Indian-language speech")
device = pick_device()
speaker = Speaker(device)
writer = Writer()


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "device": device, "loaded": {"speak": speaker.loaded,
                                                     "transcribe": writer.loaded}}  # fmt: skip


class SpeechBody(BaseModel):
    folder: str
    text: str = Field(min_length=1, max_length=20000)
    speaker: str = Field(min_length=1, max_length=40)
    seed: int | None = None


@app.post("/v1/speech")
async def speech(body: SpeechBody) -> Response:
    try:
        wav = await asyncio.to_thread(
            speaker.speak, body.folder, body.text, body.speaker, body.seed
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    except Exception:
        log.exception("speech failed")
        raise HTTPException(500, "the speech could not be made") from None
    return Response(wav, media_type="audio/wav")


@app.post("/v1/transcribe")
async def transcribe(
    folder: Annotated[str, Form()],
    language: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> dict:
    if language not in CONFORMER_LANGUAGES:
        raise HTTPException(422, "this model does not write that language")
    audio = await file.read()
    if not audio or len(audio) > MAX_BYTES:
        raise HTTPException(422, "a recording is needed")
    try:
        return await asyncio.to_thread(writer.write, folder, audio, language)
    except Exception:
        log.exception("transcription failed")
        raise HTTPException(500, "the recording could not be written down") from None
