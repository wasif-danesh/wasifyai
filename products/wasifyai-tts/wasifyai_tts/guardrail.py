"""The mandatory guardrail (ADR-0042): every text passes it before any speech is made.

It fails closed: if the classifier cannot give a valid answer, the run stops with a retryable
error. It never defaults to "allowed". The text can be in any language; the moderator judges the
meaning."""

import json
import logging

from pydantic import ValidationError
from wasifyai_platform_sdk import Capabilities, RunError

from wasifyai_tts import prompts
from wasifyai_tts.schemas import MODERATION_SCHEMA, Moderation

log = logging.getLogger(__name__)

ATTEMPTS = 2

# What users see. Fixed text: the classifier's own wording is never shown.
REFUSALS = {
    "sexual_content": "I can't turn sexual content into speech.",
    "minors": "I can't help with text that sexualises children or puts them at risk.",
    "graphic_violence": "I can't read out graphic violence or threats.",
    "hate": "I can't read out text that demeans people or promotes hatred.",
    "fraud_or_impersonation": (
        "I can't make speech for scams or for messages that pretend to be someone else, such as a "
        "bank, an official or a named person."
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
        log.warning("speech guardrail: inconsistent verdict (%s)", verdict.category)
        category = verdict.category if verdict.category != "ok" else "disallowed_content"
        return Moderation(allowed=False, category=category, reason=verdict.reason)
    return verdict


async def judge_text(caps: Capabilities, text: str) -> Moderation:
    system = prompts.load("moderation")
    user = prompts.render("moderation_request", kind="text to read aloud", text=text)
    for attempt in range(1, ATTEMPTS + 1):
        raw = await caps.text.complete("moderate", system, user, schema=MODERATION_SCHEMA)
        if (verdict := _verdict(raw)) is not None:
            return verdict
        log.warning("speech guardrail: unparseable verdict (attempt %d of %d)", attempt, ATTEMPTS)
    raise RunError(
        "moderation_unavailable",
        "We couldn't check your text right now. Please try again.",
        retryable=True,
    )
