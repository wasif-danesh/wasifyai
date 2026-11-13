"""Voice on the cloud models (ADR-0100, stage CP7): what each speaking, cloning, designing,
listening and voice-changing model is sent on each provider, and the descriptors the voice screens
read while a task runs there.

Four cloud products carry the voice tasks, each with its own model in use (Settings › Your keys):
`voice` speaks with a model's named voices; `voiceclone` speaks in a voice copied from a recording
or described in words; `transcribe` writes down speech; `voicechange` makes a recording sound like
another voice. The field names are the providers' own (`docs/spikes/fal-v1-fa0-inputs.md`,
`docs/spikes/cloud-v1-cp0.md` and Runware's model pages, read 2026-11-12); the ones not shown there
are marked and checked in the real run (CP13)."""

import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Any

from wasifyai_platform_sdk import TranscriptSegment, VoiceEngineError
from wasifyai_platform_sdk.fal import FalError
from wasifyai_platform_sdk.languages import LANGUAGES
from wasifyai_platform_sdk.voice_models import OptionSpec, VoiceInfo, VoiceModel

KEYED_VOICE = "key:voice"
KEYED_CLONE = "key:voiceclone"
KEYED_TRANSCRIBE = "key:transcribe"
KEYED_CHANGE = "key:voicechange"
# the cloud product of each voice model id, and back
VOICE_PRODUCTS = {
    KEYED_VOICE: "voice",
    KEYED_CLONE: "voiceclone",
    KEYED_TRANSCRIBE: "transcribe",
    KEYED_CHANGE: "voicechange",
}

MULTI = ("multi",)
QWEN_LANGUAGES = ("zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it")
# What a cloud model speaks or writes, where it is not every language the app names
# (docs/spikes/voice-languages-l0.md). Chatterbox: Resemble AI's published 23; it read Bengali as
# English even when told the language. MiniMax: the `language_boost` values fal.ai accepts, as far
# as its refusal of Bengali listed them. Whisper: every language but Bengali, which it wrote badly
# even when told the language (and ADR-0043 measured it calling Bengali Hindi).
CHATTERBOX_LANGUAGES = (
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja", "ko", "ms", "nl",
    "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh",
)  # fmt: skip
MINIMAX_LANGUAGES = (
    "zh", "en", "ar", "ru", "es", "fr", "pt", "de", "tr", "nl", "uk", "vi", "id", "ja", "it",
    "ko", "th", "pl", "ro", "el", "cs", "fi", "hi", "bg", "da",
)  # fmt: skip
WHISPER_LANGUAGES = tuple(c for c in LANGUAGES if c != "bn")
SPEED = OptionSpec("speed", "float", "Speed", "How fast it speaks.", 1.0, 0.5, 2.0)

FAL_KOKORO = (  # Kokoro's American voices on fal.ai
    "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore", "af_nicole",
    "af_nova", "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir",
    "am_liam", "am_michael", "am_onyx", "am_puck", "am_santa",
)  # fmt: skip
# ElevenLabs' premade voices, by name as fal.ai takes them (WaveSpeed's `voice_id`: checked in CP13)
# the names both WaveSpeed and fal.ai know (fal.ai's default, Rachel, is not on WaveSpeed: CP13)
ELEVEN = (
    ("Aria", "female"), ("Sarah", "female"), ("Laura", "female"),
    ("Charlotte", "female"), ("Alice", "female"), ("Matilda", "female"), ("Jessica", "female"),
    ("Lily", "female"), ("Roger", "male"), ("Charlie", "male"), ("George", "male"),
    ("Callum", "male"), ("Liam", "male"), ("Will", "male"), ("Eric", "male"), ("Chris", "male"),
    ("Brian", "male"), ("Daniel", "male"), ("Bill", "male"),
)  # fmt: skip
GEMINI = (
    "Kore", "Zephyr", "Puck", "Charon", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe",
    "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Algenib",
    "Rasalgethi", "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima",
    "Achird", "Zubenelgenubi", "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
)  # fmt: skip
MINIMAX_VOICES = (  # MiniMax's own voices, which every provider of MiniMax Speech takes
    ("English_expressive_narrator", "male"), ("Wise_Woman", "female"),
    ("Friendly_Person", "male"), ("Inspirational_girl", "female"), ("Deep_Voice_Man", "male"),
    ("Calm_Woman", "female"), ("Casual_Guy", "male"), ("Lively_Girl", "female"),
    ("Patient_Man", "male"), ("Young_Knight", "male"), ("Determined_Man", "male"),
    ("Lovely_Girl", "female"), ("Decent_Boy", "male"), ("Imposing_Manner", "male"),
    ("Elegant_Man", "male"), ("Abbess", "female"), ("Sweet_Girl_2", "female"),
    ("Exuberant_Girl", "female"),
)  # fmt: skip


