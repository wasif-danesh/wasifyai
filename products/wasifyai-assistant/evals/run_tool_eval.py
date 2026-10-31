"""Run the assistant's evaluation cases against a model (ADR-0057; ADR-0071 decision 8, stage A3).

    uv run python products/wasifyai-assistant/evals/run_tool_eval.py \\
        --gguf /path/model.gguf --data-dir <the app data folder with the language engine>
    uv run python products/wasifyai-assistant/evals/run_tool_eval.py \\
        --base-url http://127.0.0.1:11434/v1 --model qwen3:4b

Each case is sent with the assistant's own system prompt and tool definitions. A `tool` case ends
at the model's first answer (the right tool, usable arguments, or words when no tool is wanted).
A `guide`, `status` or `safety` case goes on: the tools the model called are answered the way the
app answers them (`how_to` and `app_status` for real, from the shipped help corpus; searches and
the web from the case's script; a proposal stops at the card), and the final answer is judged.
A case with `extra_tools` is sent that many extra, unrelated tools (the remote tools of ADR-0070)
to see whether the choice still holds.
An `editor` case (ADR-0096, MX3) is sent what the Motion graphics
editor's assistant is sent, and is judged on the change it proposes, applied to the project for
real. A `remote` case (stage C2) connects a catalogue of
`remote_tools` outside tools (5 or 40) behind `external_tools`, as decision 8 of ADR-0070 has it,
and is judged on the `call_external` the model reaches: the right server and tool, arguments that
fit the tool's schema. One JSON line per case, then a summary per kind and per catalogue size.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import yaml
from wasifyai_api.mcp_client.client import ToolInfo, rank_tools
from wasifyai_assistant import help as guides
from wasifyai_assistant.features import actions_prompt, where_of
from wasifyai_assistant.graph import SYSTEM_PROMPT, external_prompt
from wasifyai_assistant.tools import TOOL_DEFINITIONS, how_to, signature_of
from wasifyai_platform_sdk.actions import Readiness

CASES = Path(__file__).with_name("cases.yaml")
SIZES = ("square", "landscape", "portrait", "wide", "tall")
SERVED = {g.action for g in guides.guides()}
# what the assistant is really sent on the desktop: its prompt and the list of actions it may
# propose; since stage C1 the outside-tools pair is always offered there, so the prompt also names
# the connected servers (`prompt_for`)
PROMPT = SYSTEM_PROMPT + actions_prompt(SERVED)
DEFAULT_REMOTE = 5  # the catalogue behind external_tools when a case does not say
MAX_ROUNDS = 4
LOOKUPS = (
    "how_to",
    "app_status",
)  # reads of the app's own files and state: never wrong, only slower
# the kinds, and whether the case goes on after the first answer
KINDS = ("tool", "guide", "status", "safety", "remote", "editor")

# the outside servers' tools (ADR-0070): server, name, arguments (name: type), required,
# what it does
# The first five are the ones the remote cases want (so a catalogue of 5 holds them); the rest are
# what a real set of servers brings.
REMOTE_TOOLS: list[tuple[str, str, dict[str, str], list[str], str]] = [
    (
        "github",
        "search_issues",
        {"query": "string", "repo": "string"},
        ["query"],
        "Search issues and pull requests in the person's GitHub repositories by words.",
    ),
    (
        "files",
        "read_file",
        {"path": "string"},
        ["path"],
        "Read a text file under the shared folder, by its path.",
    ),
    (
        "slack",
        "send_message",
        {"channel": "string", "text": "string"},
        ["channel", "text"],
        "Post a message to a Slack channel.",
    ),
    ("weather", "current", {"city": "string"}, ["city"], "The weather right now in a city."),
    (
        "jira",
        "search_tickets",
        {"query": "string", "project": "string"},
        ["query"],
        "Find Jira tickets by words in their title or description.",
    ),
    (
        "github",
        "create_issue",
        {"repo": "string", "title": "string", "body": "string"},
        ["repo", "title"],
        "Open a new issue in a GitHub repository.",
    ),
    (
        "github",
        "list_pull_requests",
        {"repo": "string"},
        ["repo"],
        "List the open pull requests of a repository.",
    ),
    (
        "calendar",
        "add_event",
        {"title": "string", "when": "string"},
        ["title", "when"],
        "Add an event to the person's calendar.",
    ),
    (
        "db",
        "run_query",
        {"sql": "string"},
        ["sql"],
        "Run a read-only SQL query on the orders database.",
    ),
    (
        "notion",
        "search_pages",
        {"query": "string"},
        ["query"],
        "Search the person's Notion pages by words.",
    ),
    (
        "github",
        "get_issue",
        {"repo": "string", "number": "integer"},
        ["repo", "number"],
        "One issue by number, with its comments.",
    ),
    (
        "github",
        "add_comment",
        {"repo": "string", "number": "integer", "body": "string"},
        ["repo", "number", "body"],
        "Comment on an issue or pull request.",
    ),
    ("github", "list_repositories", {}, [], "The repositories the person can see."),
    (
        "github",
        "get_file",
        {"repo": "string", "path": "string", "ref": "string"},
        ["repo", "path"],
        "A file from a repository at a branch.",
    ),
    (
        "github",
        "list_commits",
        {"repo": "string", "since": "string"},
        ["repo"],
        "Recent commits of a repository.",
    ),
    (
        "files",
        "list_directory",
        {"path": "string"},
        ["path"],
        "The files in a folder under the shared folder.",
    ),
    (
        "files",
        "write_file",
        {"path": "string", "content": "string"},
        ["path", "content"],
        "Write a text file under the shared folder.",
    ),
    (
        "files",
        "search_files",
        {"pattern": "string"},
        ["pattern"],
        "Find files under the shared folder by name.",
    ),
    (
        "files",
        "move_file",
        {"source": "string", "destination": "string"},
        ["source", "destination"],
        "Move or rename a file under the shared folder.",
    ),
    ("slack", "list_channels", {}, [], "The channels of the workspace."),
    (
        "slack",
        "read_channel",
        {"channel": "string", "limit": "integer"},
        ["channel"],
        "The last messages of a channel.",
    ),
    (
        "slack",
        "add_reaction",
        {"channel": "string", "timestamp": "string", "emoji": "string"},
        ["channel", "timestamp", "emoji"],
        "React to a message with an emoji.",
    ),
    (
        "jira",
        "create_ticket",
        {"project": "string", "summary": "string", "description": "string"},
        ["project", "summary"],
        "Create a Jira ticket.",
    ),
    (
        "jira",
        "transition_ticket",
        {"key": "string", "status": "string"},
        ["key", "status"],
        "Move a ticket to another status.",
    ),
    ("jira", "get_ticket", {"key": "string"}, ["key"], "One ticket by key."),
    (
        "weather",
        "forecast",
        {"city": "string", "days": "integer"},
        ["city"],
        "The forecast for the next days in a city.",
    ),
    (
        "weather",
        "alerts",
        {"region": "string"},
        ["region"],
        "Weather warnings in force for a region.",
    ),
    (
        "calendar",
        "list_events",
        {"from": "string", "to": "string"},
        ["from", "to"],
        "The events between two dates.",
    ),
    (
        "calendar",
        "find_free_time",
        {"minutes": "integer", "day": "string"},
        ["minutes"],
        "Free slots for a meeting of a length.",
    ),
    ("db", "list_tables", {}, [], "The tables of the orders database."),
    ("db", "describe_table", {"table": "string"}, ["table"], "The columns of a table."),
    ("notion", "get_page", {"page_id": "string"}, ["page_id"], "One Notion page by id, as text."),
    (
        "notion",
        "create_page",
        {"parent_id": "string", "title": "string", "content": "string"},
        ["parent_id", "title"],
        "A new Notion page under a parent.",
    ),
    ("stocks", "quote", {"ticker": "string"}, ["ticker"], "The latest price of a ticker."),
    (
        "stocks",
        "history",
        {"ticker": "string", "days": "integer"},
        ["ticker"],
        "Daily prices of a ticker over a period.",
    ),
    (
        "mail",
        "search_mail",
        {"query": "string"},
        ["query"],
        "Search the person's mailbox by words.",
    ),
    (
        "mail",
        "send_mail",
        {"to": "string", "subject": "string", "body": "string"},
        ["to", "subject", "body"],
        "Send an email.",
    ),
    (
        "maps",
        "directions",
        {"origin": "string", "destination": "string"},
        ["origin", "destination"],
        "Directions between two places.",
    ),
    (
        "maps",
        "places_nearby",
        {"kind": "string", "near": "string"},
        ["kind", "near"],
        "Places of a kind near an address.",
    ),
    (
        "translate",
        "translate_text",
        {"text": "string", "to": "string"},
        ["text", "to"],
        "Translate text into a language.",
    ),
]


def remote_catalogue(n: int) -> list[ToolInfo]:
    """The first `n` outside tools, as the client would list them (the reads say so in their
    annotations)."""
    out = []
    for server, name, props, required, description in REMOTE_TOOLS[:n]:
        reads = name.split("_")[0] in ("search", "list", "read", "get", "current", "forecast",
                                       "quote", "history", "describe", "find", "directions",
                                       "places", "alerts")  # fmt: skip
        out.append(
            ToolInfo(
                server=server,
                name=name,
                description=description,
                input_schema={
                    "type": "object",
                    "properties": {k: {"type": v} for k, v in props.items()},
                    "required": required,
                },
                annotations={"readOnlyHint": True} if reads else {},
            )  # fmt: skip
        )
    return out


def remote_size(case: dict) -> int:
    return int(case.get("remote_tools") or DEFAULT_REMOTE)


def prompt_for(case: dict) -> str:
    """The system prompt of a case: the assistant's own, with the outside servers of its
    catalogue named, as the desktop names the ones the person connected."""
    names = sorted({t.server for t in remote_catalogue(remote_size(case))})
    return PROMPT + external_prompt(names)


def judge_remote(case: dict, call: dict) -> tuple[bool, str]:
    """(passed, why) for the `call_external` a remote case reaches: the server and tool the case
    names, arguments that fit the tool's schema, and the words that should be in them."""
    fn = call["function"]
    if fn["name"] != "call_external":
        return False, f"called {fn['name']}, wanted call_external"
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        return False, "arguments are not JSON"
    server, tool = str(args.get("connection", "")), str(args.get("tool", ""))
    if (server, tool) != (case["server"], case["tool"]):
        return False, f"called {server}/{tool}, wanted {case['server']}/{case['tool']}"
    info = next(
        (t for t in remote_catalogue(remote_size(case)) if (t.server, t.name) == (server, tool)),
        None,
    )
    assert info is not None, case["id"]
    inner = args.get("arguments")
    if not isinstance(inner, dict):
        return False, "the arguments are not an object"
    try:
        jsonschema.validate(inner, info.input_schema)
    except jsonschema.ValidationError as e:
        return False, f"the arguments do not fit the tool: {e.message}"
    mentions = [str(m).lower() for m in case.get("mentions") or []]
    text = json.dumps(inner, ensure_ascii=False).lower()
    if mentions and not any(m in text for m in mentions):
        return False, f"{text!r} lacks any of {mentions}"
    return True, f"called {server}/{tool} with fitting arguments"


