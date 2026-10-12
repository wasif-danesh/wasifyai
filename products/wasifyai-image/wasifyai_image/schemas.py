"""The run's input contract and the structured output of the guardrail."""

from typing import Any, Literal

from pydantic import BaseModel

MAX_PROMPT_CHARS = 500
Mode = Literal["text", "image"]

# size name -> (width, height). Multiples of 16, which FLUX.2 needs; about one megapixel each.
SIZES: dict[str, tuple[int, int]] = {
    "square": (1024, 1024),
    "landscape": (1152, 864),  # 4:3
    "portrait": (864, 1152),  # 3:4
    "wide": (1344, 768),  # 16:9
    "tall": (768, 1344),  # 9:16
}
DEFAULT_SIZE = "square"

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
