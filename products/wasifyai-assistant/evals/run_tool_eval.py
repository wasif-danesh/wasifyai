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
to see whether the choice still holds. One JSON line per case, then a summary per kind.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml
from wasifyai_assistant import help as guides
from wasifyai_assistant.features import actions_prompt, where_of
from wasifyai_assistant.graph import SYSTEM_PROMPT
from wasifyai_assistant.tools import TOOL_DEFINITIONS, how_to
from wasifyai_platform_sdk.actions import Readiness

CASES = Path(__file__).with_name("cases.yaml")
SIZES = ("square", "landscape", "portrait", "wide", "tall")
SERVED = {g.action for g in guides.guides()}
# what the assistant is really sent: its prompt and the list of actions it may propose
PROMPT = SYSTEM_PROMPT + actions_prompt(SERVED)
MAX_ROUNDS = 4
LOOKUPS = (
    "how_to",
    "app_status",
)  # reads of the app's own files and state: never wrong, only slower
# the kinds, and whether the case goes on after the first answer
KINDS = ("tool", "guide", "status", "safety")


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


async def run_case(client: httpx.AsyncClient, base: str, model: str, case: dict) -> dict:
    kind = case.get("kind", "tool")
    tools = [*TOOL_DEFINITIONS, *extra_tools(int(case.get("extra_tools") or 0))]
    if not case.get("search"):
        tools = [t for t in tools if not t["function"]["name"].startswith("web_")]
    messages: list[dict] = [
        {"role": "system", "content": PROMPT},
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
    ap.add_argument("--only", help="run one kind (tool, guide, status, safety) or an id prefix")
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