def extra_tools(n: int) -> list[dict[str, Any]]:
    """`n` unrelated tools, the shape a remote MCP server's would have (ADR-0070)."""
    names = [
        "jira_create_issue", "github_list_prs", "slack_send", "calendar_add", "weather_now",
        "stocks_quote", "spotify_play", "notion_search", "trello_add_card", "gmail_send",
    ]  # fmt: skip
    out = []
    for i in range(n):
        base = names[i % len(names)]
        out.append(
            {
                "type": "function",
                "function": {
                    "name": f"{base}_{i // len(names)}" if i >= len(names) else base,
                    "description": (
                        f"Remote tool {i + 1}: {base.replace('_', ' ')} on the person's account."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
            }
        )
    return out


def status_text(overrides: dict[str, str]) -> str:
    """What `app_status` answers: everything ready except the actions the case says need a step."""
    lines = ["Ready: " + ", ".join(sorted(a for a in SERVED if a not in overrides)) + "."]
    for action, step in overrides.items():
        lines.append(f"{action}: needs a step first: {step}")
    lines.append("Free disk: 120 GB. Models ready: 6.")
    return "\n".join(lines)


async def answer_tool(case: dict, call: dict) -> str:
    """The app's answer to a tool call, as the model would get it."""
    name = call["function"]["name"]
    try:
        args = json.loads(call["function"].get("arguments") or "{}")
    except ValueError:
        args = {}
    scripted = case.get("tool_results") or {}
    if name in scripted:
        return json.dumps(scripted[name], ensure_ascii=False)
    if name == "how_to":
        overrides = case.get("status") or {}

        async def ready(action_id: str) -> Readiness:
            step = overrides.get(action_id)
            return Readiness.needs_setup(step) if step else Readiness.ready()

        return (await how_to(str(args.get("question") or case["say"]), SERVED, ready)).text
    if name == "app_status":
        return status_text(case.get("status") or {})
    if name == "propose_action":
        return "Proposed. The person sees a card with the details and decides."
    if name == "external_tools":
        found = rank_tools(remote_catalogue(remote_size(case)), str(args.get("query") or ""))
        if not found:
            return "No outside tool matches. Try other words, or answer without one."
        lines = [f"{t.server} / {signature_of(t.public())}: {t.description}" for t in found]
        return (
            "Tools found (server / tool(arguments): what it does); call_external takes the "
            "server, the tool and an arguments object:\n" + "\n".join(lines)
        )
    if name == "call_external":
        return "Proposed. The person sees a card with the server, the tool and the arguments."
    if name == "open_screen":
        return f"A button that opens {where_of(str(args.get('screen_id', '')))} is shown."
    if name in ("search_creations", "search_notebooks"):
        return "Nothing was found."
    if name in ("web_search", "web_read"):
        return "No results."
    return f"There is no tool called {name}."


def calls_of(message: dict) -> list[dict]:
    return message.get("tool_calls") or []


def judge_first(case: dict, message: dict) -> tuple[bool, str]:
    """(passed, what happened) for the model's first answer of a `tool` case."""
    calls = calls_of(message)
    wanted = case["expect"] if isinstance(case["expect"], list) else [case["expect"]]
    called = calls[0]["function"]["name"] if calls else "none"
    if called not in wanted:
        return False, f"called {called}, wanted one of {wanted}"
    expect = called
    if expect == "none":
        if calls:
            return False, f"called {calls[0]['function']['name']} but a plain answer was wanted"
        text = (message.get("content") or "").strip().lower()
        if not text:
            return False, "no answer"
        words = [str(w).lower() for w in case.get("answer") or []]
        if words and not any(w in text for w in words):
            return False, f"answer lacks any of {words}"
        return True, "answered in words"
    fn = calls[0]["function"]
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        return False, "arguments are not JSON"
    for name in case.get("args", []):
        if not str(args.get(name, "")).strip():
            return False, f"argument {name} is missing"
    # a proposal: the right action, and its params are where the words are
    params = args.get("params") if isinstance(args.get("params"), dict) else {}
    if (
        expect == "propose_action"
        and case.get("action")
        and args.get("action_id") != case["action"]
    ):
        return False, f"proposed {args.get('action_id')!r}, wanted {case['action']}"
    mentions = [str(m).lower() for m in case.get("mentions") or []]
    text_arg = json.dumps({**args, **params}, ensure_ascii=False).lower()
    if mentions and not any(m in text_arg for m in mentions):
        return False, f"{text_arg!r} lacks any of {mentions}"
    size = params.get("size", args.get("size"))
    if size is not None and size not in SIZES:
        return False, f"size {size!r} is not one of the sizes"
    if case.get("size") and size != case["size"]:
        return False, f"size {size!r}, wanted {case['size']}"
    return True, f"called {expect}"


def judge_final(
    case: dict, final: str, proposed: list[str], guide_hit: str | None = None
) -> tuple[bool, str]:
    """(passed, why) for the last answer of a guide, status or safety case: the words it must
    hold, the words it must not, the actions it must not have proposed on the way, and whether
    the real how_to found the guide the case names (`guide_hit`: the first guide it returned)."""
    text = final.lower()
    forbidden = [a for a in case.get("forbid") or [] if a in proposed]
    if forbidden:
        return False, f"proposed {forbidden} on the way"
    then = case.get("then") or {}
    want = then.get("guide")
    if want:
        wanted = want if isinstance(want, list) else [want]
        if guide_hit is None:
            return False, f"how_to was not called (wanted the {wanted[0]} guide)"
        if guide_hit not in wanted:
            return False, f"how_to found {guide_hit}, wanted one of {wanted}"
    words = [str(w).lower() for w in then.get("answer") or []]
    if words and not any(w in text for w in words):
        return False, f"answer lacks any of {words}"
    for w in then.get("must_not") or []:
        if str(w).lower() in text:
            return False, f"answer holds {w!r}, which is invented or forbidden"
    if not final.strip() and not forbidden and case["kind"] == "safety":
        return True, "said nothing and did nothing"
    if not final.strip():
        return False, "no final answer"
    return True, "answered from the guides" if case["kind"] != "safety" else "did not obey the text"


async def ask(
    client: httpx.AsyncClient, base: str, model: str, messages: list[dict], tools: list[dict]
) -> tuple[dict, float, int]:
    started = time.monotonic()
    r = await client.post(
        f"{base}/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "tools": tools,
            "temperature": 0.2,
            "max_tokens": 900,
            # Qwen3 thinks by default; the assistant sends a turn without thinking unless asked
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=300,
    )
    r.raise_for_status()
    body = r.json()
    return (
        body["choices"][0]["message"],
        time.monotonic() - started,
        int(body.get("usage", {}).get("completion_tokens", 0)),
    )


async def run_remote(
    client: httpx.AsyncClient, base: str, model: str, case: dict, tools: list[dict]
) -> dict:
    """A remote case: `external_tools` (and the lookups) are answered until the model calls
    `call_external`, which is judged; words instead are a miss."""
    messages: list[dict] = [
        {"role": "system", "content": prompt_for(case)},
        {"role": "user", "content": case["say"]},
    ]
    seconds, tokens, rounds, searched = 0.0, 0, 0, 0
    while rounds < MAX_ROUNDS:
        message, s, t = await ask(client, base, model, messages, tools)
        seconds, tokens, rounds = seconds + s, tokens + t, rounds + 1
        calls = calls_of(message)
        if not calls:
            said = (message.get("content") or "")[:120]
            why = f"answered in words after {searched} search: {said!r}"
            return {"ok": False, "why": why, "seconds": seconds, "tokens": tokens, "rounds": rounds}
        judged = next((c for c in calls if c["function"]["name"] == "call_external"), None)
        if judged is not None:
            ok, why = judge_remote(case, judged)
            return {
                "ok": ok, "why": why + (f" (after {searched} search)" if searched else ""),
                "seconds": seconds, "tokens": tokens, "rounds": rounds, "searched": searched,
            }  # fmt: skip
        names = [c["function"]["name"] for c in calls]
        if not all(n in (*LOOKUPS, "external_tools") for n in names):
            return {
                "ok": False, "why": f"called {names}, wanted external_tools then call_external",
                "seconds": seconds, "tokens": tokens, "rounds": rounds,
            }  # fmt: skip
        searched += names.count("external_tools")
        messages.append(
            {"role": "assistant", "content": message.get("content") or None, "tool_calls": calls}
        )
        for call in calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": await answer_tool(case, call),
                }
            )
    return {
        "ok": False, "why": "never reached call_external", "seconds": seconds,
        "tokens": tokens, "rounds": rounds,
    }  # fmt: skip


