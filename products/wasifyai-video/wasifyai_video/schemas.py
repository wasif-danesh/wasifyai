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
# seconds -> frames (LTX wants a multiple of 8 plus one). 8 and 10 seconds do not fit the worker's
# time limit on the Mac (ADR-0037).
LENGTHS: dict[int, int] = {2: 49, 5: 121}
DEFAULT_SECONDS = 2

# Extend video (docs/spikes/video-extend-vx0.md): the last OVERLAP_FRAMES frames of a clip start a
# new clip of EXTEND_FRAMES frames, which repeats them first. The clip is kept up to those frames
# and the whole new clip follows, so each round adds EXTEND_FRAMES - OVERLAP_FRAMES (40) frames,
# 1.7 seconds. A clip of more than MAX_EXTENDABLE_FRAMES cannot be extended again: a 2 second clip
# can be extended twice (49, 89, 129), a 5 second one not at all. The picture softens each round.
OVERLAP_FRAMES = 9  # LTX wants 8 * n + 1
EXTEND_FRAMES = LENGTHS[2]
MAX_EXTENDABLE_FRAMES = 100

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
