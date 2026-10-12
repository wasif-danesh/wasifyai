"""Structured outputs and the approval contract."""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

MAX_IDEA_CHARS = 500
MAX_TAG_CHARS = 40


class SongDraft(BaseModel):
    """What `text.lyrics` returns (one structured-output call)."""

    title: str = Field(min_length=1, max_length=80)
    lyrics: str = Field(min_length=1, max_length=3000)
    style: str = Field(
        min_length=1, max_length=200
    )  # music tags: "synth-pop, upbeat, female vocal"
    cover_prompt: str = Field(min_length=1, max_length=400)

    @field_validator("title", "style", "cover_prompt")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = re.sub(r"\s+", " ", v).strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class Moderation(BaseModel):
    allowed: bool
    category: Literal["ok", "artist_voice", "existing_lyrics", "disallowed_content"]
    reason: str = ""


class Approval(BaseModel):
    """The user's answer to the `approve_lyrics` interrupt (the resume value)."""

    action: Literal["approve", "regenerate"]
    title: str | None = None  # optional edits, applied on approve
    lyrics: str | None = None
    style: str | None = None


def _object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    """A strict JSON Schema for flat objects. Plain types only: grammars used by local models
    ignore length limits, so lengths are validated after parsing instead."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


SONG_SCHEMA = _object_schema(
    {k: {"type": "string"} for k in ("title", "lyrics", "style", "cover_prompt")}
)
MODERATION_SCHEMA = _object_schema(
    {
        "allowed": {"type": "boolean"},
        "category": {
            "type": "string",
            "enum": ["ok", "artist_voice", "existing_lyrics", "disallowed_content"],
        },
        "reason": {"type": "string"},
    }
)
