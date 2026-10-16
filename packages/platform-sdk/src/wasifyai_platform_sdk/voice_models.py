"""Speech, music and avatar models as data (ADR-0066).

A model is a *descriptor*: what it can do, what it needs, what it costs, and which licence its
weights carry. The window builds its model dropdown from descriptors, and the engine validates
every request against the descriptor before anything is sent to the runtime, because the runtime
answers a user's mistake with an HTTP 500 and may silently ignore an option it does not know
(V0, VoxCPM2).

    parse_voice_model(...)   a `voice:` block of a product's `models.yaml` -> VoiceModel
    check_speak(...)         a Speak request, validated against the model
    SpeechEngine             what a product may ask of the engine (reached through the app state)

Nothing here starts a process or reads a file; the engine does (services/api audio_runtime.py)."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

TASKS = (
    "speak",
    "clone",
    "design",
    "edit",
    "convert",
    "music",
    "separate",
    "transcribe",
    "lipsync",
)
COMMERCIAL = ("yes", "conditional", "no", "unreviewed")
OPTION_TYPES = ("bool", "int", "float", "enum", "string")
ENGINES = ("audiocpp", "comfyui", "sidecar", "llamacpp", "remote")

MAX_SPEAK_CHARS = 5000
_ID = re.compile(r"^[a-z0-9][a-z0-9_.\-]*$")


class VoiceRequestError(ValueError):
    """The request cannot be run as asked. `code` is stable; `message` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class VoiceEngineError(Exception):
    """The engine could not do what was asked (not installed, did not start, the runtime failed)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OptionSpec:
    name: str
    type: str
    label: str = ""
    description: str = ""
    default: Any = None
    min: float | None = None
    max: float | None = None
    values: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name, "type": self.type, "label": self.label or self.name,
            "description": self.description, "default": self.default,
            "min": self.min, "max": self.max, "values": list(self.values),
        }  # fmt: skip


@dataclass(frozen=True)
class VoiceInfo:
    id: str
    label: str
    language: str = ""
    gender: str = ""

    def public(self) -> dict[str, str]:
        return {
            "id": self.id,
            "label": self.label,
            "language": self.language,
            "gender": self.gender,
        }


@dataclass(frozen=True)
class Measured:
    """What was measured on one computer: the figures a descriptor may quote (ADR-0066, V0)."""

    platform: str = ""
    speed_x: float | None = None  # warm, times real time (speech and transcription)
    memory_gb: float | None = None  # resident while loaded
    load_s: float | None = None  # first request, which loads the model

    def public(self) -> dict[str, Any]:
        return {
            "platform": self.platform, "speed_x": self.speed_x,
            "memory_gb": self.memory_gb, "load_s": self.load_s,
        }  # fmt: skip


@dataclass(frozen=True)
class VoiceModel:
    id: str
    title: str
    licence: str  # SPDX-like name of the weights' licence, from the catalogue entry
    engine: str
    family: str
    package: str  # the audio.cpp spec package this is (one family holds several kinds of model)
    server_task: str
    tasks: tuple[str, ...]
    recommended: tuple[str, ...]
    languages: tuple[str, ...]
    sample_rate: int
    commercial_use: str
    licence_evidence: str
    reviewed: str
    measured: Measured = field(default_factory=Measured)
    voices: tuple[VoiceInfo, ...] = ()
    default_voice: str | None = None
    options: tuple[OptionSpec, ...] = ()
    # how clone and design are delivered (V2); declared now so the schema is proven
    clone: dict[str, Any] = field(default_factory=dict, hash=False)
    design: dict[str, Any] = field(default_factory=dict, hash=False)
    # music: the modes it offers and how a request is put to the runtime (V3)
    music: dict[str, Any] = field(default_factory=dict, hash=False)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "licence": self.licence, "engine": self.engine,
            "family": self.family, "package": self.package, "tasks": list(self.tasks),
            "recommended": list(self.recommended), "languages": list(self.languages),
            "sample_rate": self.sample_rate, "commercial_use": self.commercial_use,
            "licence_evidence": self.licence_evidence, "reviewed": self.reviewed,
            "measured": self.measured.public(),
            "voices": [v.public() for v in self.voices], "default_voice": self.default_voice,
            "options": [o.public() for o in self.options],
            "clone": self.clone, "design": self.design, "music": self.music,
        }  # fmt: skip

    def option(self, name: str) -> OptionSpec | None:
        return next((o for o in self.options if o.name == name), None)

    def voice(self, voice_id: str) -> VoiceInfo | None:
        return next((v for v in self.voices if v.id == voice_id), None)


def _tuple_of(raw: Any, allowed: tuple[str, ...], what: str, model: str) -> tuple[str, ...]:
    out = tuple(str(x) for x in (raw or ()))
    bad = [x for x in out if x not in allowed]
    if bad:
        raise ValueError(f"{model}: unknown {what} {bad[0]!r}")
    return out


def _option(raw: dict[str, Any], model: str) -> OptionSpec:
    kind = str(raw.get("type", ""))
    if kind not in OPTION_TYPES or not _ID.match(str(raw.get("name", "")).lower()):
        raise ValueError(f"{model}: bad option {raw.get('name')!r}")
    values = tuple(str(v) for v in raw.get("values") or ())
    if kind == "enum" and not values:
        raise ValueError(f"{model}: enum option {raw['name']!r} needs values")
    return OptionSpec(
        name=str(raw["name"]), type=kind, label=str(raw.get("label", "")),
        description=str(raw.get("description", "")), default=raw.get("default"),
        min=float(raw["min"]) if raw.get("min") is not None else None,
        max=float(raw["max"]) if raw.get("max") is not None else None, values=values,
    )  # fmt: skip


def parse_voice_model(entry_id: str, title: str, licence: str, raw: dict[str, Any]) -> VoiceModel:
    """A `voice:` block of `models.yaml`. Raises ValueError that names the model and the problem,
    so a bad catalogue stops at startup with every cause in the message."""
    if not _ID.match(entry_id):
        raise ValueError(f"{entry_id}: id must be lowercase letters, digits, dots, dashes")
    engine = str(raw.get("engine", ""))
    if engine not in ENGINES:
        raise ValueError(f"{entry_id}: unknown engine {engine!r}")
    tasks = _tuple_of(raw.get("tasks"), TASKS, "task", entry_id)
    if not tasks:
        raise ValueError(f"{entry_id}: needs at least one task")
    recommended = _tuple_of(raw.get("recommended"), TASKS, "recommended task", entry_id)
    if not set(recommended) <= set(tasks):
        raise ValueError(f"{entry_id}: recommended for a task it does not do")
    commercial = str(raw.get("commercial_use", "unreviewed"))
    if commercial not in COMMERCIAL:
        raise ValueError(f"{entry_id}: commercial_use must be one of {COMMERCIAL}")
    if recommended and commercial != "yes":
        # ADR-0066 decision 4: never the default or the recommendation unless commercially usable
        raise ValueError(f"{entry_id}: only a model with commercial_use: yes can be recommended")
    if not str(raw.get("licence_evidence", "")).startswith("https://"):
        raise ValueError(f"{entry_id}: licence_evidence must be an https URL")
    voices = tuple(
        VoiceInfo(str(v["id"]), str(v.get("label") or v["id"]), str(v.get("language", "")),
                  str(v.get("gender", "")))
        for v in raw.get("voices") or ()
    )  # fmt: skip
    default_voice = raw.get("default_voice")
    if default_voice is not None and default_voice not in {v.id for v in voices}:
        raise ValueError(f"{entry_id}: default_voice is not in voices")
    if "speak" in tasks and voices and default_voice is None:
        raise ValueError(f"{entry_id}: a model with voices needs a default_voice")
    m = raw.get("measured") or {}
    options = tuple(_option(o, entry_id) for o in raw.get("options") or ())
    if len({o.name for o in options}) != len(options):
        raise ValueError(f"{entry_id}: duplicate option name")
    clone = dict(raw.get("clone") or {})
    design = dict(raw.get("design") or {})
    music = dict(raw.get("music") or {})
    _check_rules(entry_id, tasks, clone, design)
    _check_music_rules(entry_id, tasks, music)
    return VoiceModel(
        id=entry_id, title=title, licence=licence, engine=engine, family=str(raw["family"]),
        package=str(raw["package"]), server_task=str(raw.get("server_task", "tts")),
        tasks=tasks, recommended=recommended,
        languages=tuple(str(x) for x in raw.get("languages") or ()),
        sample_rate=int(raw.get("sample_rate", 0)), commercial_use=commercial,
        licence_evidence=str(raw["licence_evidence"]), reviewed=str(raw.get("reviewed", "")),
        measured=Measured(
            str(m.get("platform", "")), m.get("speed_x"), m.get("memory_gb"), m.get("load_s")
        ),
        voices=voices, default_voice=str(default_voice) if default_voice else None,
        options=options, clone=clone, design=design, music=music,
    )  # fmt: skip


DESIGN_VIA = ("instruct_option", "text_prefix")
REFERENCE_TEXT = ("required", "optional")
MAX_DESCRIPTION_CHARS = 300
MAX_REFERENCE_TEXT_CHARS = 1000


def _check_rules(entry_id: str, tasks: tuple[str, ...], clone: dict, design: dict) -> None:
    """How a model takes a reference recording and a voice description (V0: VoxCPM2 ignores the
    option Qwen3-TTS uses, so the delivery is declared, never assumed)."""
    if ("clone" in tasks) != bool(clone):
        raise ValueError(f"{entry_id}: a clone model declares `clone` rules, and only it does")
    if ("design" in tasks) != bool(design):
        raise ValueError(f"{entry_id}: a design model declares `design` rules, and only it does")
    if clone:
        if clone.get("reference_text") not in REFERENCE_TEXT:
            raise ValueError(f"{entry_id}: clone.reference_text must be one of {REFERENCE_TEXT}")
        lo, hi = clone.get("min_seconds"), clone.get("max_seconds")
        if not (isinstance(lo, int | float) and isinstance(hi, int | float) and 0 < lo < hi <= 120):
            raise ValueError(f"{entry_id}: clone needs min_seconds < max_seconds (at most 120)")
    if design:
        if design.get("via") not in DESIGN_VIA:
            raise ValueError(f"{entry_id}: design.via must be one of {DESIGN_VIA}")
        if not 20 <= int(design.get("max_chars", 0)) <= 1000:
            raise ValueError(f"{entry_id}: design.max_chars must be 20 to 1000")


LYRICS = ("optional", "required", "unused")
INSTRUMENTAL = ("toggle", "always", "never")
MUSIC_MODES = ("song", "sfx")
MAX_MUSIC_DESCRIPTION = 500
MAX_LYRICS_CHARS = 5000


def _check_music_rules(entry_id: str, tasks: tuple[str, ...], music: dict) -> None:
    """The modes of a music model and how the runtime takes each part of a request. The shapes
    differ between families (a duration may be a field of the request or an option; lyrics are an
    option; one family sings only when lyrics say so), so the descriptor states them and nothing
    is guessed."""
    if ("music" in tasks) != bool(music):
        raise ValueError(f"{entry_id}: a music model declares `music` rules, and only it does")
    if not music:
        return
    modes = music.get("modes") or {}
    if not modes or set(modes) - set(MUSIC_MODES):
        raise ValueError(f"{entry_id}: music.modes must be among {MUSIC_MODES}")
    for name, mode in modes.items():
        lo, default, hi = mode.get("duration") or [0, 0, 0]
        if not 0 < lo <= default <= hi <= 600:
            raise ValueError(f"{entry_id}: {name} duration must be [min, default, max] seconds")
        if name == "song":
            if mode.get("lyrics") not in LYRICS or mode.get("instrumental") not in INSTRUMENTAL:
                raise ValueError(
                    f"{entry_id}: song needs lyrics {LYRICS} and instrumental {INSTRUMENTAL}"
                )
    request = music.get("request") or {}
    if request.get("duration") not in ("top",) and not str(request.get("duration", "")).startswith(
        "option:"
    ):
        raise ValueError(f"{entry_id}: music.request.duration must be 'top' or 'option:<name>'")
    if any(m.get("lyrics", "unused") != "unused" for m in modes.values()) and not request.get(
        "lyrics_option"
    ):
        raise ValueError(f"{entry_id}: a model that takes lyrics names the option (lyrics_option)")


# ---- validating a request ----------------------------------------------------------------------


def check_options(model: VoiceModel, given: dict[str, Any] | None) -> dict[str, Any]:
    """The options a request may carry, checked against the descriptor. An option the model does not
    declare is refused (the runtime may ignore it without a word); numbers are clamped to their
    bounds; a value of the wrong kind is refused."""
    out: dict[str, Any] = {}
    for name, value in (given or {}).items():
        spec = model.option(str(name))
        if spec is None:
            raise VoiceRequestError(
                "unknown_option", f"{model.title} has no option called '{name}'."
            )
        if value is None:
            continue
        try:
            if spec.type == "bool":
                if not isinstance(value, bool):
                    raise TypeError
                out[spec.name] = value
            elif spec.type in ("int", "float"):
                if isinstance(value, bool) or not isinstance(value, int | float):
                    raise TypeError
                number = float(value)
                if number != number or number in (float("inf"), float("-inf")):
                    raise TypeError
                if spec.min is not None:
                    number = max(spec.min, number)
                if spec.max is not None:
                    number = min(spec.max, number)
                out[spec.name] = int(round(number)) if spec.type == "int" else number
            elif spec.type == "enum":
                if str(value) not in spec.values:
                    raise TypeError
                out[spec.name] = str(value)
            else:
                text = str(value).strip()
                if text:
                    out[spec.name] = text[:4000]
        except TypeError:
            raise VoiceRequestError(
                "bad_option", f"The value for '{spec.label or spec.name}' is not valid."
            ) from None
    return out


def check_speak(
    model: VoiceModel, text: str, voice: str | None, options: dict[str, Any] | None
) -> tuple[str, str | None, dict[str, Any]]:
    """(text, voice, options) ready to send, or a VoiceRequestError in words a person can read."""
    if "speak" not in model.tasks:
        raise VoiceRequestError("wrong_task", f"{model.title} does not make plain speech.")
    clean = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(text or "")).strip()
    if not clean:
        raise VoiceRequestError("empty_text", "Type the text you want to hear.")
    if len(clean) > MAX_SPEAK_CHARS:
        raise VoiceRequestError(
            "text_too_long", f"Please keep it under {MAX_SPEAK_CHARS} characters."
        )
    chosen: str | None = None
    if model.voices:
        chosen = voice or model.default_voice
        if model.voice(str(chosen)) is None:
            raise VoiceRequestError("unknown_voice", f"{model.title} has no voice '{chosen}'.")
    elif voice:
        raise VoiceRequestError("unknown_voice", f"{model.title} has no choice of voice.")
    return clean, chosen, check_options(model, options)


def _clean_text(text: str, what: str, limit: int) -> str:
    clean = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(text or "")).strip()
    if not clean:
        raise VoiceRequestError("empty_text", f"{what} is empty.")
    if len(clean) > limit:
        raise VoiceRequestError("text_too_long", f"{what} is longer than {limit} characters.")
    return clean


def check_design(
    model: VoiceModel, text: str, description: str, options: dict[str, Any] | None
) -> tuple[str, str, dict[str, Any]]:
    """(text, description, options) for speaking in a voice described in words."""
    if "design" not in model.tasks:
        raise VoiceRequestError(
            "wrong_task", f"{model.title} cannot make a voice from a description."
        )
    spoken = _clean_text(text, "The text", MAX_SPEAK_CHARS)
    limit = int(model.design["max_chars"])
    described = " ".join(_clean_text(description, "The description", limit).split())
    if len(described) < 3:
        raise VoiceRequestError("description_too_short", "Describe the voice in a few words.")
    if "(" in described or ")" in described:
        # the description may be placed in front of the text in brackets (VoxCPM2)
        raise VoiceRequestError("bad_description", "Leave brackets out of the description.")
    return spoken, described, check_options(model, options)


def check_clone(
    model: VoiceModel, text: str, reference_text: str | None, options: dict[str, Any] | None
) -> tuple[str, str | None, dict[str, Any]]:
    """(text, reference_text, options) for speaking in a voice cloned from a recording."""
    if "clone" not in model.tasks:
        raise VoiceRequestError("wrong_task", f"{model.title} cannot clone a voice.")
    spoken = _clean_text(text, "The text", MAX_SPEAK_CHARS)
    said = " ".join(str(reference_text or "").split())
    if said:
        said = _clean_text(said, "The words in the recording", MAX_REFERENCE_TEXT_CHARS)
    elif model.clone["reference_text"] == "required":
        raise VoiceRequestError(
            "reference_text_required",
            f"{model.title} needs the words spoken in the recording. Add them to the voice.",
        )
    return spoken, said or None, check_options(model, options)


@dataclass(frozen=True)
class MusicRequest:
    """A music request that passed the checks: what the runtime is asked for."""

    mode: str
    description: str
    lyrics: str
    instrumental: bool
    duration: float
    options: dict[str, Any]
    seed: int | None


def check_music(
    model: VoiceModel,
    mode: str,
    description: str,
    lyrics: str | None,
    instrumental: bool,
    duration: float | None,
    options: dict[str, Any] | None,
    seed: int | None,
) -> MusicRequest:
    """A music request checked against the model's modes. Lyrics that a mode does not sing, and
    vocals in a model that makes none, are refused in words, never dropped quietly; a duration
    outside the model's range is brought into it."""
    if "music" not in model.tasks:
        raise VoiceRequestError("wrong_task", f"{model.title} does not make music.")
    rules = model.music["modes"].get(mode)
    if rules is None:
        raise VoiceRequestError("wrong_mode", f"{model.title} does not make {mode}.")
    described = " ".join(_clean_text(description, "The description", MAX_MUSIC_DESCRIPTION).split())
    if len(described) < 3:
        raise VoiceRequestError("description_too_short", "Describe the music in a few words.")
    words = str(lyrics or "").replace("\r\n", "\n").strip()
    sung = rules.get("lyrics", "unused")
    if words and sung == "unused":
        raise VoiceRequestError("no_lyrics", f"{model.title} does not sing lyrics. Leave them out.")
    if len(words) > MAX_LYRICS_CHARS:
        raise VoiceRequestError(
            "text_too_long", f"Lyrics are longer than {MAX_LYRICS_CHARS} characters."
        )
    vocals = rules.get("instrumental", "always")
    if instrumental and vocals == "never":
        raise VoiceRequestError(
            "no_instrumental", f"{model.title} always sings. Add lyrics instead."
        )
    if instrumental and words:
        raise VoiceRequestError("lyrics_and_instrumental", "A piece without singing has no lyrics.")
    if sung == "required" and not words and not instrumental:
        raise VoiceRequestError("lyrics_required", f"{model.title} needs lyrics to sing.")
    lo, default, hi = rules["duration"]
    asked = default if duration is None else float(duration)
    if asked != asked:
        raise VoiceRequestError("bad_option", "The length is not a number.")
    return MusicRequest(
        mode=mode, description=described, lyrics=words,
        instrumental=bool(instrumental) or vocals == "always", duration=max(lo, min(hi, asked)),
        options=check_options(model, options), seed=None if seed is None else int(seed),
    )  # fmt: skip


