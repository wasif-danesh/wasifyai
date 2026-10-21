"""The run's input contract and the structured output of the guardrail."""

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
