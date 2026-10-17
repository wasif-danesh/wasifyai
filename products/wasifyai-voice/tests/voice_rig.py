"""Test doubles for the voice product: a speech engine without a runtime, the shipped catalogue."""

import io
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from wasifyai_platform_sdk import (
    LipSyncResult,
    MusicResult,
    SeparateResult,
    SpeechResult,
    Stem,
    TranscriptResult,
    TranscriptSegment,
    VoiceEngineError,
    VoiceModel,
    parse_voice_model,
)

PRODUCT = Path(__file__).parents[1]


def _is_file(path: Path | str) -> bool:
    return Path(path).is_file()


def _png_size(path: Path | str) -> int:
    """The size of a PNG file, and a check that it is one."""
    p = Path(path)
    assert p.read_bytes()[:4] == b"\x89PNG", "the picture is handed over as a PNG"
    return p.stat().st_size


def catalogue() -> dict[str, VoiceModel]:
    raw = yaml.safe_load((PRODUCT / "models.yaml").read_text())
    return {
        m["id"]: parse_voice_model(m["id"], m["title"], m["licence"], m["voice"])
        for m in raw["models"]
        if m.get("voice")
    }


def wav(seconds: float = 1.0, rate: int = 24000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x01" * channels * int(rate * seconds))
    return buf.getvalue()


def facts(path: Path | str) -> tuple[int, int]:
    """(rate, channels) of the WAV the runtime was handed."""
    with wave.open(str(path)) as w:
        return w.getframerate(), w.getnchannels()


class FakeEngine:
    """The `SpeechEngine` protocol over the shipped descriptors; what it was asked is recorded."""

    def __init__(self, ready: set[str] | None = None):
        self.models_by_id = catalogue()
        self.ready = ready if ready is not None else set(self.models_by_id)
        self.spoken: list[tuple[str, str, str | None, dict[str, Any]]] = []
        self.transcribed: list[tuple[str, int, dict[str, Any]]] = []
        self.designed: list[tuple[str, str, str, dict[str, Any]]] = []
        self.made: list[tuple[str, Any]] = []
        self.edited: list[tuple[str, Any, str]] = []
        self.cloned: list[tuple[str, str, str, str | None, dict[str, Any]]] = []
        self.separated: list[tuple[str, Any, tuple[int, int]]] = []
        self.converted: list[tuple[str, Any, tuple[int, int], tuple[int, int]]] = []
        self.speech_edited: list[tuple[str, Any, tuple[int, int]]] = []
        self.lipsynced: list[tuple[str, Any, tuple[int, int], int]] = []
        self.fail_with: VoiceEngineError | None = None

    def models(self, task: str | None = None) -> list[dict[str, Any]]:
        return [
            m.public() | {"state": "ready" if m.id in self.ready else "can_install"}
            for m in self.models_by_id.values()
            if not task or task in m.tasks
        ]

    def resolve(self, task: str, model_id: str | None) -> VoiceModel:
        if model_id:
            m = self.models_by_id.get(model_id)
            if m is None or task not in m.tasks:
                raise VoiceEngineError("unknown_model", "That model is not one this app knows.")
        else:
            m = next((x for x in self.models_by_id.values() if task in x.recommended), None)
            if m is None:
                raise VoiceEngineError("no_model", "There is no model for this yet.")
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

    async def music_edit(self, model, request, source) -> MusicResult:
        if self.fail_with:
            raise self.fail_with
        assert _is_file(source), "the runtime reads the clip from a file"
        self.edited.append((model.id, request, Path(source).name))
        return MusicResult(wav(2.0), model.sample_rate, 2.0, model.id, request.seed or 77, 1.0, 3.0)

    async def separate(self, model, request, source) -> SeparateResult:
        if self.fail_with:
            raise self.fail_with
        assert _is_file(source), "the runtime reads the recording from a file"
        self.separated.append((model.id, request, facts(source)))
        stems = tuple(Stem(n, wav(1.0, 44100, 2), 44100, 1.0) for n in model.separate["stems"])
        return SeparateResult(stems, model.id, 0.5, 1.5)

    async def convert(self, model, request, source, reference) -> SpeechResult:
        if self.fail_with:
            raise self.fail_with
        assert _is_file(source) and _is_file(reference)
        self.converted.append((model.id, request, facts(source), facts(reference)))
        return SpeechResult(wav(1.0, 16000), 16000, 1.0, model.id, None, 0.3, 0.8)

    async def speech_edit(self, model, request, source) -> SpeechResult:
        if self.fail_with:
            raise self.fail_with
        assert _is_file(source)
        self.speech_edited.append((model.id, request, facts(source)))
        return SpeechResult(wav(1.0, 48000), 48000, 1.0, model.id, None, 0.3, 0.9)

    async def lipsync(self, model, request, picture, voice) -> LipSyncResult:
        if self.fail_with:
            raise self.fail_with
        assert _is_file(picture) and _is_file(voice)
        self.lipsynced.append((model.id, request, facts(voice), _png_size(picture)))
        return LipSyncResult(b"\x00\x00\x00\x18ftypmp42" + b"0" * 32, request.voice_seconds,
                             request.fps, 640, 480, model.id, 0.5, 4.0)  # fmt: skip

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