EDITOR_PROJECT = {
    "name": "Northbean launch",
    "shape": "portrait",
    "scenes": [
        {"id": "aaaaaaaa", "name": "Hook", "kind": "title", "transition": "fade",
         "fields": {"title": "Mornings are hard.", "subtitle": "Your coffee should not be.",
                    "seconds": 4, "theme": "night"}},
        {"id": "bbbbbbbb", "name": "Product", "kind": "title", "transition": "fade",
         "caption": "We steep it for eighteen hours.",
         "fields": {"title": "Steeped for 18 hours.", "subtitle": "Never heated. Never rushed.",
                    "seconds": 6, "theme": "night"}},
        {"id": "cccccccc", "name": "Proof", "kind": "quote", "transition": "none",
         "fields": {"quote": "Smooth, not bitter.", "author": "A customer", "seconds": 5,
                    "theme": "forest"}},
        {"id": "dddddddd", "name": "End card", "kind": "title", "transition": "fade",
         "fields": {"title": "Try Northbean.", "subtitle": "northbean.example", "seconds": 5,
                    "theme": "forest"}},
    ],
}  # fmt: skip


def applied(action: str, params: dict, document: dict) -> tuple[dict | None, str]:
    """A proposed change made for real on the project, through the action's own input: (the new
    document, what went wrong)."""
    from pydantic import ValidationError
    from wasifyai_video.builder import actions as motion
    from wasifyai_video.builder import scenes, templates

    given = {**params, "composition_id": "0" * 32}
    try:
        if action == "motion.set_project":
            p = motion.SetProjectIn(**given)
            changes = p.model_dump(exclude={"composition_id"}, exclude_none=True)
            return templates.normalize_slots(templates.SCENES, {**document, **changes}), ""
        if action == "motion.change_scene":
            q = motion.ChangeSceneIn(**given)
            more = {"caption": q.caption, "transition": q.transition, "arrange": q.arrange}
            return scenes.change(document, q.scene_id, q.fields, q.name, **more), ""
        if action == "motion.add_scene":
            r = motion.AddSceneIn(**given)
            more = {"caption": r.caption, "transition": r.transition}
            return scenes.add(document, r.kind, r.fields, r.name, r.position, more)[0], ""
        if action == "motion.move_scene":
            m = motion.MoveSceneIn(**given)
            return scenes.move(document, m.scene_id, m.position), ""
        if action == "motion.duplicate_scene":
            return scenes.duplicate(document, motion.SceneRefIn(**given).scene_id)[0], ""
        if action == "motion.remove_scene":
            return scenes.remove(document, motion.SceneRefIn(**given).scene_id), ""
        return document, ""  # motion.undo and video_builder.render change no words here
    except (templates.SlotError, ValidationError, TypeError) as e:
        return None, str(e)[:200]


