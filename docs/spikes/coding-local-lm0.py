"""LM0 (docs/coding-local-model-plan.md): the coding evaluation on the app's own llama-server.

Kept as it was run, before LM1. It reaches the server through the `qwen-27b-ollama` entry and
`CODING_OLLAMA_URL`, which LM1 removed, so it no longer runs. The same run is now
`run_eval.py --data "<app data>" --model this-computer --gguf <file.gguf>`.

    uv run python docs/spikes/coding-local-lm0.py --data "<app data>" --gguf <file.gguf> \
        --context 32768 --out results.json [task ids...]

The server is started the way the app starts it (`LlamaServer.ensure_running`: `--jinja`, one
slot, the small prompt cache), with the context asked for. Then:

1. one chat call with a tool, to see whether the GGUF's template gives a tool call back;
2. the 36 tasks of `products/wasifyai-code/evals/run_eval.py`, with the gateway's local route
   pointed at this server (`CODING_OLLAMA_URL`; llama-server ignores the model's name, so the
   route's own settings, `max_input_tokens` included, are used unchanged);
3. the server's peak memory (resident size, sampled every 2 s) and the wall time.

`--data` needs `engine/llamacpp` (the app's installed release) and `engine/coding` and
`engine/node`, as for the eval runner.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from wasifyai_api.llama_server import LlamaServer

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "products" / "wasifyai-code" / "evals" / "run_eval.py"
TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file of the project",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}


async def tool_probe(url: str) -> dict:
    body = {
        "model": "local",
        "messages": [{"role": "user", "content": "Read the file app.py and tell me what it does."}],
        "tools": [TOOL],
        "max_tokens": 512,
    }
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=600) as http:
        r = await http.post(f"{url}/v1/chat/completions", json=body)
    msg = r.json()["choices"][0]["message"]
    calls = msg.get("tool_calls") or []
    return {
        "status": r.status_code,
        "seconds": round(time.monotonic() - started, 1),
        "tool_calls": [
            {"name": c["function"]["name"], "arguments": c["function"]["arguments"]} for c in calls
        ],
    }


def rss_mb(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
    return int(out.stdout.strip() or 0) / 1024


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--gguf", type=Path, required=True)
    p.add_argument("--context", type=int, default=32768)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--spec", default="", help="e.g. draft-mtp,ngram-mod")
    p.add_argument("tasks", nargs="*")
    a = p.parse_args()

    server = LlamaServer(a.data)
    started = time.monotonic()
    extra = ["--spec-type", a.spec] if a.spec else []
    url = await server.ensure_running(a.gguf, context=a.context, extra_args=extra)
    load_s = round(time.monotonic() - started, 1)
    pid = server.pid
    assert pid is not None
    print(f"llama-server {server.state()['version']} on {url}, loaded in {load_s} s", flush=True)
    probe = await tool_probe(url)
    print("tool probe:", json.dumps(probe), flush=True)

    peak = rss_mb(pid)
    env = {**os.environ, "CODING_OLLAMA_URL": url}
    cmd = [sys.executable, __file__, "--runner", "--data", str(a.data), "--model",
           "qwen-27b-ollama", "--out", str(a.out), *a.tasks]  # fmt: skip
    ran = time.monotonic()
    proc = await asyncio.create_subprocess_exec(*cmd, env=env)
    while proc.returncode is None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except TimeoutError:
            peak = max(peak, rss_mb(pid))
    summary = {
        "gguf": a.gguf.name,
        "context": a.context,
        "spec": a.spec,
        "load_s": load_s,
        "tool_probe": probe,
        "eval_minutes": round((time.monotonic() - ran) / 60, 1),
        "peak_rss_gb": round(peak / 1024, 1),
        "runner_exit": proc.returncode,
    }
    print("summary:", json.dumps(summary), flush=True)
    a.out.with_suffix(".lm0.json").write_text(json.dumps(summary, indent=2))
    await server.close()


def runner(argv: list[str]) -> int:
    """The eval runner, with the local route switched to llama-server's own way of turning
    thinking off (the chat template's switch, as chat does in `desktop_language.thinking_fields`)
    in place of Ollama's `reasoning_effort`, which llama-server does not read."""
    from dataclasses import replace

    from wasifyai_api import coding_gateway

    original = coding_gateway.load_models

    def load_models(*args, **kwargs):  # type: ignore[no-untyped-def]
        default, models = original(*args, **kwargs)
        route = models.get("qwen-27b-ollama")
        if route is not None:
            settings = {k: v for k, v in route.engine_settings.items() if k != "reasoning_effort"}
            settings["litellm_extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            models["qwen-27b-ollama"] = replace(route, engine_settings=settings)
        return default, models

    coding_gateway.load_models = load_models
    sys.path.insert(0, str(RUNNER.parent))
    import run_eval  # type: ignore[import-not-found]

    return run_eval.main(argv)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--runner"]:
        sys.exit(runner(sys.argv[2:]))
    asyncio.run(main())
