"""The guardrail for the pictures a character or style is taught from (ADR-0037, 0047, 0076).

It runs only while the safeguards are on, and it fails closed: if the classifier gives no valid
answer, the picture is not kept and the person can try again. The classifier's own words are never
shown. Whose face it is, is the person's own statement (ADR-0073 decision 7), asked in the Check
step and stored with the dataset: the classifier does not try to tell who anyone is."""

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

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"  # in the package: the wheel has it
ATTEMPTS = 2
REVIEW_PX = 768  # the classifier needs a look at the picture, not every pixel

CATEGORIES = ["ok", "sexual_content", "minors", "graphic_violence", "hate", "disallowed_content"]

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
    "sexual_content": "I can't teach from pictures with nudity or sexual content.",
    "minors": "I can't help with pictures that sexualise children or put them at risk.",
    "graphic_violence": "I can't teach from pictures of graphic violence or gore.",
    "hate": "I can't teach from pictures that promote hatred or show hate symbols.",
    "disallowed_content": "I can't use that picture.",
}


class Verdict(BaseModel):
    allowed: bool
    category: Literal[
        "ok", "sexual_content", "minors", "graphic_violence", "hate", "disallowed_content"
    ]
    reason: str = ""


def refusal_message(category: str) -> str:
    return REFUSALS.get(category, REFUSALS["disallowed_content"])


def prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def _verdict(raw: str) -> Verdict | None:
    try:
        verdict = Verdict.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        return None
    # a verdict that contradicts itself is a refusal: keep the violation it names if it names one
    if verdict.allowed != (verdict.category == "ok"):
        log.warning("training guardrail: inconsistent verdict (%s)", verdict.category)
        category = verdict.category if verdict.category != "ok" else "disallowed_content"
        return Verdict(allowed=False, category=category, reason=verdict.reason)
    return verdict


def review_copy(png: bytes) -> bytes:
    """A small JPEG of the picture for the classifier (and the captioner)."""
    with PILImage.open(io.BytesIO(png)) as im:
        rgb = im.convert("RGB")
    rgb.thumbnail((REVIEW_PX, REVIEW_PX))
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=85)
    return out.getvalue()


async def judge_picture(caps: Capabilities, png: bytes) -> Verdict:
    small = await asyncio.to_thread(review_copy, png)
    user = [prompt("moderation_picture_request"), Image.from_bytes(small, "image/jpeg")]
    system = prompt("moderation_picture")
    for attempt in range(1, ATTEMPTS + 1):
        raw = await caps.text.complete("moderate_image", system, user, schema=SCHEMA)
        if (verdict := _verdict(raw)) is not None:
            return verdict
        log.warning("training guardrail: unparseable verdict (attempt %d of %d)", attempt, ATTEMPTS)
    raise RunError(
        "moderation_unavailable",
        "We couldn't check your picture right now. Please try again.",
        retryable=True,
    )
