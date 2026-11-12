"""An area of a picture named in words ("the sky", "his shirt"), found by the model that reads
pictures (docs/chat-does-everything-plan.md, CE6), so Change part of a picture works from the chat
without drawing. The box is a little larger than what was found: an inpainted area needs room to
blend in. The words are data inside a fixed prompt, never instructions."""

import asyncio
import io
import json
import re
from typing import Any

from PIL import Image as PILImage
from wasifyai_platform_sdk.parts import Image
from wasifyai_platform_sdk.route_usage import RouteUsage

PRODUCT_ID = "wasifyai-image"
REVIEW_PX = 768
PAD = 0.04  # added on each side, as a share of the picture
SYSTEM = (
    "You find one thing in a picture. The person names it between <area> tags. Answer with JSON "
    'only: {"found": true, "box": [x1, y1, x2, y2]}, the smallest box around all of it, with '
    "coordinates from 0 to 1000 (0,0 is the top left corner, 1000,1000 the bottom right). If it "
    'is not in the picture, answer {"found": false}.'
)
_JSON = re.compile(r"\{.*\}", re.DOTALL)
_THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def caps_of(state: Any) -> Any:
    """The image product's capabilities (the model that reads pictures), or None."""
    return RouteUsage(state, PRODUCT_ID).caps


def review_copy(png: bytes) -> bytes:
    with PILImage.open(io.BytesIO(png)) as im:
        rgb = im.convert("RGB")
    rgb.thumbnail((REVIEW_PX, REVIEW_PX))
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=85)
    return out.getvalue()


def region_of(reply: str) -> dict[str, float] | None:
    """The region a reply names, as shares of the picture, padded and kept on it; None when the
    reply says it is not there or cannot be read. Coordinates from 0 to 1 are taken as shares."""
    m = _JSON.search(_THINK.sub("", reply or ""))
    if m is None:
        return None
    try:
        got = json.loads(m.group(0))
        box = [float(v) for v in got.get("box") or []]
    except (ValueError, TypeError, AttributeError):
        return None
    if got.get("found") is False or len(box) != 4:
        return None
    scale = 1.0 if max(box) <= 1.0 else 1000.0
    x1, y1, x2, y2 = (min(max(v / scale, 0.0), 1.0) for v in box)
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    if x2 - x1 < 0.01 or y2 - y1 < 0.01:
        return None
    x1, y1 = max(0.0, x1 - PAD), max(0.0, y1 - PAD)
    x2, y2 = min(1.0, x2 + PAD), min(1.0, y2 + PAD)
    return {
        "left": round(x1, 3), "top": round(y1, 3),
        "width": round(x2 - x1, 3), "height": round(y2 - y1, 3),
    }  # fmt: skip


async def find_area(caps: Any, png: bytes, words: str) -> dict[str, float] | None:
    """Where `words` is in the picture, or None. Raises what the model raises."""
    small = await asyncio.to_thread(review_copy, png)
    said = words.replace("<", " ").replace(">", " ").strip()[:200]
    user = [f"<area>{said}</area>", Image.from_bytes(small, "image/jpeg")]
    return region_of(await caps.text.complete("describe_image", SYSTEM, user))
