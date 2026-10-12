"""The mandatory guardrail (product rule: every run passes it before any generation).

It fails closed: if the classifier cannot give a valid answer, the run stops with a retryable
error. It never defaults to "allowed"."""

import json
import logging

from pydantic import ValidationError
from wasifyai_platform_sdk import Capabilities, EnhanceRefused, RunError

from wasifyai_music import prompts
from wasifyai_music.schemas import MODERATION_SCHEMA, Moderation

log = logging.getLogger(__name__)

ATTEMPTS = 2

# What users see. Fixed text: the classifier's own wording is never shown.
REFUSALS = {
    "artist_voice": (
        "I can't write songs that imitate a specific artist's voice or sound. Describe the style "
        "instead, for example “upbeat 80s synth-pop with a warm female vocal”."
    ),
    "existing_lyrics": (
        "I can't reproduce or closely rewrite existing song lyrics. I can write something new on "
        "the same theme."
    ),
    "disallowed_content": "I can't help with that request.",
}


def refusal_message(category: str) -> str:
    return REFUSALS.get(category, REFUSALS["disallowed_content"])


async def judge(caps: Capabilities, kind: str, text: str) -> Moderation:
    """Classify `text` (kind: "song request", "lyrics" or "cover art description")."""
    system = prompts.load("moderation")
    user = prompts.render("moderation_request", kind=kind, text=text)
    for attempt in range(1, ATTEMPTS + 1):
        raw = await caps.text.complete("moderate", system, user, schema=MODERATION_SCHEMA)
        try:
            verdict = Moderation.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError):
            log.warning("guardrail: unparseable verdict (attempt %d of %d)", attempt, ATTEMPTS)
            continue
        # A verdict that contradicts itself is a refusal: if it names a violation, keep that
        # category; if it refuses but says "ok", use the generic one.
        if verdict.allowed != (verdict.category == "ok"):
            log.warning("guardrail: inconsistent verdict (%s)", verdict.category)
            category = verdict.category if verdict.category != "ok" else "disallowed_content"
            return Moderation(allowed=False, category=category, reason=verdict.reason)
        return verdict
    raise RunError(
        "moderation_unavailable",
        "We couldn't check your request right now. Please try again.",
        retryable=True,
    )


async def enhance_guard(caps: Capabilities, kind: str, text: str, picture: bytes | None) -> None:
    """The Enhance button's guardrail (ADR-0038): the idea must pass before it is rewritten."""
    verdict = await judge(caps, "song request", text)
    if not verdict.allowed:
        raise EnhanceRefused(refusal_message(verdict.category))
