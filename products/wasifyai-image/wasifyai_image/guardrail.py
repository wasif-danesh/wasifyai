"""The mandatory guardrail (ADR-0036): every request passes it before any generation.

It fails closed: if the classifier cannot give a valid answer, the run stops with a retryable
error. It never defaults to "allowed". The picture a user uploads is judged by a model that can see
it; the words are judged by the text moderator as well."""

import asyncio
import io
import json
import logging

from PIL import Image as PILImage
from pydantic import ValidationError
from wasifyai_platform_sdk import Capabilities, EnhanceRefused, Image, RunError

from wasifyai_image import prompts
from wasifyai_image.schemas import MODERATION_SCHEMA, Moderation

log = logging.getLogger(__name__)

ATTEMPTS = 2
REVIEW_PX = 768  # the classifier needs a look at the picture, not every pixel

# What users see. Fixed text: the classifier's own wording is never shown.
REFUSALS = {
    "sexual_content": "I can't make or change images with nudity or sexual content.",
    "minors": "I can't help with images that sexualise children or put them at risk.",
    "graphic_violence": "I can't make graphic violent or gory images.",
    "hate": "I can't make images that promote hatred or use hate symbols.",
    "real_person_misuse": (
        "I can't make images of real people, or change a picture to impersonate someone or to "
        "mislead. Describe a fictional or generic person instead."
    ),
    "disallowed_content": "I can't help with that request.",
}


def refusal_message(category: str) -> str:
    return REFUSALS.get(category, REFUSALS["disallowed_content"])


def _verdict(raw: str) -> Moderation | None:
    try:
        verdict = Moderation.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        return None
    # A verdict that contradicts itself is a refusal: keep the violation it names if it names one.
    if verdict.allowed != (verdict.category == "ok"):
        log.warning("image guardrail: inconsistent verdict (%s)", verdict.category)
        category = verdict.category if verdict.category != "ok" else "disallowed_content"
        return Moderation(allowed=False, category=category, reason=verdict.reason)
    return verdict


async def _ask(caps: Capabilities, capability: str, system: str, user) -> Moderation:
    for attempt in range(1, ATTEMPTS + 1):
        raw = await caps.text.complete(capability, system, user, schema=MODERATION_SCHEMA)
        if (verdict := _verdict(raw)) is not None:
            return verdict
        log.warning("image guardrail: unparseable verdict (attempt %d of %d)", attempt, ATTEMPTS)
    raise RunError(
        "moderation_unavailable",
        "We couldn't check your request right now. Please try again.",
        retryable=True,
    )


async def judge_text(caps: Capabilities, kind: str, text: str) -> Moderation:
    """Classify a description or an edit instruction (kind: "image description" or
    "edit instruction")."""
    return await _ask(
        caps,
        "moderate",
        prompts.load("moderation"),
        prompts.render("moderation_request", kind=kind, text=text),
    )


def review_copy(picture: bytes) -> bytes:
    """A small JPEG of the picture for the classifier."""
    with PILImage.open(io.BytesIO(picture)) as im:
        rgb = im.convert("RGB")
    rgb.thumbnail((REVIEW_PX, REVIEW_PX))
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=85)
    return out.getvalue()


async def judge_picture(caps: Capabilities, instruction: str, picture: bytes) -> Moderation:
    """Classify the instruction together with the picture it would be applied to."""
    small = await asyncio.to_thread(review_copy, picture)
    user = [
        prompts.render("moderation_picture_request", text=instruction),
        Image.from_bytes(small, "image/jpeg"),
    ]
    return await _ask(caps, "moderate_image", prompts.load("moderation_picture"), user)


async def enhance_guard(caps: Capabilities, kind: str, text: str, picture: bytes | None) -> None:
    """The guardrail for the Enhance button (ADR-0038): the user's words, and their picture if the
    kind has one, must pass before the model writes anything."""
    what = "image description" if kind == "text_to_image" else "edit instruction"
    verdict = await judge_text(caps, what, text)
    if verdict.allowed and picture is not None:
        verdict = await judge_picture(caps, text, picture)
    if not verdict.allowed:
        raise EnhanceRefused(refusal_message(verdict.category))