def check_transcribe(model: VoiceModel, options: dict[str, Any] | None) -> dict[str, Any]:
    if "transcribe" not in model.tasks:
        raise VoiceRequestError("wrong_task", f"{model.title} does not transcribe speech.")
    return check_options(model, options)


# ---- what a product may ask of the engine -------------------------------------------------------

State = Literal["ready", "can_install", "needs_runtime", "not_available"]


@dataclass(frozen=True)
class SpeechResult:
    wav: bytes
    sample_rate: int
    seconds: float
    model_id: str
    voice: str | None
    load_s: float  # time spent before the model answered (0 when it was already loaded)
    elapsed_s: float


@dataclass(frozen=True)
class MusicResult:
    wav: bytes
    sample_rate: int
    seconds: float
    model_id: str
    seed: int | None
    load_s: float
    elapsed_s: float


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    segments: tuple[TranscriptSegment, ...]
    seconds: float  # length of the audio
    model_id: str
    elapsed_s: float


class SpeechEngine(Protocol):
    """The engine's speech runtime. A product reaches it as `app_state.audio` (never imported)."""

    def models(self, task: str | None = None) -> list[dict[str, Any]]:
        """Descriptors with their state on this computer."""
        ...

    def resolve(self, task: str, model_id: str | None) -> VoiceModel:
        """The model a request means: the one named, else the default for the task. Raises
        VoiceEngineError when it is unknown or not ready, with what to do about it."""
        ...

    async def speak(
        self, model: VoiceModel, text: str, voice: str | None, options: dict[str, Any]
    ) -> SpeechResult: ...

    async def design(
        self, model: VoiceModel, text: str, description: str, options: dict[str, Any]
    ) -> SpeechResult:
        """Speak `text` in a voice described in words (the descriptor says how it is delivered)."""
        ...

    async def clone(
        self,
        model: VoiceModel,
        text: str,
        reference: Path,
        reference_text: str | None,
        options: dict[str, Any],
    ) -> SpeechResult:
        """Speak `text` in the voice of the recording at `reference` (a file on this computer)."""
        ...

    async def music(self, model: VoiceModel, request: MusicRequest) -> MusicResult:
        """Make music (a song or a sound effect) from a checked request."""
        ...

    async def transcribe(
        self, model: VoiceModel, wav: bytes, options: dict[str, Any]
    ) -> TranscriptResult: ...
