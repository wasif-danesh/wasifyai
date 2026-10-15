"""Run the assistant's tool-choice cases against a model (ADR-0057, docs/phase2-stage-d-plan.md D6).

    uv run python products/wasifyai-assistant/evals/run_tool_eval.py \\
        --gguf /path/model.gguf --data-dir <the app data folder with the language engine>
    uv run python products/wasifyai-assistant/evals/run_tool_eval.py \\
        --base-url http://127.0.0.1:11434/v1 --model qwen3:4b

Each case is sent with the assistant's own system prompt and tool definitions. It reports, per
model: tool-choice accuracy, usable arguments, answer words where asked, the time to the answer,
the speed and (for a GGUF the app runs itself) the server's memory. One JSON line per case,
then a summary.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import yaml
from wasifyai_assistant.graph import SYSTEM_PROMPT
from wasifyai_assistant.tools import SIZES, TOOL_DEFINITIONS

CASES = Path(__file__).with_name("cases.yaml")


def judge(case: dict, message: dict) -> tuple[bool, str]:
    """(passed, what happened) for one answer."""
    calls = message.get("tool_calls") or []
    expect = case["expect"]
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
    if not calls:
        return False, f"no tool call (wanted {expect})"
    fn = calls[0]["function"]
    if fn["name"] != expect:
        return False, f"called {fn['name']}, wanted {expect}"
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        return False, "arguments are not JSON"
    for name in case.get("args", []):
        if not str(args.get(name, "")).strip():
            return False, f"argument {name} is missing"
    mentions = [str(m).lower() for m in case.get("mentions") or []]
    text_arg = str(args.get("prompt") or args.get("query") or "").lower()
    if mentions and not any(m in text_arg for m in mentions):
        return False, f"{text_arg!r} lacks any of {mentions}"
    if "size" in args and args["size"] not in SIZES:
        return False, f"size {args['size']!r} is not one of the sizes"
    if case.get("size") and args.get("size") != case["size"]:
        return False, f"size {args.get('size')!r}, wanted {case['size']}"
    return True, f"called {expect}"


async def ask(
    client: httpx.AsyncClient, base: str, model: str, say: str
) -> tuple[dict, float, int]:
    started = time.monotonic()
    r = await client.post(
        f"{base}/chat/completions",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": say},
            ],
            "tools": TOOL_DEFINITIONS,
            "temperature": 0.2,
            "max_tokens": 600,
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


async def run(base: str, model: str, server=None) -> dict:
    cases = yaml.safe_load(CASES.read_text())["cases"]
    results = []
    async with httpx.AsyncClient() as client:
        await ask(
            client, base, model, "Hi"
        )  # a warm-up: the first request pays for the prompt cache
        for case in cases:
            try:
                message, seconds, tokens = await ask(client, base, model, case["say"])
                ok, why = judge(case, message)
            except Exception as exc:  # a model that errors fails the case, not the run
                message, seconds, tokens, ok, why = {}, 0.0, 0, False, f"error: {exc}"
            row = {
                "id": case["id"], "ok": ok, "why": why, "seconds": round(seconds, 1),
                "tokens": tokens,
            }  # fmt: skip
            results.append(row)
            print(json.dumps(row), flush=True)
    passed = sum(r["ok"] for r in results)
    timed = [r for r in results if r["seconds"] and r["tokens"]]
    summary = {
        "model": model,
        "passed": passed,
        "total": len(results),
        "tool_cases_passed": sum(
            r["ok"] for r, c in zip(results, cases, strict=True) if c["expect"] != "none"
        ),
        "tool_cases": sum(c["expect"] != "none" for c in cases),
        "median_seconds": sorted(r["seconds"] for r in results)[len(results) // 2],
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
            summary = await run(f"{url}/v1", Path(args.gguf).stem, server)
            summary["load_seconds"] = round(load, 1)
        finally:
            await server.close()
    elif args.base_url:
        summary = await run(args.base_url.rstrip("/"), args.model)
    else:
        ap.error("give --gguf or --base-url")
    print(json.dumps({"summary": summary}))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
