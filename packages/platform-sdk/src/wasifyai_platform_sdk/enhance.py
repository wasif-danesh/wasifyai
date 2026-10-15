"""Prompt enhancement (ADR-0038): rewrite what a user typed into a better prompt for the model.

A product mounts `build_enhance_router(...)` from its own routes. The platform stays generic: the
product says which kinds it has (product.yaml `enhance:`), loads the enhancer instructions from its
own prompts, and supplies the guardrail that must pass on the user's text (and picture) first.

The user's text is data inside a fixed prompt, never instructions, and the result is only text for
the prompt box: the run's own guardrail judges the final prompt again when it is submitted."""

import asyncio
import io
import logging
import re
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from PIL import Image as PILImage
from pydantic import BaseModel, Field

from wasifyai_platform_sdk.capabilities import Capabilities
from wasifyai_platform_sdk.errors import RunError
from wasifyai_platform_sdk.parts import Image
from wasifyai_platform_sdk.routes import RouteDeps
from wasifyai_platform_sdk.uploads import UploadLimiter

log = logging.getLogger(__name__)

TIMEOUT_S = 25
ENHANCED = "prompt.enhanced"
REVIEW_PX = 768
DESCRIBE_SYSTEM = (
    "You describe pictures for someone writing a prompt for a video or image model. In one or two "
    "plain sentences say what the picture shows: the subject, the setting, the colours and the "
    "light. No opinions, no guesses about who anyone is, and no names of real people."
)


class EnhanceRefused(Exception):
    """The guardrail refused the user's text or picture; `message` is the fixed text to show."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# (capabilities, kind, the user's text, their picture as stored or None); raises EnhanceRefused
Guard = Callable[[Capabilities, str, str, bytes | None], Awaitable[None]]


class EnhanceIn(BaseModel):
    kind: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    prompt: str = Field(min_length=1, max_length=4000)
    upload_id: str | None = None


class EnhanceOut(BaseModel):
    prompt: str
    changed: bool


_FENCE = re.compile(r"^```[a-z]*\n?|\n?```$", re.IGNORECASE)
_LEAD = re.compile(
    r"^\s*(?:here(?:'s| is)[^\n:]*:|(?:enhanced|improved|rewritten|new|final)?\s*prompt\s*:)\s*",
    re.IGNORECASE,
)


_THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_WORKING = re.compile(
    r"^\W*(?:we need to|we have|we are|we should|the user|let'?s |let me |okay[,.]|ok[,.]|hmm|"
    r"alright|first,|so the user|i need to|i should|i will|the task|the instruction)",
    re.IGNORECASE,
)


def strip_thinking(text: str) -> str:
    """Take out a reasoning model's `<think>` block, which some servers leave in the answer."""
    out = _THINK.sub("", text)
    if "</think>" in out.lower():  # an opening tag the server consumed
        out = re.split(r"</think>", out, flags=re.IGNORECASE)[-1]
    return out.strip()


def looks_like_working(text: str) -> bool:
    """Does this read like the model thinking aloud ("We need to rewrite...") instead of a prompt?
    A model without its chat template does this; pasting it into the prompt box would be wrong."""
    return bool(_WORKING.match(text.strip())) or "The user says" in text[:300]


def clean_output(text: str, limit: int) -> str:
    """The model's reply as a bare prompt: no fences, quotes, markdown or "Here is your prompt:",
    cut at a sentence boundary if it is over `limit`."""
    out = _FENCE.sub("", text.strip()).strip()
    out = _LEAD.sub("", out).strip()
    out = re.sub(r"[*_#`]+", "", out)
    if len(out) >= 2 and out[0] in "\"'“‘" and out[-1] in "\"'”’":
        out = out[1:-1].strip()
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{2,}", "\n", out).strip()
    if len(out) > limit:
        cut = out[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind(".\n"))
        out = cut[: end + 1] if end >= limit // 2 else cut.rsplit(" ", 1)[0]
    return out.strip()