def _named(names: tuple[str, ...] | tuple[tuple[str, str], ...], language: str = "multi"):
    out = []
    for n in names:
        name, gender = (n, "") if isinstance(n, str) else n
        label = name.replace("_", " ").strip()
        out.append(VoiceInfo(name, label, language, gender))
    return tuple(out)


def _kokoro() -> tuple[VoiceInfo, ...]:
    return tuple(
        VoiceInfo(v, v[3:].capitalize(), "en-us", "female" if v[1] == "f" else "male")
        for v in FAL_KOKORO
    )


@dataclass(frozen=True)
class Speaker:
    """A speaking model on the cloud: its voices, its languages and whether it takes a speed."""

    title: str
    voices: tuple[VoiceInfo, ...]
    default_voice: str | None
    languages: tuple[str, ...] = MULTI
    speed: bool = False


SPEAKERS: dict[str, Speaker] = {  # by the catalogue's id
    "kokoro": Speaker("Kokoro", _kokoro(), "af_heart", ("en-us",), speed=True),
    "elevenlabs-v4": Speaker("ElevenLabs v4", _named(ELEVEN), "Aria"),
    "gemini-3.8-flash-tts": Speaker("Gemini 3.8 Flash TTS", _named(GEMINI), "Kore"),
    "chatterbox": Speaker("Chatterbox", (), None, CHATTERBOX_LANGUAGES),
    "minimax-speech-2.8-hd": Speaker(
        "MiniMax Speech 2.8 HD",
        _named(MINIMAX_VOICES),
        "English_expressive_narrator",
        MINIMAX_LANGUAGES,
        speed=True,
    ),
}


def speak_request(
    model_id: str, provider: str, endpoint: str, text: str, voice: str | None,
    speed: float | None,
) -> dict[str, Any]:  # fmt: skip
    """The body (or the Runware task) that speaks `text` in a named voice."""
    if provider == "runware":  # MiniMax Speech: an `audioInference` task
        speech: dict[str, Any] = {"text": text, "voice": voice or "English_expressive_narrator"}
        if speed is not None:
            speech["speed"] = speed
        return {"taskType": "audioInference", "speech": speech, "outputFormat": "WAV",
                "includeCost": True}  # fmt: skip
    if model_id == "kokoro":
        body: dict[str, Any] = {"prompt": text, "voice": voice or "af_heart"}
        if speed is not None:
            body["speed"] = speed
        return body
    if model_id == "elevenlabs-v4":
        if provider == "wavespeed":
            return {"text": text, "voice_id": voice or "Aria"}
        return {"text": text, "voice": voice or "Aria"}
    if model_id == "gemini-3.8-flash-tts":
        field = "text" if provider == "wavespeed" else "prompt"  # WaveSpeed's: checked in CP13
        return {field: text, "voice": voice or "Kore"}
    if model_id == "chatterbox":
        return {"text": text}
    if model_id == "minimax-speech-2.8-hd":
        if provider == "wavespeed":
            out: dict[str, Any] = {"text": text, "voice_id": voice or "English_expressive_narrator"}
            if speed is not None:
                out["speed"] = speed
            return out
        setting: dict[str, Any] = {"voice_id": voice or "English_expressive_narrator"}
        if speed is not None:
            setting["speed"] = speed
        return {"prompt": text, "voice_setting": setting, "output_format": "url"}
    raise FalError("invalid_input", f"This app does not speak with {model_id}.", True)


# ---- copy a voice, or make one from words ------------------------------------------------------

# MiniMax keeps a copied or designed voice at the provider it was made on: later speech in it costs
# per character there (`minimax-speech-2.8-hd`), so it is remembered by what made it (`voice_key`)


