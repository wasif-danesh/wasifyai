# SPDX-License-Identifier: Apache-2.0
"""Moderation and daily limits for the voice product (ADR-0047). They run only while the
safeguards are on (`await caps.safeguards_on()`: off on the desktop, forced on in production).

Words that will be spoken or sung, lyrics and descriptions of music, and the words of a recording
that is made to talk go to the text moderator, which judges any language. A picture a face is taken
from goes to a model that can see it and refuses photographs of real people. Both fail closed: with
no valid answer the run stops with a retryable error. The daily limits count the usage events the
product records."""

import asyncio
import io
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Literal

from PIL import Image as PILImage
from pydantic import BaseModel, ValidationError
from wasifyai_platform_sdk import (
    Capabilities,
    Image,
    RunError,
    require_context,
    start_of_day_utc,
    sum_usage,
)

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).with_name("prompts")
ATTEMPTS = 2
REVIEW_PX = 768
CHUNK_CHARS = 6000  # a long text is judged in pieces, so one verdict never has to read a book
CONCURRENCY = 3

WORD_CATEGORIES = [
    "ok",
    "sexual_content",
    "minors",
    "graphic_violence",
    "hate",
    "fraud_or_impersonation",
    "disallowed_content",
]
PICTURE_CATEGORIES = [
    "ok",
    "sexual_content",
    "minors",
    "graphic_violence",
    "hate",
    "real_person_photo",
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


class PictureVerdict(BaseModel):
    allowed: bool
    category: Literal[
        "ok",
        "sexual_content",
        "minors",
        "graphic_violence",
        "hate",
        "real_person_photo",
        "disallowed_content",
    ]
    reason: str = ""


def _schema(categories: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "allowed": {"type": "boolean"},
            "category": {"type": "string", "enum": categories},
            "reason": {"type": "string"},
        },
        "required": ["allowed", "category", "reason"],
        "additionalProperties": False,
    }


WORDS_SCHEMA = _schema(WORD_CATEGORIES)
PICTURE_SCHEMA = _schema(PICTURE_CATEGORIES)

# What users see. Fixed text: the classifier's own wording is never shown.
WORD_REFUSALS = {
    "sexual_content": "I can't turn sexual content into speech or music.",
    "minors": "I can't help with text that sexualises children or puts them at risk.",
    "graphic_violence": "I can't read out or sing graphic violence or threats.",
    "hate": "I can't read out or sing text that demeans people or promotes hatred.",
    "fraud_or_impersonation": (
        "I can't make speech for scams or for messages that pretend to be someone else, such as a "
        "bank, an official or a named person."
    ),
    "disallowed_content": "I can't help with that request.",
}
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


def words_refusal(category: str) -> str:
    return WORD_REFUSALS.get(category, WORD_REFUSALS["disallowed_content"])


def picture_refusal(category: str) -> str:
    return PICTURE_REFUSALS.get(category, PICTURE_REFUSALS["disallowed_content"])


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def render_prompt(name: str, **values: str) -> str:
    return Template(load_prompt(name)).safe_substitute(**values)


def _verdict(raw: str, model: type[BaseModel]) -> Any:
    try:
        verdict = model.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        return None
    # a verdict that contradicts itself is a refusal: keep the violation it names if it names one
    if verdict.allowed != (verdict.category == "ok"):  # type: ignore[attr-defined]
        log.warning("voice guardrail: inconsistent verdict (%s)", verdict.category)  # type: ignore[attr-defined]
        category = verdict.category if verdict.category != "ok" else "disallowed_content"  # type: ignore[attr-defined]
        return model(allowed=False, category=category, reason=verdict.reason)  # type: ignore[attr-defined]
    return verdict


async def judge_text(caps: Capabilities, text: str, kind: str = "text to read aloud") -> Moderation:
    system = load_prompt("moderation")
    user = render_prompt("moderation_request", kind=kind, text=text)
    for attempt in range(1, ATTEMPTS + 1):
        raw = await caps.text.complete("moderate", system, user, schema=WORDS_SCHEMA)
        if (verdict := _verdict(raw, Moderation)) is not None:
            return verdict  # type: ignore[no-any-return]
        log.warning("voice guardrail: unparseable verdict (attempt %d of %d)", attempt, ATTEMPTS)
    raise RunError(
        "moderation_unavailable",
        "We couldn't check your text right now. Please try again.",
        retryable=True,
    )


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
    user = [load_prompt("moderation_picture_request"), Image.from_bytes(small, "image/jpeg")]
    system = load_prompt("moderation_picture")
    for attempt in range(1, ATTEMPTS + 1):
        raw = await caps.text.complete("moderate_image", system, user, schema=PICTURE_SCHEMA)
        if (verdict := _verdict(raw, PictureVerdict)) is not None:
            return verdict  # type: ignore[no-any-return]
        log.warning("voice guardrail: unparseable verdict (attempt %d of %d)", attempt, ATTEMPTS)
    raise RunError(
        "moderation_unavailable",
        "We couldn't check your picture right now. Please try again.",
        retryable=True,
    )


