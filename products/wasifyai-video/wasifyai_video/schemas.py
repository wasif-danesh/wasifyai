"""The run's input contract and the structured output of the guardrail."""

import re
from typing import Any, Literal

from pydantic import BaseModel

MAX_PROMPT_CHARS = 500
Mode = Literal["text", "image", "extend"]

# shape name -> (width, height). Multiples of 32, which LTX-Video needs; about 0.4 megapixel each.
SHAPES: dict[str, tuple[int, int]] = {
    "landscape": (768, 512),  # 3:2
    "portrait": (512, 768),  # 2:3
    "square": (512, 512),
}
DEFAULT_SHAPE = "landscape"

FPS = 24
# seconds -> frames (LTX wants a multiple of 8 plus one). The lengths offered are 5 and 8 seconds
# (owner, 2026-10-21): 2 seconds is too short to judge a model by, and a faster computer than the
# Mac we measured on (ADR-0037) must not be held to a short clip. Add a length here to offer it; the
# worker's limit on the desktop is an hour, and a clip can be stopped.
LENGTHS: dict[int, int] = {5: 121, 8: 193}
DEFAULT_SECONDS = 5

# Extend video (docs/spikes/video-extend-vx0.md): the last OVERLAP_FRAMES frames of a clip start a
# new clip of LENGTHS[seconds] frames, which repeats them first. The clip is kept up to those frames
# and the whole new clip follows, so a round adds LENGTHS[seconds] - OVERLAP_FRAMES frames (112 or
# 184: about 5 or 8 seconds). Any clip can be extended, however long; the picture softens a little
# each round, which the screen says.
OVERLAP_FRAMES = 9  # LTX wants 8 * n + 1

# Looks the person taught (ADR-0073, video amendment): LoRAs on the video model, named by the file
# they are kept in under a `loras` folder, with a strength. TV0 found the look needs about 1.5 to 2
# at the app's guidance of 3, so the range runs higher than for pictures.
MAX_LOOKS = 2
LOOK_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()/-]{0,200}\.safetensors$")
MIN_STRENGTH, MAX_STRENGTH, DEFAULT_STRENGTH = 0.1, 2.5, 1.5


def check_looks(raw: object) -> tuple[list[dict[str, Any]], str]:
    """The looks of a request as `[{name, weight}]`, or why they are refused. A name is a file name
    relative to a `loras` folder: no `..`, no absolute path, only `.safetensors`."""
    if raw in (None, []):
        return [], ""
    if not isinstance(raw, list):
        return [], "Please choose the looks from the list."
    if len(raw) > MAX_LOOKS:
        return [], f"Please use at most {MAX_LOOKS} looks."
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else None
        weight = item.get("weight", DEFAULT_STRENGTH) if isinstance(item, dict) else None
        if not isinstance(name, str) or not LOOK_NAME.match(name) or ".." in name:
            return [], "One of the looks has a name that cannot be used."
        if isinstance(weight, bool) or not isinstance(weight, int | float):
            return [], "A look's strength must be a number."
        if not MIN_STRENGTH <= float(weight) <= MAX_STRENGTH:
            return [], f"A look's strength must be between {MIN_STRENGTH} and {MAX_STRENGTH}."
        if name in seen:
            return [], "Each look can be used once."
        seen.add(name)
        out.append({"name": name, "weight": round(float(weight), 2)})
    return out, ""


CATEGORIES = [
    "ok",
    "sexual_content",
    "minors",
    "graphic_violence",
    "hate",
    "real_person_misuse",
    "disallowed_content",
]


class Moderation(BaseModel):
    allowed: bool
    category: Literal[
        "ok",
        "sexual_content",
        "minors",
        "graphic_violence",
        "hate",
        "real_person_misuse",
        "disallowed_content",
    ]
    reason: str = ""


MODERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "allowed": {"type": "boolean"},
        "category": {"type": "string", "enum": CATEGORIES},
        "reason": {"type": "string"},
    },
    "required": ["allowed", "category", "reason"],
    "additionalProperties": False,
}
