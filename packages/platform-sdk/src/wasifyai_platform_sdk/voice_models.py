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
    # audio tools (V4): splitting a recording into stems, changing whose voice it is, editing words
    separate: dict[str, Any] = field(default_factory=dict, hash=False)
    convert: dict[str, Any] = field(default_factory=dict, hash=False)
    speech_edit: dict[str, Any] = field(default_factory=dict, hash=False)
    # lip sync (V5): a picture and a voice in, a video out
    lipsync: dict[str, Any] = field(default_factory=dict, hash=False)

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
            "separate": self.separate, "convert": self.convert, "speech_edit": self.speech_edit,
            "lipsync": self.lipsync,
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
    separate = dict(raw.get("separate") or {})
    convert = dict(raw.get("convert") or {})
    speech_edit = dict(raw.get("speech_edit") or {})
    lipsync = dict(raw.get("lipsync") or {})
    _check_rules(entry_id, tasks, clone, design)
    _check_music_rules(entry_id, engine, tasks, music)
    _check_tool_rules(entry_id, tasks, separate, convert, speech_edit)
    _check_lipsync_rules(entry_id, engine, tasks, lipsync)
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
        separate=separate, convert=convert, speech_edit=speech_edit, lipsync=lipsync,
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
MUSIC_MODES = ("song", "sfx", "edit")
EDIT_ACTIONS = ("repaint", "extend", "cover", "inpaint", "restyle")
EDIT_RECIPES = ("ace_step", "stable_audio")  # how the runtime of each family takes an edit
MAX_MUSIC_DESCRIPTION = 500
MAX_LYRICS_CHARS = 5000


def _check_music_rules(entry_id: str, engine: str, tasks: tuple[str, ...], music: dict) -> None:
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
        if name == "edit":
            actions = tuple(mode.get("actions") or ())
            if not actions or set(actions) - set(EDIT_ACTIONS):
                raise ValueError(f"{entry_id}: edit.actions must be among {EDIT_ACTIONS}")
            if not 1 <= int(mode.get("max_ranges", 0)) <= 16 or not (
                5 <= float(mode.get("max_source_s", 0)) <= 600
            ):
                raise ValueError(f"{entry_id}: edit needs max_ranges (1 to 16) and max_source_s")
            if (music.get("request") or {}).get("edit") not in EDIT_RECIPES:
                raise ValueError(f"{entry_id}: edit needs request.edit, one of {EDIT_RECIPES}")
            continue
        lo, default, hi = mode.get("duration") or [0, 0, 0]
        if not 0 < lo <= default <= hi <= 600:
            raise ValueError(f"{entry_id}: {name} duration must be [min, default, max] seconds")
        if name == "song":
            if mode.get("lyrics") not in LYRICS or mode.get("instrumental") not in INSTRUMENTAL:
                raise ValueError(
                    f"{entry_id}: song needs lyrics {LYRICS} and instrumental {INSTRUMENTAL}"
                )
    request = music.get("request") or {}
    if engine == "comfyui":  # a workflow of the image engine: its map file names the inputs
        if request.get("duration") != "workflow" or not _ID.match(str(request.get("workflow", ""))):
            raise ValueError(
                f"{entry_id}: a ComfyUI music model names its workflow, duration: workflow"
            )
        if "edit" in modes:
            raise ValueError(f"{entry_id}: a ComfyUI workflow here makes music, it does not edit")
    elif request.get("duration") not in ("top",) and not str(
        request.get("duration", "")
    ).startswith("option:"):
        raise ValueError(f"{entry_id}: music.request.duration must be 'top' or 'option:<name>'")
    if any(m.get("lyrics", "unused") != "unused" for m in modes.values()) and not request.get(
        "lyrics_option"
    ):
        raise ValueError(f"{entry_id}: a model that takes lyrics names the option (lyrics_option)")


_STEM = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
CONVERT_TARGETS = ("reference",)  # a recording of the voice to sound like
EDIT_STYLES = ("markup",)  # tagged text: <sub targ="new">old</sub>, <del>, <ins>
MAX_TOOL_SOURCE_S = 3600.0


