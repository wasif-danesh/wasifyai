"""A skill file for Claude Code (ADR-0069 stage M3): instructions that tell an agent how to use
the app well through the MCP server, generated from the catalogue so they are never stale. It
does not replace the server (a skill is words, not a connection); it is copied from Settings."""

from collections.abc import Iterable

from wasifyai_platform_sdk.actions import Action, ActionRegistry, scope_of

from wasifyai_api.mcp_server.tools import tool_name

GROUP_TITLES = {
    "make": "Making things",
    "models": "Models on this computer",
    "read": "Reading the app's state",
    "library": "The person's library (private)",
    "notebooks": "The person's notebooks (private)",
    "voices": "The person's voices",
}


def skill_markdown(registry: ActionRegistry, scopes: Iterable[str]) -> str:
    allowed = set(scopes) | {"read"}
    by_group: dict[str, list[Action]] = {}
    for action in registry.for_surface("mcp"):
        group = scope_of(action)
        if group in allowed:
            by_group.setdefault(group, []).append(action)
    lines = [
        "---",
        "name: wasify-ai",
        "description: Make pictures, videos, speech and music with Wasify AI on this computer, "
        "and read what it made. Use when the person asks to create media or wants something from "
        "their Wasify AI library.",
        "---",
        "",
        "# Wasify AI",
        "",
        "Wasify AI runs on the person's own computer and is reachable as the MCP server `wasify`. "
        "Every tool is one thing the app can do; the app enforces what each tool may do, not the "
        "tool's description.",
        "",
        "## How calls behave",
        "",
        "- A tool that takes a while answers `status: running` with a `job_id` after about 25 "
        "seconds. Follow it with `job_wait` (up to 50 seconds a call) or `job_status`; do not "
        "call the tool again.",
        "- A connection runs one job at a time. `busy` means: wait for the job named, then retry.",
        "- Deleting, copying a voice, downloading a model and anything the person set to ask "
        "first are approved in the Wasify AI window, never here. A `needs_approval` answer "
        "carries an `approval_id`: tell the person to look at the app, then follow it with "
        "`approval_status` (it can wait up to 50 seconds). Never claim something was made before "
        "the status says so.",
        "- Results name creations by id and kind; files stay in the app. To get a file out, call "
        "`library_export` with a folder the connection may write to; to give the app a file, name "
        "a path under a folder it may read.",
        "- `app_status` says which tools are ready on this computer and what is missing; call it "
        "before telling the person something cannot be done.",
        "",
    ]
    for group in ("make", "models", "read", "library", "notebooks", "voices"):
        actions = by_group.get(group)
        if not actions:
            continue
        lines.append(f"## {GROUP_TITLES[group]}")
        lines.append("")
        for a in sorted(actions, key=lambda x: x.id):
            flags = []
            if a.long:
                flags.append("takes a while")
            if "needs_consent" in a.flags or a.effect == "destroy":
                flags.append("asks the person in the app")
            if "leaves_device" in a.flags:
                flags.append("leaves this computer")
            note = f" ({'; '.join(flags)})" if flags else ""
            lines.append(f"- `{tool_name(a.id)}`: {a.summary.rstrip('.')}{note}.")
        lines.append("")
    lines += [
        "## Examples",
        "",
        '- "Make a picture of a red teapot": `image_generate` with the prompt, then `job_wait` '
        "with the job_id it returns.",
        '- "Say hello in a calm voice": `speech_speak` with the text; if it answers '
        "`needs_setup`, tell the person the step it names (a speech model to get).",
        '- "Which models are here?": `models_list`.',
        "",
    ]
    return "\n".join(lines)
