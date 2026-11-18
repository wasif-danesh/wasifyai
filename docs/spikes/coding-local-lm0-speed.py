"""LM0's speed check: how fast the app's llama-server writes coding output, per file and option.

    uv run python docs/spikes/coding-local-lm0-speed.py --data "<app data>" --gguf <file.gguf> \
        [--draft <mtp.gguf>] [--spec ngram-mod] --label <name> --out speed.jsonl

The server is started the way the app starts it (`LlamaServer.ensure_running`, context 32,768),
with the speculative options added. Three kinds of output a coding session writes are asked for,
each twice, thinking off (`chat_template_kwargs`), at Qwen's non-thinking settings:

    edit     the whole of a real file again with one small change (mostly copied text)
    write    a new module from a description
    explain  plain words about a file

The writing speed is llama-server's own figure (`timings.predicted_per_second`); with a draft, how
many drafted tokens were accepted too. One line of JSON per run is added to `--out`.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx
from wasifyai_api.llama_server import LlamaServer

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "products" / "wasifyai-code" / "wasifyai_code" / "installs.py").read_text()
PROMPTS = {
    "edit": "Here is a Python file.\n\n```python\n" + SOURCE + "\n```\n\nChange LIMIT_S to 20 "
    "minutes and nothing else. Reply with the whole file again in one code block, nothing else.",
    "write": "Write a Python module `intervals.py` with a function merge(intervals) that merges "
    "overlapping closed intervals given as (start, end) tuples, a function total_length, type "
    "hints, docstrings, and pytest tests for both in the same reply.",
    "explain": "Explain in plain words, in about 300 words, what this file does and why.\n\n"
    "```python\n" + SOURCE + "\n```",
}


async def ask(http: httpx.AsyncClient, url: str, prompt: str) -> dict:
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1200,
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.monotonic()
    r = await http.post(f"{url}/v1/chat/completions", json=body)
    r.raise_for_status()
    data = r.json()
    t = data.get("timings") or {}
    return {
        "seconds": round(time.monotonic() - started, 1),
        "tokens": t.get("predicted_n"),
        "tok_s": round(t.get("predicted_per_second") or 0, 1),
        "draft_n": t.get("draft_n"),
        "draft_accepted": t.get("draft_n_accepted"),
    }


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--gguf", type=Path, required=True)
    p.add_argument("--draft", type=Path)
    p.add_argument("--spec", default="")
    p.add_argument("--label", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()

    extra: list[str] = []
    if a.draft:
        extra += ["--spec-type", "draft-mtp", "-md", str(a.draft)]
    elif a.spec:
        extra += ["--spec-type", a.spec]
    server = LlamaServer(a.data)
    url = await server.ensure_running(a.gguf, context=32768, extra_args=extra)
    async with httpx.AsyncClient(timeout=900) as http:
        await ask(http, url, "Say hello.")  # warm up
        for kind, prompt in PROMPTS.items():
            for run in (1, 2):
                got = {"label": a.label, "kind": kind, "run": run, **await ask(http, url, prompt)}
                print(json.dumps(got), flush=True)
                with a.out.open("a") as f:
                    f.write(json.dumps(got) + "\n")
    await server.close()


if __name__ == "__main__":
    asyncio.run(main())
