"""Test doubles for the voice product: a speech engine without a runtime, the shipped catalogue."""

import io
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from wasifyai_platform_sdk import (
    MusicResult,
    SpeechResult,
    TranscriptResult,
    TranscriptSegment,
    VoiceEngineError,
    VoiceModel,
    parse_voice_model,
)

PRODUCT = Path(__file__).parents[1]


def _is_file(path: Path | str) -> bool:
    return Path(path).is_file()


def catalogue() -> dict[str, VoiceModel]:
    raw = yaml.safe_load((PRODUCT / "models.yaml").read_text())
    return {
        m["id"]: parse_voice_model(m["id"], m["title"], m["licence"], m["voice"])
        for m in raw["models"]
        if m.get("voice")
    }


def wav(seconds: float = 1.0, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(rate * seconds))
    return buf.getvalue()


class FakeEngine:
    """The `SpeechEngine` protocol over the shipped descriptors; what it was asked is recorded."""

    def __init__(self, ready: set[str] | None = None):
        self.models_by_id = catalogue()
        self.ready = ready if ready is not None else set(self.models_by_id)
        self.spoken: list[tuple[str, str, str | None, dict[str, Any]]] = []
        self.transcribed: list[tuple[str, int, dict[str, Any]]] = []
        self.designed: list[tuple[str, str, str, dict[str, Any]]] = []
        self.made: list[tuple[str, Any]] = []
        self.cloned: list[tuple[str, str, str, str | None, dict[str, Any]]] = []
        self.fail_with: VoiceEngineError | None = None

    def models(self, task: str | None = None) -> list[dict[str, Any]]:
        return [m.public() for m in self.models_by_id.values() if not task or task in m.tasks]

    def resolve(self, task: str, model_id: str | None) -> VoiceModel:
        if model_id:
            m = self.models_by_id.get(model_id)
            if m is None or task not in m.tasks:
                raise VoiceEngineError("unknown_model", "That model is not one this app knows.")
        else:
            m = next(x for x in self.models_by_id.values() if task in x.recommended)
        if m.id not in self.ready:
            raise VoiceEngineError("model_missing", f"{m.title} is not on this computer yet.")
        return m

    async def speak(self, model, text, voice, options) -> SpeechResult:
        if self.fail_with:
            raise self.fail_with
        self.spoken.append((model.id, text, voice, dict(options)))
        seconds = max(0.5, len(text) / 20)
        return SpeechResult(wav(seconds), model.sample_rate, seconds, model.id, voice, 0.4, 0.9)

    async def design(self, model, text, description, options) -> SpeechResult:
        if self.fail_with:
            raise self.fail_with
        self.designed.append((model.id, text, description, dict(options)))
        return SpeechResult(wav(1.0), model.sample_rate, 1.0, model.id, None, 0.3, 0.7)

    async def clone(self, model, text, reference, reference_text, options) -> SpeechResult:
        if self.fail_with:
            raise self.fail_with
        assert _is_file(reference), "the runtime reads the recording from a file"
        self.cloned.append((model.id, text, Path(reference).name, reference_text, dict(options)))
        return SpeechResult(wav(1.0), model.sample_rate, 1.0, model.id, None, 0.3, 0.7)

    async def music(self, model, request) -> MusicResult:
        if self.fail_with:
            raise self.fail_with
        self.made.append((model.id, request))
        return MusicResult(wav(2.0), model.sample_rate, 2.0, model.id, request.seed or 99, 1.0, 3.0)

    async def transcribe(self, model, data, options) -> TranscriptResult:
        if self.fail_with:
            raise self.fail_with
        self.transcribed.append((model.id, len(data), dict(options)))
        return TranscriptResult(
            "Hello there. Second sentence.",
            (
                TranscriptSegment(0.0, 1.0, "Hello there."),
                TranscriptSegment(1.5, 3.0, "Second sentence."),
            ),
            3.0, model.id, 0.2,
        )  # fmt: skip


def app_state(tmp_path: Path, engine: FakeEngine | None = None) -> SimpleNamespace:
    return SimpleNamespace(audio=engine or FakeEngine(), desktop_dir=tmp_path, storage=None)