def _check_tool_rules(
    entry_id: str, tasks: tuple[str, ...], separate: dict, convert: dict, speech_edit: dict
) -> None:
    """What an audio tool needs the descriptor to say (V4): the stems a separator returns, the kind
    of target a converter takes, the style of edit and the longest recording each accepts."""
    for task, rules in (("separate", separate), ("convert", convert), ("edit", speech_edit)):
        if (task in tasks) != bool(rules):
            key = "speech_edit" if task == "edit" else task
            raise ValueError(f"{entry_id}: a {task} model declares `{key}` rules, and only it does")
    if separate:
        stems = tuple(str(x) for x in separate.get("stems") or ())
        if not stems or len(set(stems)) != len(stems) or not all(_STEM.match(x) for x in stems):
            raise ValueError(f"{entry_id}: separate.stems must be distinct names")
        if not 8000 <= int(separate.get("input_rate", 0)) <= 96000:
            raise ValueError(f"{entry_id}: separate.input_rate must be a sample rate")
    if convert:
        if convert.get("target") not in CONVERT_TARGETS:
            raise ValueError(f"{entry_id}: convert.target must be one of {CONVERT_TARGETS}")
        lo, hi = convert.get("reference_seconds") or [0, 0]
        if not 0 < lo < hi <= 120:
            raise ValueError(f"{entry_id}: convert.reference_seconds must be [min, max] (to 120)")
        if not 8000 <= int(convert.get("input_rate", 0)) <= 48000:
            raise ValueError(f"{entry_id}: convert.input_rate must be a sample rate")
        req = convert.get("request") or {}
        if not (req.get("source") and req.get("reference")):
            raise ValueError(f"{entry_id}: convert.request names the source and reference fields")
    if speech_edit:
        if speech_edit.get("style") not in EDIT_STYLES:
            raise ValueError(f"{entry_id}: speech_edit.style must be one of {EDIT_STYLES}")
        if not 8000 <= int(speech_edit.get("input_rate", 0)) <= 48000:
            raise ValueError(f"{entry_id}: speech_edit.input_rate must be a sample rate")
        if not 1 <= int(speech_edit.get("max_changes", 0)) <= 16:
            raise ValueError(f"{entry_id}: speech_edit.max_changes must be 1 to 16")
    for rules in (separate, convert, speech_edit):
        if rules and not 1 <= float(rules.get("max_source_s", 0)) <= MAX_TOOL_SOURCE_S:
            raise ValueError(f"{entry_id}: a tool needs max_source_s (1 to {MAX_TOOL_SOURCE_S:g})")


LIPSYNC_PICTURE = {
    "drawn": "This picture is a drawing, painting or other artwork, not a photograph of a person.",
    "own": "This is a picture of me.",
    "permission": "This is a picture of someone who has given me permission to use it.",
}
LIPSYNC_VOICE = {
    "generated": "The voice was made on this computer from words (text to speech).",
    "own": "This is my own voice.",
    "permission": "The person whose voice this is has given me permission to use it.",
}
MARK_TEXT = "AI-generated"  # drawn on every frame of a lip sync video and written into its metadata


def _check_lipsync_rules(entry_id: str, engine: str, tasks: tuple[str, ...], lipsync: dict) -> None:
    """What a lip sync model declares: the longest voice and the largest picture it takes, the frame
    rate, and that the visible mark is not optional (ADR-0044, ADR-0066 decision 8)."""
    if ("lipsync" in tasks) != bool(lipsync):
        raise ValueError(f"{entry_id}: a lipsync model declares `lipsync` rules, and only it does")
    if not lipsync:
        return
    if engine != "sidecar":
        raise ValueError(f"{entry_id}: a lip sync model runs as a sidecar here")
    if not 5 <= float(lipsync.get("max_voice_s", 0)) <= 3600:
        raise ValueError(f"{entry_id}: lipsync.max_voice_s must be 5 to 3600")
    if not 256 <= int(lipsync.get("max_side", 0)) <= 2048:
        raise ValueError(f"{entry_id}: lipsync.max_side must be 256 to 2048")
    if not 5 <= int(lipsync.get("fps", 0)) <= 60:
        raise ValueError(f"{entry_id}: lipsync.fps must be 5 to 60")
    if lipsync.get("mark") != "required":
        raise ValueError(
            f"{entry_id}: lipsync.mark must be `required`: the mark cannot be left off"
        )


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
    rules = model.music["modes"].get(mode) if mode != "edit" else None
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


@dataclass(frozen=True)
class MusicEditRequest:
    """A change to a clip that passed the checks."""

    action: str
    description: str
    source_seconds: float
    ranges: tuple[tuple[float, float], ...]
    strength: float | None
    extend_s: float | None
    options: dict[str, Any]
    seed: int | None