def pieces(text: str) -> list[str]:
    """The text cut into pieces of at most CHUNK_CHARS, at line or sentence ends where it can."""
    text = text.strip()
    if len(text) <= CHUNK_CHARS:
        return [text] if text else []
    out: list[str] = []
    while text:
        if len(text) <= CHUNK_CHARS:
            out.append(text)
            break
        cut = max(
            text.rfind("\n", 0, CHUNK_CHARS),
            *(m.end() for m in re.finditer(r"[.!?。]\s", text[:CHUNK_CHARS])),
        )
        cut = cut if cut > CHUNK_CHARS // 2 else CHUNK_CHARS
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    return [p for p in out if p]


# What the daily limits count, each a usage event the product records and a key in `quotas:`
@dataclass(frozen=True)
class Meter:
    event: str
    quota: str
    noun: str


SPEECHES = Meter("voice.speech", "speeches_per_user_per_day", "speeches")
SONGS = Meter("voice.music", "songs_per_user_per_day", "pieces of music")
CLIPS = Meter("voice.lipsync", "lipsyncs_per_user_per_day", "lip sync videos")
TOOLS = Meter("voice.tool", "tools_per_user_per_day", "runs of the audio tools")
DUBS = Meter("voice.dub", "dubs_per_user_per_day", "dubs")
BOOKS = Meter(
    "voice.audiobook", "audiobook_characters_per_user_per_day", "characters of audiobook text"
)

Refusal = tuple[str, str]  # (code, the sentence the person sees)


class Guard:
    """What a graph asks before it does work; each method does nothing while safeguards are off."""

    def __init__(self, caps: Capabilities):
        self.caps = caps

    async def on(self) -> bool:
        return await self.caps.safeguards_on()

    # ---- daily limits ------------------------------------------------------------------------

    async def _used(self, meter: Meter) -> int:
        override: Callable[[Meter], Awaitable[int]] | None = self.caps.extras.get("quota_used")
        if override is not None:  # tests, and deployments that count somewhere else
            return await override(meter)
        if self.caps.db is None:
            return 0
        ctx = require_context()
        return int(
            await sum_usage(
                self.caps.db,
                ctx.tenant_id,
                ctx.product_id,
                ctx.user_id,
                meter.event,
                start_of_day_utc(),
            )  # fmt: skip
        )

    async def over_limit(self, meter: Meter, adding: int = 1) -> Refusal | None:
        """A refusal when `adding` more would pass today's limit (one more thing by default)."""
        if not await self.on():
            return None
        limit = (self.caps.config.quotas.get(meter.quota) if self.caps.config else None) or None
        if limit and await self._used(meter) + max(adding, 1) > limit:
            return (
                "quota_exceeded",
                f"You've reached today's limit of {limit} {meter.noun}. Please try again tomorrow.",
            )
        return None

    # ---- words and pictures ------------------------------------------------------------------

    async def words(self, *texts: str, kind: str = "text to read aloud") -> Refusal | None:
        """A refusal for the first text the moderator will not allow, else None."""
        if not await self.on():
            return None
        # the texts of one request are judged together (they are one piece of work), cut when long
        parts = pieces("\n\n".join(str(t).strip() for t in texts if str(t).strip()))
        gate = asyncio.Semaphore(CONCURRENCY)

        async def one(part: str) -> Moderation:
            async with gate:
                return await judge_text(self.caps, part, kind)

        for verdict in await asyncio.gather(*(one(p) for p in parts)):
            if not verdict.allowed:
                return (verdict.category, words_refusal(verdict.category))
        return None

    async def picture(self, data: bytes) -> Refusal | None:
        if not await self.on():
            return None
        verdict = await judge_picture(self.caps, data)
        if not verdict.allowed:
            return (verdict.category, picture_refusal(verdict.category))
        return None


def metered(
    caps: Capabilities,
    guard: Guard,
    refuse_with: Callable[[str, str], dict[str, Any]],
    meter: Meter,
    node: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    amount: Callable[[dict[str, Any]], int] = lambda state: 1,
    unit: str = "runs",
    count: bool = True,
    **meta: Any,
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """A graph node held to a daily limit: refused before any work when `amount(state)` more would
    pass the limit, and counted (as `amount` of `unit`, unless `count` is false) once it has made
    something."""

    async def run(state: dict[str, Any]) -> dict[str, Any]:
        wanted = amount(state)
        if refusal := await guard.over_limit(meter, wanted):
            return refuse_with(*refusal)
        out = await node(state)
        if count and out.get("status") == "done":
            await caps.record_usage(meter.event, wanted, unit, **meta)
        return out

    return run
