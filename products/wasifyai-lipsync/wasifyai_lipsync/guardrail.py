"""The guardrails (ADR-0044), which run only while the safeguards are on (ADR-0047).

Words (a script, the words of an uploaded voice, the style hint) go to the text to speech
moderator, which judges any language. The picture goes to a model that can see it and refuses
photographs of real people. Both fail closed: with no valid answer the run stops with a retryable
error."""

import asyncio
import io
import json
import logging

from PIL import Image as PILImage
from pydantic import ValidationError
from wasifyai_platform_sdk import Capabilities, Image, RunError
from wasifyai_tts import guardrail as speech_guardrail
from wasifyai_tts.schemas import Moderation

from wasifyai_lipsync import prompts
from wasifyai_lipsync.schemas import PICTURE_SCHEMA, PictureVerdict

log = logging.getLogger(__name__)

ATTEMPTS = 2
REVIEW_PX = 768

# What users see. Fixed text: the classifier's own wording is never shown.
PICTURE_REFUSALS = {
    "real_person_photo": (
        "I can't make a photograph of a real person speak. Use an illustration, a cartoon, a 3D "
        "character or an animal instead."
    ),
    "sexual_content": "I can't use pictures with nudity or sexual content.",
    "minors": "I can't help with pictures that sexualise children or put them at risk.",
    "graphic_violence": "I can't use pictures of graphic violence or gore.",
    "hate": "I can't use pictures that promote hatred or show hate symbols.",
    "disallowed_content": "I can't use that picture.",
}


def picture_refusal(category: str) -> str:
    return PICTURE_REFUSALS.get(category, PICTURE_REFUSALS["disallowed_content"])


def words_refusal(category: str) -> str:
    return speech_guardrail.refusal_message(category)


async def judge_words(caps: Capabilities, text: str) -> Moderation:
    """What is said (or sung, or the style asked for), in any language."""
    return await speech_guardrail.judge_text(caps, text)


def _verdict(raw: str) -> PictureVerdict | None:
    try:
        verdict = PictureVerdict.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        return None
    if verdict.allowed != (verdict.category == "ok"):
        log.warning("lip sync guardrail: inconsistent verdict (%s)", verdict.category)
        category = verdict.category if verdict.category != "ok" else "disallowed_content"
        return PictureVerdict(allowed=False, category=category, reason=verdict.reason)
    return verdict


def review_copy(picture: bytes) -> bytes:
    """A small JPEG of the picture for the classifier."""
    with PILImage.open(io.BytesIO(picture)) as im:
        rgb = im.convert("RGB")
    rgb.thumbnail((REVIEW_PX, REVIEW_PX))
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=85)
    return out.getvalue()


async def judge_picture(caps: Capabilities, picture: bytes) -> PictureVerdict:
    small = await asyncio.to_thread(review_copy, picture)
    user = [prompts.load("moderation_picture_request"), Image.from_bytes(small, "image/jpeg")]
    system = prompts.load("moderation_picture")
    for attempt in range(1, ATTEMPTS + 1):
        raw = await caps.text.complete("moderate_image", system, user, schema=PICTURE_SCHEMA)
        if (verdict := _verdict(raw)) is not None:
            return verdict
        log.warning("lip sync guardrail: unparseable verdict (attempt %d of %d)", attempt, ATTEMPTS)
    raise RunError(
        "moderation_unavailable",
        "We couldn't check your picture right now. Please try again.",
        retryable=True,
    )
