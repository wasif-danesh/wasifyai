"""The assistant's tools (ADR-0057 decision 2, ADR-0068).

Only the tools listed here exist: adding one is a code change that is reviewed, not a side effect
of a new capability appearing. Each tool is a catalogue action (`TOOL_ACTIONS`) run through the
platform's one executor, with the origin `assistant`, for the user of the run. It returns a small
reference (an image id, search hits) plus a sentence for the model, never a file.

The four definitions below are the ones the assistant has always shown the model (the tool-choice
evaluation measures exactly these); A2 replaces them with the meta-tools of ADR-0071."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from wasifyai_platform_sdk.actions import ActionExecutor, ActionResult, ApprovalPolicy

SIZES = ("square", "landscape", "portrait", "wide", "tall")
MAX_MUSIC_SECONDS = 120
MAX_PROMPT = 500
ORIGIN = "assistant"
# what the assistant did before the card of ADR-0071: it made things at once. A setting, not the
# default: the person who chose "ask first" will get the card in A2.
POLICY = ApprovalPolicy(make="auto")
# the tool the model sees -> the action that runs it
TOOL_ACTIONS = {
    "generate_image": "image.generate",
    "make_music": "music.generate",
    "search_creations": "library.search",
    "search_notebooks": "notebook.search",
}
# what the chat window shows beside a made thing
SEEN_IN_CHAT = {
    "generate_image": " The person can see it in the chat.",
    "make_music": " The person can play it in the chat.",
}
PROGRESS_KEYS = (
    "job_id", "capability", "status", "queue_position", "progress", "preview_url",
)  # fmt: skip

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
                "Find things the person made earlier (images, songs, speech, notebooks) by what "
                "they were about. It names the things it finds but does not read inside "
                "documents: to learn what their documents say, use search_notebooks."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to look for."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_music",
            "description": (
                "Make a piece of music or a song and save it to the person's library. Use it when "
                "the person asks you to compose, make or write music, a song or a tune. Describe "
                "the style in a few words in English (genre, mood, instruments). Add lyrics only "
                "if the person gave them or asked for a song with words."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "The style and mood."},
                    "lyrics": {"type": "string", "description": "The words to sing, if any."},
                    "instrumental": {"type": "boolean", "description": "No singing."},
                    "seconds": {
                        "type": "number",
                        "description": "Length in seconds. Default 30, at most 120.",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notebooks",
            "description": (
                "Look inside the person's notebooks (the documents, notes and pages they added as "
                "sources) for passages about a topic. Use it when they ask about something that "
                "may be in their own documents or notebooks. Answer only from the passages that "
                "are about the question, and say which notebook and source each came from."
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


def _text(arguments: dict[str, Any], key: str, limit: int) -> str:
    return str(arguments.get(key) or "").strip()[:limit]


def action_input(name: str, arguments: dict[str, Any]) -> dict[str, Any] | str:
    """A tool's arguments as the action takes them, mended as the assistant always mended them (cut
    to length, a wrong size becomes square), or the sentence that says why nothing can be done."""
    if name == "generate_image":
        prompt = _text(arguments, "prompt", MAX_PROMPT)
        if not prompt:
            return "The prompt was empty, so no image was made."
        size = str(arguments.get("size", "square"))
        return {"prompt": prompt, "size": size if size in SIZES else "square"}
    if name == "make_music":
        description = _text(arguments, "description", 500)
        if not description:
            return "The description was empty, so no music was made."
        out: dict[str, Any] = {"description": description}
        lyrics = _text(arguments, "lyrics", 5000)
        if lyrics:
            out["lyrics"] = lyrics
        elif arguments.get("instrumental"):
            out["instrumental"] = True
        try:
            seconds = float(arguments.get("seconds") or 30)
        except (TypeError, ValueError):
            seconds = 30.0
        out["seconds"] = max(5.0, min(float(MAX_MUSIC_SECONDS), seconds))
        return out
    query = _text(arguments, "query", 300 if name == "search_notebooks" else 200)
    return {"query": query} if query else "There was nothing to search for."


def outcome_of(name: str, result: ActionResult) -> ToolOutcome:
    """An action's result as the tool result the model and the window have always had."""
    if result.status == "ok":
        return ToolOutcome("ok", result.output, result.text + SEEN_IN_CHAT.get(name, ""))
    if name == "search_notebooks" and result.code == "unavailable":
        return ToolOutcome(
            "error", {"message": result.text}, f"Notebooks could not be searched: {result.text}"
        )
    if result.status == "refused":
        return ToolOutcome("refused", result.output or {"message": result.text}, result.text)
    return ToolOutcome("error", {}, result.text)  # error, needs_setup, needs_approval


async def run_tool(
    name: str,
    arguments: dict[str, Any],
    executor: ActionExecutor,
    write: Writer,
    tool_call_id: str | None = None,
) -> ToolOutcome:
    action_id = TOOL_ACTIONS.get(name)
    if action_id is None:
        return ToolOutcome("error", text=f"There is no tool called {name}.")
    params = action_input(name, arguments)
    if isinstance(params, str):
        return ToolOutcome("error", text=params)

    def progress(ev: dict[str, Any]) -> None:
        if ev.get("event") == "job_progress":
            data = {k: ev[k] for k in PROGRESS_KEYS if ev.get(k) is not None}
            if tool_call_id:  # two jobs in one turn each find their own card
                data["tool_call_id"] = tool_call_id
            write({"type": "job_progress", "data": data})

    result = await executor.run_action(action_id, params, ORIGIN, policy=POLICY, on_event=progress)
    return outcome_of(name, result)