def review_jpeg(png: bytes, px: int = REVIEW_PX) -> bytes:
    """A small JPEG of the picture: the model needs a look at it, not every pixel."""
    with PILImage.open(io.BytesIO(png)) as im:
        rgb = im.convert("RGB")
    rgb.thumbnail((px, px))
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=85)
    return out.getvalue()


def build_enhance_router(
    deps: RouteDeps,
    product_id: str,
    load_prompt: Callable[[str], str],
    guard: Guard,
    limiter_name: str = "enhance",
) -> APIRouter:
    router = APIRouter(tags=[product_id])

    @router.post("/prompt/enhance", response_model=EnhanceOut)
    async def enhance(
        body: EnhanceIn, request: Request, identity=Depends(deps.identity)
    ) -> EnhanceOut:
        state = deps.state
        caps: Capabilities = state.caps[product_id]
        rule = caps.config.enhance.get(body.kind) if caps.config else None
        if rule is None:
            raise HTTPException(422, "That kind of prompt can't be enhanced here.")
        text = body.prompt.strip()
        if not text:
            raise HTTPException(422, "Please type something first.")
        if len(text) > rule.max_chars:
            raise HTTPException(422, f"Please keep it under {rule.max_chars} characters.")
        limiter: UploadLimiter = state.enhance_limiter
        if not await limiter.allow(identity.tenant_id, identity.user_id):
            raise HTTPException(429, "You've enhanced a lot of prompts. Please wait a while.")

        with deps.acting_as(identity, product_id):
            picture = await _picture(deps, product_id, identity, body, rule.needs_picture)
            try:
                async with asyncio.timeout(TIMEOUT_S):
                    await guard(caps, body.kind, text, picture)
                    result = await _rewrite(caps, load_prompt(rule.prompt), text, picture)
            except EnhanceRefused as exc:
                raise HTTPException(422, exc.message) from None
            except RunError as exc:
                raise HTTPException(503, exc.message) from None
            except TimeoutError:
                raise HTTPException(
                    503, "Enhancing is taking too long. Please try again in a moment."
                ) from None
            except Exception:
                log.exception("prompt enhancement failed", extra={"kind": body.kind})
                raise HTTPException(
                    503, "We couldn't enhance your prompt right now. Please try again."
                ) from None
            result = strip_thinking(result)
            if looks_like_working(result):
                raise HTTPException(
                    503,
                    "The model answered with its working instead of a prompt. Try again, or "
                    "choose another model in Models.",
                )
            cleaned = clean_output(result, rule.max_chars)
            await caps.record_usage(ENHANCED, 1, "prompts", prompt_kind=body.kind)
        if not cleaned or cleaned == text:
            return EnhanceOut(prompt=text, changed=False)
        return EnhanceOut(prompt=cleaned, changed=True)

    return router


async def _picture(deps: RouteDeps, product_id: str, identity, body: EnhanceIn, needed: bool):
    """The caller's own unused upload for this request, or None when the kind needs none."""
    if not needed:
        return None
    if not body.upload_id:
        raise HTTPException(422, "Please choose a picture first.")
    try:
        key = f"uploads/{UUID(body.upload_id)}.png"
    except ValueError:
        raise HTTPException(422, "Please upload your picture again.") from None
    record = await deps.state.uploads.find(identity.tenant_id, product_id, identity.user_id, key)
    if record is None or deps.storage is None:
        raise HTTPException(422, "Please upload your picture again.")
    try:
        return await deps.storage.get(key)
    except FileNotFoundError:
        raise HTTPException(422, "Please upload your picture again.") from None


async def _rewrite(caps: Capabilities, system: str, text: str, picture: bytes | None) -> str:
    if picture is None:
        user = f"<user_text>\n{text}\n</user_text>"
    else:
        jpeg = await asyncio.to_thread(review_jpeg, picture)
        description = await caps.text.complete(
            "describe_image",
            DESCRIBE_SYSTEM,
            ["Describe this picture.", Image.from_bytes(jpeg, "image/jpeg")],
        )
        user = (
            f"<picture_description>\n{description.strip()}\n</picture_description>\n"
            f"<user_text>\n{text}\n</user_text>"
        )
    return await caps.text.complete("enhance", system, user)