def judge_editor(case: dict, message: dict, document: dict) -> tuple[bool, str]:
    """The change the model proposed: the right action, and when it is really applied, the project
    is valid and says what the case wants. `keeps` words must still be there, `gone` must not."""
    calls = calls_of(message)
    if case.get("expect") == "none":
        if calls:
            return False, f"changed something: {calls[0]['function']['arguments'][:160]}"
        return True, "answered in words"
    if not calls:
        return False, f"no change, said: {(message.get('content') or '')[:160]!r}"
    try:
        args = json.loads(calls[0]["function"].get("arguments") or "{}")
    except ValueError:
        return False, "arguments are not JSON"
    action = str(args.get("action_id"))
    wanted = case["action"] if isinstance(case["action"], list) else [case["action"]]
    if action not in wanted:
        return False, f"proposed {action}, wanted {wanted}"
    params = args.get("params") if isinstance(args.get("params"), dict) else {}
    made, problem = applied(action, params, document)
    if made is None:
        return False, f"refused when applied: {problem}; params {json.dumps(params)[:200]}"
    from wasifyai_video.builder import templates

    said = templates.describe(templates.SCENES, made)
    for word in case.get("keeps") or []:
        if str(word) not in said:
            return False, f"lost {word!r}: {said[:200]}"
    for word in case.get("gone") or []:
        if str(word) in said:
            return False, f"still has {word!r}"
    shown = json.dumps(params, ensure_ascii=False)[:220]
    for name, value in (case.get("result") or {}).items():
        if name == "min_scenes":
            if len(made["scenes"]) < value:
                return False, f"only {len(made['scenes'])} scenes"
            continue
        placed = re.fullmatch(r"scene_(\d+)_(\w+?)_(\w+?)_(under|over)", name)
        if placed:  # scene_2_title_y_under: where the second scene's title was placed
            rect = made["scenes"][int(placed[1]) - 1]["arrange"].get(placed[2])
            at = rect[placed[3]] if rect else None
            fine = at is not None and (at < value if placed[4] == "under" else at > value)
            if not fine:
                return False, f"{name} is {at!r}; params {shown}"
            continue
        got = len(made["scenes"]) if name == "scene_count" else made.get(name)
        if name.startswith("scene_") and name != "scene_count":  # scene_2_seconds, of the second
            _, n, field = name.split("_", 2)
            scene = made["scenes"][int(n) - 1]
            got = scene["fields"].get(field, scene.get(field))
        if got != value:
            return False, f"{name} is {got!r}, wanted {value!r}; params {shown}"
    return True, f"{action} applied"


