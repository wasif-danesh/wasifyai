"""The speech runtime of the web profile: models served by hosted providers, asked through the
gateway by alias (rule 5), instead of programs on the person's own computer.

It is the engine seam the voice product already uses (`SpeechEngine`, reached as `app.state.audio`),
with the models a deployment *allows* (ADR-0066 decision 11): descriptors in `hosted-models.yaml`
(`engine: remote`), each naming a gateway alias in `package`. The gateway (LiteLLM) maps the alias
to whatever provider the admin chose (OpenRouter or another); what the engine speaks is the common
OpenAI-style audio API:

    speak       POST /v1/audio/speech         text and a voice in, a WAV out
    transcribe  POST /v1/audio/transcriptions  a recording in, text and timed segments out

Cloning, designing a voice, music, splitting, converting, editing, dubbing and lip sync have no
common API across providers; a model of the web offers only what its descriptor lists, so the
screens never offer them here (they stay "Soon" until a hosted model for them is chosen).
"""

import io
import time
import wave
from pathlib import Path
from typing import Any

import httpx
import yaml
from wasifyai_platform_sdk import (
    SpeechResult,
    TranscriptResult,
    TranscriptSegment,
    VoiceEngineError,
    VoiceModel,
    parse_voice_model,
)

TIMEOUT_S = 180.0


def load_hosted_models(path: Path) -> list[VoiceModel]:
    """The descriptors of `hosted-models.yaml`: a list of `{id, title, voice: {...}}`."""
    raw = yaml.safe_load(path.read_text()) or {}
    out = []
    for m in raw.get("models") or []:
        model = parse_voice_model(m["id"], m["title"], m["voice"])
        if model.engine != "remote":
            raise ValueError(f"{model.id}: a hosted model has `engine: remote`")
        out.append(model)
    return out


def wav_info(wav: bytes) -> tuple[int, float]:
    """(sample rate, seconds) from a WAV's header."""
    try:
        with wave.open(io.BytesIO(wav)) as w:
            return w.getframerate(), w.getnframes() / w.getframerate()
    except (wave.Error, EOFError, ZeroDivisionError):
        raise VoiceEngineError(
            "engine_failed", "The speech service did not return audio that could be read."
        ) from None


class HostedSpeechEngine:
    """`SpeechEngine` for speak and transcribe through the gateway."""

    def __init__(
        self,
        models: list[VoiceModel],
        base_url: str,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
    ):
        self._models = {m.id: m for m in models}
        self._base = base_url.rstrip("/")
        self._headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT_S)

    # ---- the models -------------------------------------------------------------------------

    def models(self, task: str | None = None) -> list[dict[str, Any]]:
        return [
            {**m.public(), "state": "ready", "files_ready": True, "runtime_ready": True,
             "bytes_missing": 0, "hosted": True}
            for m in self._models.values()
            if not task or task in m.tasks
        ]  # fmt: skip

    def resolve(self, task: str, model_id: str | None) -> VoiceModel:
        if model_id:
            m = self._models.get(model_id)
            if m is None or task not in m.tasks:
                raise VoiceEngineError(
                    "unknown_model", "That model is not one this service offers for this."
                )
            return m
        wanted = [m for m in self._models.values() if task in m.recommended]
        for m in wanted or [m for m in self._models.values() if task in m.tasks]:
            return m
        raise VoiceEngineError(
            "no_model", "This service does not offer that yet. It is coming to the web."
        )

    # ---- calls ------------------------------------------------------------------------------

    async def _post(self, path: str, **kw: Any) -> httpx.Response:
        try:
            res = await self._client.post(self._base + path, headers=self._headers, **kw)
        except httpx.TransportError:
            raise VoiceEngineError(
                "busy", "The speech service could not be reached. Try again in a moment."
            ) from None
        if res.status_code == 429 or res.status_code >= 500:
            raise VoiceEngineError("busy", "The speech service is busy. Try again in a moment.")
        if res.status_code >= 400:
            raise VoiceEngineError(
                "engine_failed", f"The speech service refused this ({res.status_code})."
            )
        return res

    async def speak(
        self,
        model: VoiceModel,
        text: str,
        voice: str | None,
        options: dict[str, Any],
        *,
        beside: bool = False,
    ) -> SpeechResult:
        t0 = time.monotonic()  # `beside` is for a local model's memory: a hosted one holds none
        body: dict[str, Any] = {
            "model": model.package, "input": text, "response_format": "wav",
            **({"voice": voice} if voice else {}),
        }  # fmt: skip
        if "speed" in options:
            body["speed"] = float(options["speed"])
        res = await self._post("/v1/audio/speech", json=body)
        rate, seconds = wav_info(res.content)
        return SpeechResult(res.content, rate, seconds, model.id, voice, 0.0, time.monotonic() - t0)

    async def transcribe(
        self, model: VoiceModel, wav: bytes, options: dict[str, Any], *, beside: bool = False
    ) -> TranscriptResult:
        t0 = time.monotonic()  # `beside` is for a local model's memory: a hosted one holds none
        data = {"model": model.package, "response_format": "verbose_json"}
        if options.get("language"):
            data["language"] = str(options["language"])
        res = await self._post(
            "/v1/audio/transcriptions", files={"file": ("audio.wav", wav, "audio/wav")}, data=data
        )
        try:
            j = res.json()
        except ValueError:
            raise VoiceEngineError(
                "engine_failed", "The speech service's answer could not be read."
            ) from None
        segments = tuple(
            TranscriptSegment(float(s["start"]), float(s["end"]), str(s["text"]).strip())
            for s in j.get("segments") or []
            if str(s.get("text", "")).strip()
        )
        text = str(j.get("text", "")).strip()
        seconds = float(j.get("duration") or (segments[-1].end if segments else 0.0))
        if not segments and text:
            segments = (TranscriptSegment(0.0, seconds, text),)
        return TranscriptResult(text, segments, seconds, model.id, time.monotonic() - t0)

    def _not_offered(self, what: str) -> VoiceEngineError:
        return VoiceEngineError(
            "not_offered",
            f"{what} is not offered on the web yet. It is available in the desktop app.",
        )

    async def design(self, *a: Any, **k: Any) -> Any:
        raise self._not_offered("Making a voice from a description")

    async def clone(self, *a: Any, **k: Any) -> Any:
        raise self._not_offered("Copying a voice")

    async def music(self, *a: Any, **k: Any) -> Any:
        raise self._not_offered("Music")

    async def music_edit(self, *a: Any, **k: Any) -> Any:
        raise self._not_offered("Changing music")

    async def separate(self, *a: Any, **k: Any) -> Any:
        raise self._not_offered("Splitting a recording")

    async def convert(self, *a: Any, **k: Any) -> Any:
        raise self._not_offered("Changing a voice")

    async def speech_edit(self, *a: Any, **k: Any) -> Any:
        raise self._not_offered("Editing speech")

    async def lipsync(self, *a: Any, **k: Any) -> Any:
        raise self._not_offered("Lip sync")

    async def stop(self) -> bool:
        await self._client.aclose()
        return True