# which of the optional parts each action takes; any other part given is refused, not ignored
_EDIT_USES = {
    "repaint": {"ranges", "strength"},
    "extend": {"extend_s"},
    "cover": {"strength"},
    "inpaint": {"ranges"},
    "restyle": {"strength"},
}
MAX_EXTEND_S = 120.0


def check_music_edit(
    model: VoiceModel,
    action: str,
    description: str,
    source_seconds: float,
    ranges: list[tuple[float, float]] | None,
    strength: float | None,
    extend_s: float | None,
    options: dict[str, Any] | None,
    seed: int | None,
) -> MusicEditRequest:
    """An edit of a clip checked against what the model can do to one. The parts an action does not
    take are refused; ranges are brought into the clip and joined where they touch."""
    if "music" not in model.tasks:
        raise VoiceRequestError("wrong_task", f"{model.title} does not make music.")
    rules = model.music["modes"].get("edit")
    if rules is None:
        raise VoiceRequestError("wrong_mode", f"{model.title} cannot change a clip.")
    if action not in rules["actions"]:
        raise VoiceRequestError("wrong_action", f"{model.title} cannot {action} a clip.")
    described = " ".join(_clean_text(description, "The description", MAX_MUSIC_DESCRIPTION).split())
    if len(described) < 3:
        raise VoiceRequestError("description_too_short", "Describe the change in a few words.")
    limit = float(rules["max_source_s"])
    if not 0 < source_seconds <= limit:
        raise VoiceRequestError(
            "clip_length", f"{model.title} changes clips of up to {limit:g} seconds."
        )
    uses = _EDIT_USES[action]
    if "ranges" not in uses and ranges:
        raise VoiceRequestError("no_ranges", f"To {action} a clip, leave the parts out.")
    if "strength" not in uses and strength is not None:
        raise VoiceRequestError("no_strength", f"To {action} a clip, leave the strength out.")
    if "extend_s" not in uses and extend_s is not None:
        raise VoiceRequestError("no_extend", f"To {action} a clip, leave the extra length out.")
    merged: list[tuple[float, float]] = []
    if "ranges" in uses:
        clamped = sorted(
            (max(0.0, float(a)), min(source_seconds, float(b))) for a, b in (ranges or [])
        )
        for a, b in clamped:
            if b - a < 0.2:
                continue
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        if not merged:
            raise VoiceRequestError("ranges_required", f"Pick the part of the clip to {action}.")
        if len(merged) > int(rules["max_ranges"]):
            raise VoiceRequestError(
                "too_many_ranges",
                f"{model.title} changes up to {rules['max_ranges']} part(s) at once.",
            )
    if strength is not None and not 0.0 <= float(strength) <= 1.0:
        raise VoiceRequestError("bad_option", "The strength is between 0 and 1.")
    if "extend_s" in uses:
        if extend_s is None or not 1.0 <= float(extend_s) <= MAX_EXTEND_S:
            raise VoiceRequestError(
                "extend_required", f"Say how many seconds to add (1 to {MAX_EXTEND_S:g})."
            )
        if source_seconds + float(extend_s) > limit:
            raise VoiceRequestError(
                "clip_length",
                f"The result would pass {limit:g} seconds, the most {model.title} makes.",
            )
    return MusicEditRequest(
        action=action, description=described, source_seconds=float(source_seconds),
        ranges=tuple(merged), strength=None if strength is None else float(strength),
        extend_s=None if extend_s is None else float(extend_s),
        options=check_options(model, options), seed=None if seed is None else int(seed),
    )  # fmt: skip


@dataclass(frozen=True)
class SeparateRequest:
    options: dict[str, Any]
    source_seconds: float


def _source_length(model: VoiceModel, rules: dict[str, Any], seconds: float) -> float:
    if not seconds or seconds != seconds or seconds < 1:
        raise VoiceRequestError("too_short", "That recording is under one second.")
    if seconds > float(rules["max_source_s"]):
        raise VoiceRequestError(
            "too_long",
            f"{model.title} takes a recording of up to {float(rules['max_source_s']) / 60:g} "
            "minutes. Cut it shorter first.",
        )
    return seconds


def check_separate(
    model: VoiceModel, source_seconds: float, options: dict[str, Any] | None
) -> SeparateRequest:
    """Splitting a recording into stems: the model must be a separator and the recording a length
    it takes."""
    if "separate" not in model.tasks:
        raise VoiceRequestError("wrong_task", f"{model.title} does not split music into stems.")
    _source_length(model, model.separate, source_seconds)
    return SeparateRequest(check_options(model, options), source_seconds)


