"""Music and sound effects on the cloud models (ADR-0100, stage CP8): what each song, sound effect,
splitting and editing model is sent on each provider, how its answer is read, and the descriptors
the music screens read while a product runs there.

Four cloud products carry the music tools, each with its own model in use (Settings › Your keys):
`music` makes songs, `sfx` sound effects, `split` takes a recording apart into stems, and
`musicedit` changes a stretch of a clip. The field names are the providers' own where
`docs/spikes/cloud-v1-cp0.md` and the providers' model pages show them (read 2026-11-12); the ones
not shown there are marked "(CP13)" and checked in the real run."""

import io
import zipfile
from dataclasses import dataclass
from typing import Any

from wasifyai_platform_sdk import MusicEditRequest, MusicRequest, VoiceEngineError
from wasifyai_platform_sdk.fal import FalError
from wasifyai_platform_sdk.voice_models import VoiceModel

KEYED_MUSIC = "key:music"
KEYED_SFX = "key:sfx"
KEYED_SPLIT = "key:split"
KEYED_MUSICEDIT = "key:musicedit"
# the cloud product of each music model id
MUSIC_PRODUCTS = {
    KEYED_MUSIC: "music",
    KEYED_SFX: "sfx",
    KEYED_SPLIT: "split",
    KEYED_MUSICEDIT: "musicedit",
}
MUSIC_IDS = {v: k for k, v in MUSIC_PRODUCTS.items()}

# ---- songs and sound effects -------------------------------------------------------------------

# what each cloud model can do, in the shape the music screen and `check_music` read. MiniMax and
# Mureka choose the length themselves (they take no duration), so their one length is only shown.
MINIMAX_MODES = {
    "song": {"lyrics": "optional", "instrumental": "toggle", "duration": [120, 120, 120]}
}
MINIMAX = (  # MiniMax's endpoints, each of which refuses a description under ten letters
    "fal-ai/minimax-music/v2.6", "minimax/music-2.6", "minimax:music@2.6",
    "minimax/music-3", "minimax/music-3.0",
)  # fmt: skip
MINIMAX_MIN_PROMPT = 10
# by the catalogue's id for the model (`own_keys_catalogue.py`); an admin's row on the web names
# fal.ai's endpoint, so that is found too (`_model_id` in `own_keys_engines.py`)
MUSIC_MODELS: dict[str, tuple[str, dict[str, Any]]] = {
    "minimax-music-2.6": ("MiniMax Music 2.6", MINIMAX_MODES),
    "minimax-music-3": ("MiniMax Music 3", MINIMAX_MODES),
    "elevenlabs-music": (
        "ElevenLabs Music v2.5",
        {"song": {"lyrics": "unused", "instrumental": "toggle", "duration": [3, 30, 600]}},
    ),
    # Mureka sings only words it is given; an instrumental goes to its own endpoint
    "mureka-v9.5": (
        "Mureka v9.5",
        {"song": {"lyrics": "required", "instrumental": "toggle", "duration": [180, 180, 180]}},
    ),
    "elevenlabs-sfx-v2": ("ElevenLabs Sound Effects", {"sfx": {"duration": [0.5, 5, 22]}}),
    "elevenlabs-sfx-v3": ("ElevenLabs Sound Effects v3", {"sfx": {"duration": [0.5, 5, 30]}}),
    "mirelo-sfx-2": ("Mirelo SFX 2.0", {"sfx": {"duration": [1, 5, 120]}}),
    "stable-audio-3-sfx": ("Stable Audio 3 small", {"sfx": {"duration": [1, 8, 120]}}),
}  # fmt: skip


def _needs_lyrics(where: str) -> FalError:
    """Refused before anything is sent, so another offer of the model may take it."""
    return FalError("provider_refused", f"{where} sings only words it is given: add lyrics.", True)


def music_job(req: MusicRequest) -> dict[str, Any]:
    """What a song or sound effect is priced by: its length, and whether it is sung."""
    return {"seconds": req.duration, "task": "instrumental" if req.instrumental else "song"}


