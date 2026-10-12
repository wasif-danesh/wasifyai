"""Speech to text on an OpenAI-compatible server (ADR-0043).

The recording is the cleaned 16 kHz mono WAV the API stored. When the user did not choose a
language, the first 30 seconds go to a larger model that only decides the language (Whisper turbo
mistakes Bengali for Hindi, see ADR-0043); the whole recording is then transcribed by the fast
model with that language given.

For the Indian languages the product lists (`indic_languages`) the work goes to the IndicConformer
server (`indic-stt`) instead. It takes short pieces: the recording is cut at its quietest moments
into pieces of up to about 15 seconds, each is transcribed, and every piece is one timed segment.

The result is a JSON file: the text, the language and timed segments."""

import io
import json
import logging
import wave
from typing import Any

import httpx
import numpy as np
from wasifyai_platform_sdk import JobRequest

from wasifyai_media_worker.backends import raise_for_backend
from wasifyai_media_worker.comfy import ComfyError, ProgressFn

log = logging.getLogger(__name__)

DETECT_SECONDS = 30
BASE_TIMEOUT_S = 300
# a recording is transcribed at least this much faster than real time on the slowest supported setup
SLOWEST_REAL_TIME_FACTOR = 2.0


def first_seconds(wav_bytes: bytes, seconds: float) -> bytes:
    """The first `seconds` of a WAV, as a WAV."""
    with wave.open(io.BytesIO(wav_bytes)) as src:
        frames = src.readframes(int(src.getframerate() * seconds))
        out = io.BytesIO()
        with wave.open(out, "wb") as dst:
            dst.setnchannels(src.getnchannels())
            dst.setsampwidth(src.getsampwidth())
            dst.setframerate(src.getframerate())
            dst.writeframes(frames)
        return out.getvalue()


PIECE_MIN_S = 4.0
PIECE_MAX_S = 15.0
FRAME = 320  # 20 ms at 16 kHz


def split_pieces(
    wav_bytes: bytes, min_s: float = PIECE_MIN_S, max_s: float = PIECE_MAX_S
) -> list[tuple[float, float, bytes]]:
    """Cut a 16 kHz mono WAV into pieces of `min_s` to `max_s` seconds at its quietest moments, so
    no word is cut in half where there is a pause to cut at. Returns (start, end, WAV bytes)."""
    with wave.open(io.BytesIO(wav_bytes)) as src:
        rate, width, channels = src.getframerate(), src.getsampwidth(), src.getnchannels()
        samples = np.frombuffer(src.readframes(src.getnframes()), dtype="<i2")
    total = len(samples)
    if total == 0:
        return []
    frames = total // FRAME
    energy = np.abs(samples[: frames * FRAME].astype("float32")).reshape(frames, FRAME).mean(axis=1)
    if frames >= 3:  # smooth over three frames so one click is not mistaken for silence
        energy = np.convolve(energy, np.ones(3) / 3, mode="same")
    lo, hi = int(min_s * rate / FRAME), int(max_s * rate / FRAME)
    cuts = [0]
    while total - cuts[-1] * FRAME > hi * FRAME:
        start = cuts[-1]
        window = energy[start + lo : start + hi]
        cuts.append(start + lo + int(np.argmin(window)) + 1)
    bounds = [c * FRAME for c in cuts] + [total]
    pieces = []
    for a, b in zip(bounds, bounds[1:], strict=False):
        out = io.BytesIO()
        with wave.open(out, "wb") as dst:
            dst.setnchannels(channels)
            dst.setsampwidth(width)
            dst.setframerate(rate)
            dst.writeframes(samples[a:b].tobytes())
        pieces.append((a / rate, b / rate, out.getvalue()))
    return pieces


class OpenAITranscriptionRunner:
    backend = "openai-transcription"
    local_gpu = False

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

    async def _post(self, base: str, audio: bytes, model: str, language: str | None, wait_s: float):
        data = {"model": model, "response_format": "verbose_json"}
        if language:
            data["language"] = language
        r = await self._http.post(
            f"{base}/v1/audio/transcriptions",
            data=data,
            files={"file": ("audio.wav", audio, "audio/wav")},
            headers=self._headers,
            timeout=wait_s,
        )
        raise_for_backend(r)
        try:
            return r.json()
        except ValueError:
            log.error("the transcription server did not answer with JSON")
            raise ComfyError("job_failed", "The speech service returned unusable text.") from None

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: Any = None
    ) -> dict[str, tuple[bytes, str, str]]:
        audio = (files or {}).get("audio")
        model = job.inputs.get("model")
        engine = str(job.inputs.get("engine") or "whisper")
        if not audio or not model:
            raise ComfyError("invalid_workflow", "The request is missing the recording.")
        base = self._servers.get(engine)
        if base is None:
            log.error("no transcription server for engine %r", engine)
            raise ComfyError("backend_misconfigured", "The speech service is not set up.")
        seconds = float(job.inputs.get("seconds") or 0)
        # time to transcribe grows with the recording: allow it, and never less than the base
        timeout = max(self._timeout, BASE_TIMEOUT_S + SLOWEST_REAL_TIME_FACTOR * seconds)
        await on_progress(0.02)
        language = str(job.inputs.get("language") or "") or None
        if language is None:
            detect_model = job.inputs.get("detect_model") or model
            sample = first_seconds(audio, DETECT_SECONDS)
            found = await self._post(base, sample, str(detect_model), None, timeout)
            language = str(found.get("language") or "") or None
        await on_progress(0.15)
        indic = self._servers.get("indic-stt")
        if language and indic and language in (job.inputs.get("indic_languages") or []):
            result = await self._indic(indic, audio, language, timeout, on_progress)
        else:
            body = await self._post(base, audio, str(model), language, timeout)
            result = {
                "text": str(body.get("text") or "").strip(),
                "language": str(body.get("language") or language or ""),
                "segments": [
                    {
                        "start": float(s.get("start", 0)),
                        "end": float(s.get("end", 0)),
                        "text": s["text"],
                    }
                    for s in body.get("segments") or []
                    if str(s.get("text", "")).strip()
                ],
            }
        await on_progress(1.0)
        return {
            "transcript": (
                json.dumps(result, ensure_ascii=False).encode("utf-8"),
                "application/json",
                "json",
            )
        }

    async def _indic(
        self, base: str, audio: bytes, language: str, wait_s: float, on_progress: ProgressFn
    ) -> dict[str, Any]:
        """IndicConformer takes short pieces: cut at the quietest moments, one request per piece."""
        pieces = split_pieces(audio)
        segments: list[dict[str, Any]] = []
        for n, (start, end, piece) in enumerate(pieces):
            r = await self._http.post(
                f"{base}/v1/audio/transcriptions",
                data={"model": "indic-conformer", "language": language, "response_format": "json"},
                files={"file": ("piece.wav", piece, "audio/wav")},
                headers=self._headers,
                timeout=wait_s,
            )
            raise_for_backend(r)
            try:
                said = str(r.json().get("text") or "").strip()
            except ValueError:
                log.error("the Indic transcription server did not answer with JSON")
                raise ComfyError(
                    "job_failed", "The speech service returned unusable text."
                ) from None
            if said:
                segments.append({"start": round(start, 2), "end": round(end, 2), "text": said})
            await on_progress(0.15 + 0.85 * (n + 1) / len(pieces))
        return {
            "text": " ".join(s["text"] for s in segments),
            "language": language,
            "segments": segments,
        }