@dataclass(frozen=True)
class ConvertRequest:
    options: dict[str, Any]
    seed: int | None
    source_seconds: float


def check_convert(
    model: VoiceModel,
    source_seconds: float,
    reference_seconds: float,
    options: dict[str, Any] | None,
    seed: int | None = None,
) -> ConvertRequest:
    """Making a recording sound like another voice: a source it can take and a recording of the
    voice to sound like of the length the model wants."""
    if "convert" not in model.tasks:
        raise VoiceRequestError("wrong_task", f"{model.title} does not change a voice.")
    _source_length(model, model.convert, source_seconds)
    lo, hi = model.convert["reference_seconds"]
    if not lo <= reference_seconds <= hi + 0.5:
        raise VoiceRequestError(
            "reference_length",
            f"{model.title} needs a recording of the voice of {lo:g} to {hi:g} seconds.",
        )
    return ConvertRequest(
        check_options(model, options), None if seed is None else int(seed), source_seconds
    )


@dataclass(frozen=True)
class SpeechEditRequest:
    instruction: str  # the original words with the changes tagged
    old_text: str
    new_text: str
    options: dict[str, Any]
    seed: int | None
    source_seconds: float


_WORD = re.compile(r"[\u3400-\u9fff]|[^\W_]+")  # words only: punctuation is not a change
_CJK = re.compile(r"[\u3000-\u9fff]")
MAX_EDIT_CHARS = 1000


def _word_spans(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group().casefold()) for m in _WORD.finditer(text)]


def edit_markup(old: str, new: str, max_changes: int = 5) -> str:
    """The recording's words with the changes marked the way the editing model reads them:
    `<sub targ="new">old</sub>`, `<del>old</del>`, `<ins>new</ins>`. Changes separated by one or two
    unchanged words are joined into one, so the model gets a few clear edits, not a scatter."""
    from difflib import SequenceMatcher

    a, b = _word_spans(old), _word_spans(new)
    ops = SequenceMatcher(None, [x[2] for x in a], [x[2] for x in b], autojunk=False).get_opcodes()
    regions: list[list[int]] = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        if regions and i1 - regions[-1][1] <= 2 and i1 > regions[-1][1]:
            regions[-1][1], regions[-1][3] = i2, j2
        elif regions and i1 == regions[-1][1]:
            regions[-1][1], regions[-1][3] = i2, j2
        else:
            regions.append([i1, i2, j1, j2])
    if not regions:
        raise VoiceRequestError("no_change", "The words are the same. Change some of them.")
    if len(regions) > max_changes:
        raise VoiceRequestError(
            "too_many_changes",
            f"That is more than {max_changes} separate changes. Make fewer changes at a time.",
        )
    out: list[str] = []
    pos = 0
    for i1, i2, j1, j2 in regions:
        start = a[i1][0] if i1 < len(a) else len(old)
        out.append(old[pos:start])
        gone = old[a[i1][0] : a[i2 - 1][1]] if i2 > i1 else ""
        came = new[b[j1][0] : b[j2 - 1][1]] if j2 > j1 else ""
        if gone and came:
            out.append(f'<sub targ="{came}">{gone}</sub>')
            pos = a[i2 - 1][1]
        elif gone:
            end = a[i2 - 1][1]
            tail = old[end : end + 1]
            keep = tail if tail.isspace() else ""
            out.append(f"<del>{gone}{keep}</del>")
            pos = end + len(keep)
        else:
            more = "" if _CJK.search(came[-1:]) or i1 >= len(a) else " "
            lead = " " if i1 >= len(a) and not _CJK.search(came[:1]) and old[-1:] else ""
            out.append(f"<ins>{lead}{came}{more}</ins>")
            pos = start
    out.append(old[pos:])
    return "".join(out)


def check_speech_edit(
    model: VoiceModel,
    source_seconds: float,
    old_text: str,
    new_text: str,
    options: dict[str, Any] | None,
    seed: int | None = None,
) -> SpeechEditRequest:
    """Changing the words in a recording: what was said, what it should say, and a recording the
    model can take. Characters that would be read as markup are refused."""
    if "edit" not in model.tasks:
        raise VoiceRequestError("wrong_task", f"{model.title} does not edit speech.")
    _source_length(model, model.speech_edit, source_seconds)
    old = " ".join(_clean_text(old_text, "What was said", MAX_EDIT_CHARS).split())
    new = " ".join(_clean_text(new_text, "The new words", MAX_EDIT_CHARS).split())
    if len(old) < 2 or len(new) < 2:
        raise VoiceRequestError(
            "text_required", "Write what the recording says, and what it should say."
        )
    if any(c in old + new for c in '<>"'):
        raise VoiceRequestError("bad_text", "Leave < > and double quotes out of the words.")
    instruction = edit_markup(old, new, int(model.speech_edit["max_changes"]))
    return SpeechEditRequest(
        instruction, old, new, check_options(model, options),
        None if seed is None else int(seed), source_seconds,
    )  # fmt: skip