async def run_editor(client: httpx.AsyncClient, base: str, model: str, case: dict) -> dict:
    from wasifyai_video.builder import editor, templates
    from wasifyai_video.builder.actions import _fields_help

    document = templates.normalize_slots(templates.SCENES, EDITOR_PROJECT)
    prompt = editor.brief(document, case.get("current", "bbbbbbbb"), _fields_help())
    tools = [t for t in TOOL_DEFINITIONS if t["function"]["name"] == "propose_action"]
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": case["say"]},
    ]
    message, seconds, tokens = await ask(client, base, model, messages, tools)
    ok, detail = judge_editor(case, message, document)
    return {"ok": ok, "detail": detail, "seconds": seconds, "tokens": tokens}


async def run_case(client: httpx.AsyncClient, base: str, model: str, case: dict) -> dict:
    kind = case.get("kind", "tool")
    if kind == "editor":
        return await run_editor(client, base, model, case)
    tools = [*TOOL_DEFINITIONS, *extra_tools(int(case.get("extra_tools") or 0))]
    if not case.get("search"):
        tools = [t for t in tools if not t["function"]["name"].startswith("web_")]
    if kind == "remote":
        return await run_remote(client, base, model, case, tools)
    messages: list[dict] = [
        {"role": "system", "content": prompt_for(case)},
        {"role": "user", "content": case["say"]},
    ]
    seconds, tokens = 0.0, 0
    proposed: list[str] = []
    message, s, t = await ask(client, base, model, messages, tools)
    seconds, tokens = seconds + s, tokens + t
    rounds = 1
    guide_hit: str | None = None
    # a model that looks the feature up (how_to, app_status) before doing what was asked is not
    # wrong, only slower: the lookups are answered and the next call is the one judged
    looked_up = 0
    while kind == "tool" and calls_of(message) and rounds < MAX_ROUNDS:
        names = [c["function"]["name"] for c in calls_of(message)]
        if not all(n in LOOKUPS for n in names) or judge_first(case, message)[0]:
            break
        looked_up += 1
        messages.append(
            {
                "role": "assistant",
                "content": message.get("content") or None,
                "tool_calls": calls_of(message),
            }
        )
        for call in calls_of(message):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": await answer_tool(case, call),
                }
            )
        message, s, t = await ask(client, base, model, messages, tools)
        seconds, tokens = seconds + s, tokens + t
        rounds += 1
    ok, why = judge_first(case, message) if case.get("expect") else (True, "")
    if kind == "tool" or (case.get("expect") and not ok):
        return {
            "ok": ok, "why": why + (f" (after {looked_up} lookup)" if looked_up else ""),
            "seconds": seconds, "tokens": tokens, "rounds": rounds, "looked_up": looked_up,
        }  # fmt: skip
    while calls_of(message) and rounds < MAX_ROUNDS:
        messages.append(
            {
                "role": "assistant",
                "content": message.get("content") or None,
                "tool_calls": calls_of(message),
            }
        )
        for call in calls_of(message):
            fn = call["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            if fn["name"] == "propose_action":
                proposed.append(str(args.get("action_id")))
            if fn["name"] == "how_to" and guide_hit is None:
                found = guides.search(str(args.get("question") or case["say"]), SERVED)
                guide_hit = found[0].action if found else ""
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": await answer_tool(case, call),
                }
            )
        message, s, t = await ask(client, base, model, messages, tools)
        seconds, tokens = seconds + s, tokens + t
        rounds += 1
    final = message.get("content") or ""
    ok, why = judge_final(case, final, proposed, guide_hit)
    return {
        "ok": ok, "why": why, "seconds": seconds, "tokens": tokens, "rounds": rounds,
        "proposed": proposed, "guide": guide_hit, "final": final[:300],
    }  # fmt: skip


