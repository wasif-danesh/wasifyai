"""A model's prompt writer (ADR-0097): some models read a structured caption, not a sentence.

Ideogram 4 draws a refusal card for a plain sentence and a good picture for its JSON caption,
which its own service writes with a text model first. A model in product.yaml names its writer in
`settings` (`prompt_writer: <prompt file>`); the graph runs the person's words through
`text.enhance` with that prompt and sends the caption as the job's prompt. The person's own words
stay the picture's prompt.
"""

from __future__ import annotations

import json
import re
from math import log
from typing import Any

from wasifyai_platform_sdk.enhance import strip_thinking

from wasifyai_image import prompts

MAX_ELEMENTS = 8


RATIOS = ("1:1", "5:4", "4:5", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "21:9", "9:21")


def aspect_ratio(width: int, height: int) -> str:
    """The common shape nearest to the picture's (1344 x 768 is "16:9", not "7:4")."""
    want = log(width / height)
    return min(RATIOS, key=lambda r: abs(log(int(r.split(":")[0]) / int(r.split(":")[1])) - want))


def _first_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in the reply: models wrap it in a fence or a sentence now and then."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start : i + 1])
                    except ValueError:
                        break
                    return value if isinstance(value, dict) else None
        start = text.find("{", start + 1)
    return None


def _box(raw: object) -> list[int] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        top, left, bottom, right = (max(0, min(1000, round(float(v)))) for v in raw)
    except (TypeError, ValueError):
        return None
    if bottom <= top or right <= left:
        return None
    return [top, left, bottom, right]


def caption_of(reply: str, ratio: str) -> str | None:
    """The model's reply as the caption the image model reads, or None when it is not one."""
    raw = _first_object(strip_thinking(reply))
    if raw is None:
        return None
    summary = raw.get("high_level_description")
    parts = raw.get("compositional_deconstruction")
    if not isinstance(summary, str) or not summary.strip() or not isinstance(parts, dict):
        return None
    elements: list[dict[str, Any]] = []
    for e in parts.get("elements") or []:
        if not isinstance(e, dict) or len(elements) == MAX_ELEMENTS:
            continue
        kind, box, desc = e.get("type"), _box(e.get("bbox")), e.get("desc")
        if kind not in ("obj", "text") or box is None or not isinstance(desc, str):
            continue
        item: dict[str, Any] = {"type": kind, "bbox": box, "desc": desc.strip()}
        if kind == "text":
            words = e.get("text")
            if not isinstance(words, str) or not words.strip():
                continue
            item["text"] = words.strip()
        elements.append(item)
    if not elements:
        return None
    background = parts.get("background")
    caption = {
        "aspect_ratio": ratio,
        "high_level_description": re.sub(r"\s+", " ", summary).strip(),
        "compositional_deconstruction": {
            "background": background.strip() if isinstance(background, str) else "",
            "elements": elements,
        },
    }
    return json.dumps(caption, ensure_ascii=False)


async def write_caption(caps: Any, writer: str, prompt: str, width: int, height: int) -> str | None:
    """The caption for `prompt` from the writer prompt `writer` (a file in prompts/), or None."""
    ratio = aspect_ratio(width, height)
    system = prompts.render(writer, aspect_ratio=ratio)
    for _ in range(2):  # a small model now and then answers with something else; one more try
        reply = await caps.text.complete("enhance", system, f"<user_text>\n{prompt}\n</user_text>")
        caption = caption_of(reply, ratio)
        if caption is not None:
            return caption
    return None
