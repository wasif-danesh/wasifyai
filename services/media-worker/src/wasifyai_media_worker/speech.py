"""Text to speech on an OpenAI-compatible speech server (ADR-0042).

The runner splits long text at sentence ends, asks the server for each piece, and joins the pieces
into one WAV, so a request is one result whatever the length. Which server answers is decided by the
voice's engine (`kokoro`, later `indic-parler`): the settings map an engine to an address."""

import io
import logging
import re
import wave
from typing import Any

import httpx
from wasifyai_platform_sdk import JobRequest

from wasifyai_media_worker.backends import raise_for_backend
from wasifyai_media_worker.comfy import ComfyError, ProgressFn

log = logging.getLogger(__name__)

PAUSE_S = 0.3  # silence between pieces
# a sentence ends at these, in any script: Latin, Devanagari danda, Chinese and Japanese full stops
_END = re.compile(r"(?<=[.!?…।॥。！？])\s*")
_SOFT = re.compile(r"(?<=[,;:，、；：])\s*")


def split_text(text: str, max_chars: int = 400) -> list[str]:
    """Pieces of at most `max_chars`, cut at sentence ends where possible, then at commas, then at
    the limit. Nothing is dropped, so the speech says all of the text."""
    pieces: list[str] = []
    for sentence in (s for s in _END.split(text.strip()) if s.strip()):
        pieces.extend(_fit(sentence, max_chars))
    packed: list[str] = []
    for piece in pieces:  # put short sentences together up to the limit
        if packed and len(packed[-1]) + 1 + len(piece) <= max_chars:
            packed[-1] = f"{packed[-1]} {piece}"
        else:
            packed.append(piece)
    return packed


def _fit(sentence: str, limit: int) -> list[str]:
    if len(sentence) <= limit:
        return [sentence]
    parts = [p for p in _SOFT.split(sentence) if p.strip()]
    if len(parts) > 1:
        out: list[str] = []
        for part in parts:
            if out and len(out[-1]) + 1 + len(part) <= limit:
                out[-1] = f"{out[-1]} {part}"
            else:
                out.extend(_fit(part, limit) if len(part) > limit else [part])
        return out
    words = sentence.split(" ")
    if len(words) > 1:  # no commas: cut at spaces
        out, cur = [], ""
        for word in words:
            if cur and len(cur) + 1 + len(word) > limit:
                out.append(cur)
                cur = word
            else:
                cur = f"{cur} {word}".strip()
        return [*out, cur] if cur else out
    return [sentence[i : i + limit] for i in range(0, len(sentence), limit)]  # no spaces at all


def join_wavs(pieces: list[bytes], pause_s: float = PAUSE_S) -> bytes:
    """One WAV from several with the same format, with a short silence between them."""
    out = io.BytesIO()
    params = None
    with wave.open(out, "wb") as dst:
        for n, piece in enumerate(pieces):
            with wave.open(io.BytesIO(piece)) as src:
                if params is None:
                    params = src.getparams()
                    dst.setparams(params)
                elif (src.getnchannels(), src.getsampwidth(), src.getframerate()) != (
                    params.nchannels,
                    params.sampwidth,
                    params.framerate,
                ):
                    raise ComfyError("job_failed", "The speech service changed audio format.")
                if n:
                    gap = int(params.framerate * pause_s)
                    dst.writeframes(b"\x00" * gap * params.nchannels * params.sampwidth)
                dst.writeframes(src.readframes(src.getnframes()))
    return out.getvalue()


class OpenAISpeechRunner:
    """Any server with an OpenAI-style POST /v1/audio/speech."""

    backend = "openai-speech"
    local_gpu = False  # the speech servers run on the CPU in this version

    def __init__(
        self,
        servers: dict[str, str],
        timeout_s: float,
        http: httpx.AsyncClient,
        api_key: str | None = None,
    ):
        self._servers = {k: v.rstrip("/") for k, v in servers.items()}
        self._timeout = timeout_s
        self._http = http
        self._headers = {"authorization": f"Bearer {api_key}"} if api_key else {}

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: Any = None
    ) -> dict[str, tuple[bytes, str, str]]:
        text = job.inputs.get("text")
        engine, voice, model = (job.inputs.get(k) for k in ("engine", "voice", "model"))
        if not isinstance(text, str) or not text.strip() or not voice or not model:
            raise ComfyError("invalid_workflow", "The request is missing the text or the voice.")
        base = self._servers.get(str(engine))
        if base is None:
            log.error("no speech server for engine %r", engine)
            raise ComfyError("backend_misconfigured", "The speech service is not set up.")
        pieces_text = split_text(text, int(job.inputs.get("max_chars") or 400))
        wavs: list[bytes] = []
        await on_progress(0.02)
        for n, piece in enumerate(pieces_text):
            body: dict[str, Any] = {
                "model": model, "voice": voice, "input": piece, "response_format": "wav",
            }  # fmt: skip
            if speed := job.inputs.get("speed"):
                body["speed"] = speed
            r = await self._http.post(
                f"{base}/v1/audio/speech", json=body, headers=self._headers, timeout=self._timeout
            )
            raise_for_backend(r)
            wavs.append(r.content)
            await on_progress((n + 1) / len(pieces_text))
        try:
            wav = join_wavs(wavs)
        except (wave.Error, EOFError) as exc:
            log.error("the speech server did not return a WAV: %s", exc)
            raise ComfyError("job_failed", "The speech service returned unusable audio.") from exc
        with wave.open(io.BytesIO(wav)) as made:
            if made.getnframes() == 0:  # a server can answer 200 with a header and no sound
                log.error("the speech server returned silence for voice %r", voice)
                raise ComfyError("job_failed", "The speech service made no sound for that text.")
        return {"audio": (wav, "audio/wav", "wav")}