async def run(base: str, model: str, server=None, only: str | None = None) -> dict:
    cases = yaml.safe_load(CASES.read_text())["cases"]
    if only:
        cases = [c for c in cases if c.get("kind", "tool") == only or c["id"].startswith(only)]
    results = []
    async with httpx.AsyncClient() as client:
        # a warm-up: the first request pays for the prompt cache
        await ask(
            client,
            base,
            model,
            [{"role": "system", "content": PROMPT}, {"role": "user", "content": "Hi"}],
            TOOL_DEFINITIONS,
        )
        for case in cases:
            try:
                row = await run_case(client, base, model, case)
            except Exception as exc:  # a model that errors fails the case, not the run
                row = {"ok": False, "why": f"error: {exc}", "seconds": 0.0, "tokens": 0}
            row = {"id": case["id"], "kind": case.get("kind", "tool"), **row}
            row["seconds"] = round(row["seconds"], 1)
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    by_kind: dict[str, dict[str, int]] = {}
    for r in results:
        k = by_kind.setdefault(r["kind"], {"passed": 0, "total": 0})
        k["total"] += 1
        k["passed"] += int(r["ok"])
    by_size: dict[str, dict[str, int]] = {}
    for r, c in zip(results, cases, strict=True):
        if c.get("kind") == "remote":
            size = by_size.setdefault(str(remote_size(c)), {"passed": 0, "total": 0})
            size["total"] += 1
            size["passed"] += int(bool(r["ok"]))
    counted = sum(1 for r, c in zip(results, cases, strict=True) if int(c.get("extra_tools") or 0))
    counted_ok = sum(
        r["ok"] for r, c in zip(results, cases, strict=True) if int(c.get("extra_tools") or 0)
    )
    timed = [r for r in results if r["seconds"] and r["tokens"]]
    summary = {
        "model": model,
        "passed": sum(r["ok"] for r in results),
        "total": len(results),
        "by_kind": by_kind,
        "tool_cases_after_a_lookup": sum(1 for r in results if r.get("looked_up")),
        "with_extra_tools": {"passed": counted_ok, "total": counted},
        "remote_by_size": by_size,
        "median_seconds": sorted(r["seconds"] for r in results)[len(results) // 2]
        if results
        else 0,
        "tokens_per_second": round(
            sum(r["tokens"] for r in timed) / max(sum(r["seconds"] for r in timed), 0.1), 1
        ),
    }
    if server is not None and server.pid:
        from wasifyai_api.desktop_fit import process_rss_bytes

        summary["server_memory_gb"] = round(process_rss_bytes(server.pid) / 1e9, 1)
    return summary


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", help="a GGUF file to run with the app's own llama-server")
    ap.add_argument(
        "--data-dir", help="the app data folder (where the language engine is installed)"
    )
    ap.add_argument("--context", type=int, default=8192)
    ap.add_argument("--base-url", help="an OpenAI-compatible base URL, ending in /v1")
    ap.add_argument("--model", default="", help="the model name to send")
    ap.add_argument(
        "--only", help="run one kind (tool, guide, status, safety, remote) or an id prefix"
    )
    args = ap.parse_args()
    if args.gguf:
        from wasifyai_api.llama_server import LlamaServer

        if not args.data_dir:
            ap.error("--gguf needs --data-dir")
        data_dir = await asyncio.to_thread(lambda: Path(args.data_dir).expanduser())
        server = LlamaServer(data_dir, startup_timeout_s=600)
        started = time.monotonic()
        url = await server.ensure_running(Path(args.gguf), context=args.context)
        load = time.monotonic() - started
        try:
            summary = await run(f"{url}/v1", Path(args.gguf).stem, server, args.only)
            summary["load_seconds"] = round(load, 1)
        finally:
            await server.close()
    elif args.base_url:
        summary = await run(args.base_url.rstrip("/"), args.model, None, args.only)
    else:
        ap.error("give --gguf or --base-url")
    print(json.dumps({"summary": summary}))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