def music_verb(endpoint_model: str, req: MusicRequest) -> str:
    """The verb an offer's endpoint is looked up by: Mureka's instrumentals have their own."""
    return "instrumental" if endpoint_model == "mureka-v9.5" and req.instrumental else "song"


def music_body(endpoint: str, req: MusicRequest) -> dict[str, Any]:
    """What the model is sent for a checked music request (fal.ai's fields, WaveSpeed's or a
    Runware task)."""
    if endpoint in MINIMAX and len(req.description) < MINIMAX_MIN_PROMPT:
        raise VoiceEngineError(
            "description_too_short", "Describe the music in at least ten letters for MiniMax."
        )
    if endpoint == "minimax:music@2.6":  # Runware: an `audioInference` task
        settings: dict[str, Any] = {"instrumental": req.instrumental}
        if req.lyrics:
            settings["lyrics"] = req.lyrics
        elif not req.instrumental:
            settings["lyricsOptimizer"] = True
        return {
            "taskType": "audioInference", "positivePrompt": req.description,
            "outputFormat": "WAV", "settings": settings, "includeCost": True,
        }  # fmt: skip
    if endpoint in ("minimax/music-2.6", "minimax/music-3.0"):  # WaveSpeed
        ws: dict[str, Any] = {"prompt": req.description, "is_instrumental": req.instrumental}
        if req.lyrics:
            ws["lyrics"] = req.lyrics
        elif not req.instrumental:
            # a song needs words: Music 3 writes them when asked; 2.6 here cannot (CP13)
            if endpoint == "minimax/music-2.6":
                raise _needs_lyrics("MiniMax Music 2.6 on WaveSpeed")
            ws["lyrics_optimizer"] = True
        return ws
    if endpoint == "minimax/music-3":  # fal.ai: it takes words only, and picks no length (CP13)
        if req.instrumental or not req.lyrics:
            raise _needs_lyrics("MiniMax Music 3 on fal.ai")
        return {"prompt": req.description, "lyrics": req.lyrics}
    if endpoint == "fal-ai/minimax-music/v2.6":
        body: dict[str, Any] = {"prompt": req.description, "is_instrumental": req.instrumental}
        if req.lyrics:
            body["lyrics"] = req.lyrics
        elif not req.instrumental:
            body["lyrics_optimizer"] = True  # MiniMax writes the words from the description
        return body
    if endpoint in ("fal-ai/elevenlabs/music", "elevenlabs/music-v2.5"):
        return {
            "prompt": req.description, "music_length_ms": round(req.duration * 1000),
            "force_instrumental": req.instrumental,
        }  # fmt: skip
    if endpoint.startswith(("mureka-ai/", "mureka/")):  # a song takes lyrics; bgm does not
        mureka: dict[str, Any] = {"prompt": req.description}
        if not req.instrumental:
            mureka["lyrics"] = req.lyrics
        return mureka
    if endpoint == "elevenlabs/sound-effects-v3":  # WaveSpeed (CP13: its names)
        return {"prompt": req.description, "duration": req.duration, "loop": False}
    if endpoint in ("mirelo-ai/sfx-2.0/text-to-audio", "mirelo-ai/sfx2.0/text-to-audio"):
        return {"prompt": req.description, "duration": req.duration}  # (CP13: fal.ai's names)
    if endpoint == "fal-ai/stable-audio-3/small/sfx/text-to-audio":  # (CP13)
        return {"prompt": req.description, "duration": req.duration, "output_format": "wav"}
    return {"text": req.description, "duration_seconds": req.duration}  # fal.ai's ElevenLabs SFX


# ---- splitting a recording into stems ----------------------------------------------------------


@dataclass(frozen=True)
class CloudSplit:
    """A model that takes a recording apart: the stems it returns (by this app's names), the name
    each has in the provider's answer, and the longest recording it takes."""

    name: str
    stems: tuple[str, ...]
    answer: dict[str, str]  # the provider's name for a stem -> this app's
    max_source_s: float = 600