def voice_key(kind: str, made_from: bytes) -> str:
    """What a kept voice is remembered by: a copy by its recording, a design by its words."""
    return f"{kind}:{hashlib.sha256(made_from).hexdigest()}"


def new_voice_id() -> str:
    """A voice id MiniMax takes: a letter first, eight or more letters and digits."""
    return f"wasify{secrets.token_hex(8)}"


def clone_request(
    model_id: str, provider: str, endpoint: str, text: str, reference: str,
    reference_text: str | None, voice_id: str = "",
) -> dict[str, Any]:  # fmt: skip
    """The body that speaks `text` in the voice of the recording at `reference` (an address or
    Runware's upload id). MiniMax makes the voice under `voice_id` and says `text` with it."""
    if model_id == "qwen3-tts" and provider == "runware":
        settings: dict[str, Any] = {"xVectorOnly": not reference_text}
        if reference_text:
            settings["transcript"] = reference_text
        return {
            "taskType": "audioInference", "inputs": {"audio": reference},
            "speech": {"text": text, "voice": "clone", "language": "Auto"},
            "settings": settings, "outputFormat": "WAV", "includeCost": True,
        }  # fmt: skip
    if model_id == "chatterbox-clone":  # WaveSpeed's Chatterbox takes a voice to speak in
        return {"text": text, "reference_audio": reference}
    if model_id == "minimax-voice":
        if provider == "wavespeed":
            return {"audio": reference, "custom_voice_id": voice_id, "model": "speech-2.8-hd",
                    "text": text}  # fmt: skip
        return {"audio_url": reference, "text": text}
    raise FalError("invalid_input", f"{model_id} does not copy a voice on {provider}.", True)


def design_request(
    model_id: str, provider: str, text: str, description: str, voice_id: str = ""
) -> dict[str, Any]:
    """The body that speaks `text` in a voice described as `description`."""
    if model_id == "qwen3-tts" and provider == "runware":
        return {
            "taskType": "audioInference", "positivePrompt": description,
            "speech": {"text": text, "voice": "design", "language": "Auto"},
            "outputFormat": "WAV", "includeCost": True,
        }  # fmt: skip
    if model_id == "qwen3-tts":
        return {"prompt": description, "text": text}
    if model_id == "minimax-voice":
        body: dict[str, Any] = {"prompt": description, "preview_text": text}
        if provider == "wavespeed":
            body["custom_voice_id"] = voice_id
        return body
    raise FalError("invalid_input", f"{model_id} does not design a voice on {provider}.", True)


def made_voice(result: dict[str, Any], asked: str) -> str:
    """The id of the voice MiniMax made: the one it names, else the one asked for."""
    said = result.get("custom_voice_id") or result.get("voice_id")
    return str(said or asked)


# ---- write down speech -------------------------------------------------------------------------


def transcribe_request(model_id: str, provider: str, audio: str, language: str | None):
    if model_id == "scribe-v2":
        if provider == "wavespeed":  # field names checked in CP13
            body: dict[str, Any] = {"audio": audio, "diarize": False}
        else:
            body = {"audio_url": audio, "diarize": False, "tag_audio_events": False}
        if language:
            body["language_code"] = language
        return body
    if model_id == "whisper":
        out: dict[str, Any] = {"audio": audio, "task": "transcribe", "enable_timestamps": True}
        if language:
            out["language"] = language
        return out
    raise FalError("invalid_input", f"This app does not write down speech with {model_id}.", True)


_END = re.compile(r"[.!?…。！？]$")