@dataclass(frozen=True)
class LipSyncRequest:
    consent: dict[str, str]  # what the person said about the picture and the voice
    fps: int
    voice_seconds: float
    mark: str


def check_lipsync(
    model: VoiceModel,
    voice_seconds: float,
    picture_basis: str | None,
    voice_basis: str | None,
    options: dict[str, Any] | None = None,
) -> LipSyncRequest:
    """A lip sync request: a voice of a length the model takes, and the person's word about whose
    picture and whose voice these are. Without that word it is refused, whatever the model is."""
    if "lipsync" not in model.tasks:
        raise VoiceRequestError("wrong_task", f"{model.title} does not make talking videos.")
    if picture_basis not in LIPSYNC_PICTURE:
        raise VoiceRequestError(
            "consent_required",
            "Say what the picture is: a drawing, a picture of you, or of someone who agreed.",
        )
    if voice_basis not in LIPSYNC_VOICE:
        raise VoiceRequestError(
            "consent_required",
            "Say whose voice this is: made here from words, yours, or one you may use.",
        )
    if not voice_seconds or voice_seconds != voice_seconds or voice_seconds < 1:
        raise VoiceRequestError("too_short", "That voice is under one second.")
    if voice_seconds > float(model.lipsync["max_voice_s"]):
        raise VoiceRequestError(
            "too_long",
            f"{model.title} takes a voice of up to {float(model.lipsync['max_voice_s']) / 60:g} "
            "minutes. Use a shorter one.",
        )
    check_options(model, options)
    return LipSyncRequest(
        {"picture": picture_basis, "voice": voice_basis},
        int(model.lipsync["fps"]), voice_seconds, MARK_TEXT,
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
    displaced: str | None = None  # whose model was unloaded to make room (read aloud, ADR-0083)


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
class Stem:
    name: str
    wav: bytes
    sample_rate: int
    seconds: float


@dataclass(frozen=True)
class SeparateResult:
    stems: tuple[Stem, ...]
    model_id: str
    load_s: float
    elapsed_s: float


@dataclass(frozen=True)
class LipSyncResult:
    mp4: bytes
    seconds: float
    fps: int
    width: int
    height: int
    model_id: str
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
    displaced: str | None = None  # whose model was unloaded to make room (dictation, ADR-0083)


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
        self,
        model: VoiceModel,
        text: str,
        voice: str | None,
        options: dict[str, Any],
        *,
        beside: bool = False,
    ) -> SpeechResult:
        """Speak `text`. `beside`: a short passage read aloud in the chat, which may keep the model
        in memory next to the chat model when the two fit (the engine's slot decides)."""
        ...

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

    async def music_edit(
        self, model: VoiceModel, request: MusicEditRequest, source: Path
    ) -> MusicResult:
        """Change a clip that is a file on this computer."""
        ...

    async def transcribe(
        self, model: VoiceModel, wav: bytes, options: dict[str, Any], *, beside: bool = False
    ) -> TranscriptResult:
        """Write down a recording. `beside`: a short clip for dictation, which may keep the model
        in memory next to the chat model when the two fit (the engine's slot decides)."""
        ...

    async def separate(
        self, model: VoiceModel, request: SeparateRequest, source: Path
    ) -> SeparateResult:
        """Split a recording that is a file on this computer into stems."""
        ...

    async def convert(
        self, model: VoiceModel, request: ConvertRequest, source: Path, reference: Path
    ) -> SpeechResult:
        """Make the recording at `source` sound like the voice in the recording at `reference`."""
        ...

    async def speech_edit(
        self, model: VoiceModel, request: SpeechEditRequest, source: Path
    ) -> SpeechResult:
        """Change the words in the recording at `source`."""
        ...

    async def lipsync(
        self, model: VoiceModel, request: LipSyncRequest, picture: Path, voice: Path
    ) -> LipSyncResult:
        """Make a video of the face in the picture saying the voice (files on this computer)."""
        ...
