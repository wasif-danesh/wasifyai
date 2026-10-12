"""The run's input contract and the structured output of the guardrail."""

from typing import Any, Literal

from pydantic import BaseModel

MAX_TEXT_CHARS = 2000
CATEGORIES = [
    "ok",
    "sexual_content",
    "minors",
    "graphic_violence",
    "hate",
    "fraud_or_impersonation",
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
        "fraud_or_impersonation",
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