def transcript_of(result: dict[str, Any]) -> tuple[str, tuple[TranscriptSegment, ...], float]:
    """(text, timed parts, seconds) from a provider's answer: Scribe's `words`, Whisper's
    `segments` or `chunks`, or the plain text as one part."""
    out = result
    outputs = result.get("outputs")
    if isinstance(outputs, list) and outputs and isinstance(outputs[0], dict):
        out = outputs[0]  # WaveSpeed: the answer is the first output
    elif isinstance(outputs, list) and outputs and isinstance(outputs[0], str):
        out = {"text": outputs[0]}
    text = str(out.get("text") or "").strip()
    segments: list[TranscriptSegment] = []
    words = [
        w
        for w in out.get("words") or []
        if isinstance(w, dict) and w.get("type", "word") in ("word", "spacing")
    ]
    if words:  # Scribe: whole sentences from its timed words
        start, said = None, ""
        for w in words:
            piece = str(w.get("text", ""))
            if start is None and piece.strip():
                start = float(w.get("start") or 0.0)
            said += piece
            if start is not None and _END.search(said.strip()):
                segments.append(
                    TranscriptSegment(start, float(w.get("end") or start), said.strip())
                )
                start, said = None, ""
        if start is not None and said.strip():
            end = float(words[-1].get("end") or start)
            segments.append(TranscriptSegment(start, end, said.strip()))
    else:
        for s in out.get("segments") or out.get("chunks") or []:
            if not isinstance(s, dict) or not str(s.get("text", "")).strip():
                continue
            ts = s.get("timestamp")
            pair = ts if isinstance(ts, list | tuple) and len(ts) == 2 else None
            begin, finish = pair if pair else (s.get("start"), s.get("end"))
            first = float(begin or 0.0)
            segments.append(
                TranscriptSegment(first, float(finish or first), str(s["text"]).strip())
            )
    if not text:
        text = " ".join(s.text for s in segments)
    if not text:
        raise VoiceEngineError("engine_failed", "The speech was not written down.")
    seconds = segments[-1].end if segments else 0.0
    if not segments:
        segments = [TranscriptSegment(0.0, seconds, text)]
    return text, tuple(segments), seconds


# ---- change a voice ----------------------------------------------------------------------------


def convert_request(provider: str, source: str, reference: str) -> dict[str, Any]:
    """Chatterbox: the recording, and the voice it should sound like."""
    if provider == "wavespeed":  # field names checked in CP13
        return {"audio": source, "reference_audio": reference}
    return {"source_audio_url": source, "target_voice_audio_url": reference}


# ---- the descriptors the screens read ----------------------------------------------------------


def _model(id_: str, title: str, family: str, tasks: tuple[str, ...], **more: Any) -> VoiceModel:
    return VoiceModel(
        id=id_, title=title, engine="remote", family=family, package="", server_task=tasks[0],
        tasks=tasks, recommended=tasks, sample_rate=more.pop("sample_rate", 24000),
        languages=more.pop("languages", MULTI), **more,
    )  # fmt: skip


def speaker_model(model_id: str, title: str, family: str) -> VoiceModel:
    s = SPEAKERS.get(model_id)
    if s is None:
        raise VoiceEngineError("not_with_key", f"{model_id} is not a speaking model this app uses.")
    return _model(
        KEYED_VOICE,
        title,
        family,
        ("speak",),
        languages=s.languages,
        voices=s.voices,
        default_voice=s.default_voice,
        options=(SPEED,) if s.speed else (),
    )


CLONE_RULES = {"reference_text": "optional", "min_seconds": 3, "max_seconds": 30}
DESIGN_RULES = {"via": "cloud", "max_chars": 300}


def clone_model(tasks: tuple[str, ...], title: str, family: str, model_id: str) -> VoiceModel:
    languages = {
        "qwen3-tts": QWEN_LANGUAGES, "chatterbox-clone": CHATTERBOX_LANGUAGES,
        "minimax-voice": MINIMAX_LANGUAGES,
    }.get(model_id, MULTI)  # fmt: skip
    return _model(
        KEYED_CLONE, title, family, tasks, languages=languages,
        clone=dict(CLONE_RULES) if "clone" in tasks else {},
        design=dict(DESIGN_RULES) if "design" in tasks else {},
    )  # fmt: skip


def transcribe_model(title: str, family: str, model_id: str = "") -> VoiceModel:
    languages = WHISPER_LANGUAGES if model_id == "whisper" else MULTI
    return _model(
        KEYED_TRANSCRIBE, title, family, ("transcribe",), sample_rate=16000, languages=languages
    )


CONVERT_RULES = {
    "target": "reference", "input_rate": 44100, "reference_seconds": [3, 30],
    "max_source_s": 300, "request": {"source": "audio", "reference": "voice_ref"},
}  # fmt: skip


def change_model(title: str, family: str) -> VoiceModel:
    return _model(
        KEYED_CHANGE,
        title,
        family,
        ("convert",),
        sample_rate=44100,
        convert=dict(CONVERT_RULES),
    )