SPLIT_MODELS: dict[str, CloudSplit] = {
    # Demucs's six-stem model (fal.ai; `model` picks it)
    "demucs": CloudSplit(
        "Demucs (6 parts)", ("drums", "bass", "other", "vocals", "guitar", "piano"),
        {s: s for s in ("drums", "bass", "other", "vocals", "guitar", "piano")},
    ),
    # SAM Audio takes out the sound it is told to: here the singing, and the rest
    "sam-audio": CloudSplit(
        "SAM Audio (vocals)", ("vocals", "instrumental"),
        {"target": "vocals", "residual": "instrumental"},
    ),
    # Mureka's first separation: the singing and the backing (CP0: the page lists two prices,
    # $0.09 and $1.05; the cheaper one is this; measured in CP13 before use)
    "mureka-stems": CloudSplit(
        "Mureka stems", ("vocals", "instrumental"),
        {"vocals": "vocals", "instrumental": "instrumental", "accompaniment": "instrumental"},
    ),
}  # fmt: skip
SPLIT_RATE = 44100
MP3_ONLY = {("mureka-stems", "fal")}  # splitters that cannot read a WAV: sent an MP3 (CP13)
SAM_PROMPT = "singing voice"


def split_body(model_id: str, provider: str, audio: str) -> dict[str, Any]:
    """What a splitter is sent for the recording at `audio` (an address on the provider)."""
    if model_id == "demucs":
        return {"audio_url": audio, "model": "htdemucs_6s"}
    if model_id == "sam-audio":
        return {"audio_url": audio, "prompt": SAM_PROMPT}
    if provider == "wavespeed":  # Mureka stems on WaveSpeed
        return {"audio": audio, "model": "audio-separation-1"}
    return {"audio_url": audio, "model": "audio-separation-1"}  # (CP13: fal.ai's names)


def stems_of(model_id: str, result: dict[str, Any]) -> list[tuple[str, Any]]:
    """The stems in a splitter's answer, by this app's names, each with where its file is (a URL
    or fal.ai's `{url, content_type}`). WaveSpeed answers a list in the model's own order."""
    model = SPLIT_MODELS[model_id]
    outputs = result.get("outputs")
    if isinstance(outputs, list):  # WaveSpeed: addresses, in the order of the stems
        return [(s, u) for s, u in zip(model.stems, outputs, strict=False) if u]
    found: list[tuple[str, Any]] = []
    stems = result.get("stems")
    holder: dict[str, Any] = stems if isinstance(stems, dict) else result
    for theirs, ours in model.answer.items():
        item = holder.get(theirs)
        if item and ours not in (s for s, _ in found):
            found.append((ours, item))
    return found


# a stem's file in a zip, by the words its name holds (Mureka stems on fal.ai answers a zip, CP13)
ZIP_STEMS = (("vocal", "vocals"), ("accompan", "instrumental"), ("instrument", "instrumental"),
             ("backing", "instrumental"), ("drum", "drums"), ("bass", "bass"))  # fmt: skip
AUDIO_EXTS = (".wav", ".mp3", ".flac", ".m4a", ".ogg")


