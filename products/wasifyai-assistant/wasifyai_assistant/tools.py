"""The assistant's tools (ADR-0057 decision 2).

Only the tools listed here exist: adding one is a code change that is reviewed, not a side effect
of a new capability appearing. Each tool acts through the platform's `ToolHost` for the user of the
run, and returns a small reference (an image id, search hits) plus a sentence for the model,
never a file."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from wasifyai_platform_sdk import ToolHost

SIZES = ("square", "landscape", "portrait", "wide", "tall")
IMAGE_PRODUCT = "wasifyai-image"
MAX_PROMPT = 500

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Make a new picture from a description and save it to the person's library. Use it "
                "when the person asks you to draw, paint, make or generate an image. Write the "
                "prompt as a clear, concrete description in English."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "What the picture shows."},
                    "size": {
                        "type": "string",
                        "enum": list(SIZES),
                        "description": "The shape of the picture. Default square.",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_creations",
            "description": (
                "Find things the person made earlier (images, songs, speech) by what they were "
                "about. Use it when they ask for something they made before."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to look for."}},
                "required": ["query"],
            },
        },
    },
]


@dataclass
class ToolOutcome:
    status: str  # ok, refused, error
    output: dict[str, Any] = field(default_factory=dict)  # for the window: a small reference
    text: str = ""  # for the model


Writer = Callable[[dict[str, Any]], None]


def parse_arguments(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def run_tool(
    name: str, arguments: dict[str, Any], host: ToolHost, write: Writer
) -> ToolOutcome:
    if name == "generate_image":
        return await _generate_image(arguments, host, write)
    if name == "search_creations":
        return await _search(arguments, host)
    return ToolOutcome("error", text=f"There is no tool called {name}.")


async def _generate_image(arguments: dict[str, Any], host: ToolHost, write: Writer) -> ToolOutcome:
    prompt = str(arguments.get("prompt", "")).strip()[:MAX_PROMPT]
    size = str(arguments.get("size", "square"))
    if not prompt:
        return ToolOutcome("error", text="The prompt was empty, so no image was made.")
    if size not in SIZES:
        size = "square"
    async for ev in host.run_product(
        IMAGE_PRODUCT, {"mode": "text", "prompt": prompt, "size": size}
    ):
        kind = ev.get("event")
        if kind == "job_progress":
            data = {
                k: ev[k]
                for k in (
                    "job_id",
                    "capability",
                    "status",
                    "queue_position",
                    "progress",
                    "preview_url",
                )
                if ev.get(k) is not None
            }
            write({"type": "job_progress", "data": data})
        elif kind == "error":
            return ToolOutcome(
                "error", text=f"The image could not be made: {ev.get('message', 'it failed')}."
            )
        elif kind == "done":
            out = ev.get("outputs") or {}
            if out.get("status") == "refused":
                reason = (out.get("refusal") or {}).get("message", "it was not allowed")
                return ToolOutcome(
                    "refused", {"message": reason}, f"The image was not made: {reason}"
                )
            if out.get("status") != "done" or not out.get("image_id"):
                return ToolOutcome("error", text="The image could not be made.")
            width, height = int(out.get("width", 0)), int(out.get("height", 0))
            return ToolOutcome(
                "ok",
                {
                    "image_id": out["image_id"], "product_id": IMAGE_PRODUCT, "prompt": prompt,
                    "width": width, "height": height,
                },
                f'The image was made ({width}x{height}) from "{prompt}" and saved to the '
                "library. The person can see it in the chat.",
            )  # fmt: skip
    return ToolOutcome("error", text="The image could not be made.")


async def _search(arguments: dict[str, Any], host: ToolHost) -> ToolOutcome:
    query = str(arguments.get("query", "")).strip()
    if not query:
        return ToolOutcome("error", text="There was nothing to search for.")
    hits = await host.search_creations(query, 6)
    if not hits:
        return ToolOutcome("ok", {"results": []}, "Nothing matched in the person's library.")
    lines = [f"- {h['kind']}: {h.get('text') or h['id']}" for h in hits]
    return ToolOutcome(
        "ok", {"results": hits}, f"Found {len(hits)} in the person's library:\n" + "\n".join(lines)
    )
