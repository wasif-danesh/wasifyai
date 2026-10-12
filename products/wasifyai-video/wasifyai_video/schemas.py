"""The run's input contract and the structured output of the guardrail."""

from typing import Any, Literal

from pydantic import BaseModel

MAX_PROMPT_CHARS = 500
Mode = Literal["text", "image"]

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
