"""The guardrail for the pictures a 3D model is made from (ADR-0037, ADR-0047, P6).

It runs only while the safeguards are on, and it fails closed: if the classifier gives no valid
answer, nothing is made and the person can try again. The classifier's own words are never shown."""

import asyncio
import io
import json
import logging
from pathlib import Path
from typing import Any, Literal

from PIL import Image as PILImage
from pydantic import BaseModel, ValidationError
from wasifyai_platform_sdk import Capabilities, Image, RunError

log = logging.getLogger(__name__)

# inside the package when installed from a wheel (the build copies `prompts/` in), else beside it
_HERE = Path(__file__).resolve().parent
PROMPTS_DIR = _HERE / "prompts" if (_HERE / "prompts").is_dir() else _HERE.parent / "prompts"
ATTEMPTS = 2
REVIEW_PX = 768  # the classifier needs a look at the picture, not every pixel

CATEGORIES = [
    "ok", "sexual_content", "minors", "graphic_violence", "hate", "real_person_photo",
    "disallowed_content",
]  # fmt: skip

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "allowed": {"type": "boolean"},
        "category": {"type": "string", "enum": CATEGORIES},
        "reason": {"type": "string"},
    },
    "required": ["allowed", "category", "reason"],
    "additionalProperties": False,
}

REFUSALS = {
    "sexual_content": "I can't make a 3D model from a picture with nudity or sexual content.",
    "minors": "I can't help with pictures that sexualise children or put them at risk.",
    "graphic_violence": "I can't make a 3D model from a picture of graphic violence or gore.",
    "hate": "I can't make a 3D model from a picture that promotes hatred or shows hate symbols.",
    "real_person_photo": (
        "I can't make a 3D model from a photograph of a real person. Use a picture of an object, "
        "an illustration or a cartoon instead."
    ),
    "disallowed_content": "I can't use that picture.",
}


class Verdict(BaseModel):
    allowed: bool
    category: Literal[
        "ok", "sexual_content", "minors", "graphic_violence", "hate", "real_person_photo",
        "disallowed_content",
    ]  # fmt: skip
    reason: str = ""


def refusal_message(category: str) -> str:
    return REFUSALS.get(category, REFUSALS["disallowed_content"])


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def _verdict(raw: str) -> Verdict | None:
    try:
        verdict = Verdict.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        return None
    # a verdict that contradicts itself is a refusal: keep the violation it names if it names one
    if verdict.allowed != (verdict.category == "ok"):
        log.warning("3D guardrail: inconsistent verdict (%s)", verdict.category)
        category = verdict.category if verdict.category != "ok" else "disallowed_content"
        return Verdict(allowed=False, category=category, reason=verdict.reason)
    return verdict


def review_copy(picture: bytes) -> bytes:
    """A small JPEG of the picture for the classifier."""
    with PILImage.open(io.BytesIO(picture)) as im:
        rgb = im.convert("RGB")
    rgb.thumbnail((REVIEW_PX, REVIEW_PX))
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=85)
    return out.getvalue()


async def judge_picture(caps: Capabilities, picture: bytes) -> Verdict:
    small = await asyncio.to_thread(review_copy, picture)
    user = [_prompt("moderation_picture_request"), Image.from_bytes(small, "image/jpeg")]
    system = _prompt("moderation_picture")
    for attempt in range(1, ATTEMPTS + 1):
        raw = await caps.text.complete("moderate_image", system, user, schema=SCHEMA)
        if (verdict := _verdict(raw)) is not None:
            return verdict
        log.warning("3D guardrail: unparseable verdict (attempt %d of %d)", attempt, ATTEMPTS)
    raise RunError(
        "moderation_unavailable",
        "We couldn't check your picture right now. Please try again.",
        retryable=True,
    )