def stems_in_zip(model_id: str, data: bytes) -> list[tuple[str, bytes, str]]:
    """The stems of a splitter's zip, by this app's names (each name once), with their files."""
    wanted = set(SPLIT_MODELS[model_id].stems)
    found: list[tuple[str, bytes, str]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                low = info.filename.lower()
                ext = next((e for e in AUDIO_EXTS if low.endswith(e)), None)
                if ext is None or low.startswith("__macosx"):
                    continue
                name = next((ours for word, ours in ZIP_STEMS if word in low), None)
                if name in wanted and name not in (n for n, _, _ in found):
                    found.append((name, z.read(info), ext))
    except zipfile.BadZipFile:
        raise VoiceEngineError(
            "engine_failed", "The parts came back in a file that is not a zip."
        ) from None
    return found


def split_model(model_id: str, title: str, family: str) -> VoiceModel:
    m = SPLIT_MODELS.get(model_id)
    if m is None:
        raise VoiceEngineError(
            "not_with_key", f"{model_id} is not a splitting model this app uses."
        )
    return VoiceModel(
        id=KEYED_SPLIT, title=title, engine="remote", family=family, package="",
        server_task="separate", tasks=("separate",), recommended=("separate",), languages=(),
        sample_rate=SPLIT_RATE,
        separate={"stems": list(m.stems), "input_rate": SPLIT_RATE, "max_source_s": m.max_source_s},
    )  # fmt: skip


# ---- changing a stretch of a clip --------------------------------------------------------------

# what each editing model can do, as `check_music_edit` reads it, and how its runtime takes an
# edit (`EDIT_RECIPES`). ACE-Step repaints one stretch (Runware: `repaintingStart`/`End`, CP0);
# Stable Audio 3 fills one stretch in
EDIT_MODELS: dict[str, tuple[str, dict[str, Any], str]] = {
    "ace-step-edit": (
        "ACE-Step 1.5 (edit)",
        {"actions": ["repaint"], "max_ranges": 1, "max_source_s": 240},
        "ace_step",
    ),
    "stable-audio-3-inpaint": (
        "Stable Audio 3 (edit)",
        {"actions": ["inpaint"], "max_ranges": 1, "max_source_s": 120},
        "stable_audio",
    ),
}


def edit_job(req: MusicEditRequest) -> dict[str, Any]:
    return {"seconds": req.source_seconds}


def edit_body(endpoint: str, provider: str, audio: str, req: MusicEditRequest) -> dict[str, Any]:
    """What an editing model is sent: the clip (an address, or Runware's upload id), the
    description and the one stretch to change."""
    start, end = req.ranges[0]
    if provider == "runware":  # ACE-Step's repaint: an `audioInference` task (CP0)
        return {
            "taskType": "audioInference", "positivePrompt": req.description,
            "inputs": {"audio": audio},  # no `duration` with a clip: Runware refuses it (CP13)
            "settings": {"repaintingStart": round(start, 2), "repaintingEnd": round(end, 2)},
            "outputFormat": "WAV", "includeCost": True,
        }  # fmt: skip
    if endpoint == "fal-ai/ace-step/audio-inpaint":  # (CP13)
        return {
            "audio_url": audio, "tags": req.description, "lyrics": "",
            "start_time": round(start, 2), "end_time": round(end, 2),
        }  # fmt: skip
    return {  # Stable Audio 3 inpainting on fal.ai (CP13)
        "audio_url": audio, "prompt": req.description, "output_format": "wav",
        "mask_start_seconds": round(start, 2), "mask_end_seconds": round(end, 2),
    }  # fmt: skip


def edit_model(model_id: str, title: str, family: str) -> VoiceModel:
    found = EDIT_MODELS.get(model_id)
    if found is None:
        raise VoiceEngineError("not_with_key", f"{model_id} is not an editing model this app uses.")
    _, rules, recipe = found
    return VoiceModel(
        id=KEYED_MUSICEDIT, title=title, engine="remote", family=family, package="",
        server_task="music", tasks=("music",), recommended=(), languages=("multi",),
        sample_rate=44100,
        music={"modes": {"edit": dict(rules)}, "request": {"duration": "top", "edit": recipe}},
    )  # fmt: skip


def music_model(product: str, model_id: str, title: str, family: str) -> VoiceModel:
    """The model offered while `product` (music, sfx, split or musicedit) runs on a cloud model."""
    if product == "split":
        return split_model(model_id, title, family)
    if product == "musicedit":
        return edit_model(model_id, title, family)
    found = MUSIC_MODELS.get(model_id)
    if found is None:
        raise VoiceEngineError("not_with_key", f"{model_id} is not a music model this app uses.")
    return VoiceModel(
        id=MUSIC_IDS[product], title=title, engine="remote", family=family, package="",
        server_task="music", tasks=("music",), recommended=(), languages=("multi",),
        sample_rate=44100,
        music={"modes": found[1], "request": {"duration": "top", "lyrics_option": "lyrics"}},
    )  # fmt: skip


def model_name(model_id: str, fallback: str) -> str:
    """The model's own name, for its title."""
    for table in (MUSIC_MODELS, EDIT_MODELS):
        if model_id in table:
            return table[model_id][0]
    split = SPLIT_MODELS.get(model_id)
    return split.name if split else fallback
