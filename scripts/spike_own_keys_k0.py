"""Spike K0 of ADR-0095: a chat on OpenRouter, a picture and a clip on fal.ai, with one's own keys.

It calls the providers the way the engine will: the chat through the OpenAI-compatible client the
text provider already uses (`openai.AsyncOpenAI` with the provider's address and the key), the media
through fal.ai's queue API over `httpx` (submit, follow `status_url`, read `response_url`, download
the file). It writes down how long each step took and what each request and answer looked like,
never the keys.

    OPENROUTER_API_KEY=... FAL_KEY=... uv run python scripts/spike_own_keys_k0.py --out /tmp/k0

Keys are read from the environment only. The results go to `<out>/k0.json` and the files beside
it; nothing is kept in the repository.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from openai import AsyncOpenAI

OPENROUTER = "https://openrouter.ai/api/v1"
FAL_QUEUE = "https://queue.fal.run"
CHAT_MODEL = "openai/gpt-4o-mini"
PICTURE = "fal-ai/flux-2"
CLIP = "fal-ai/ltx-2/text-to-video/fast"
POLL_S = 2.0
TIMEOUT_S = 900.0


def shape(value: Any) -> Any:
    """The keys and types of an answer, without its values (the form, not the content)."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return type(value).__name__


async def chat(key: str, model: str) -> dict[str, Any]:
    client = AsyncOpenAI(base_url=OPENROUTER, api_key=key)
    t0 = time.monotonic()
    first = None
    text = ""
    usage: dict[str, Any] = {}
    stream = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Answer in one short sentence."},
            {"role": "user", "content": "What colour is a clear daytime sky?"},
        ],
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            first = first if first is not None else time.monotonic() - t0
            text += chunk.choices[0].delta.content
        if chunk.usage:
            usage = {"input": chunk.usage.prompt_tokens, "output": chunk.usage.completion_tokens}
    return {
        "provider": "openrouter", "model": model, "first_token_s": round(first or 0, 2),
        "total_s": round(time.monotonic() - t0, 2), "answer": text.strip(), "tokens": usage,
    }  # fmt: skip


async def fal(
    key: str, endpoint: str, body: dict[str, Any], out: Path, name: str
) -> dict[str, Any]:
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=120)) as http:
        r = await http.post(f"{FAL_QUEUE}/{endpoint}", headers=headers, json=body)
        if r.status_code >= 400:
            return {"endpoint": endpoint, "error": r.status_code, "said": r.text[:500]}
        sub = r.json()
        queued_s = round(time.monotonic() - t0, 2)
        states: list[str] = []
        while True:
            if time.monotonic() - t0 > TIMEOUT_S:
                return {"endpoint": endpoint, "error": "timeout", "states": states}
            st = (await http.get(sub["status_url"], headers=headers)).json()
            if not states or states[-1] != st.get("status"):
                states.append(str(st.get("status")))
            if st.get("status") == "COMPLETED":
                break
            await asyncio.sleep(POLL_S)
        done_s = round(time.monotonic() - t0, 2)
        res = await http.get(sub["response_url"], headers=headers)
        result = res.json()
        if res.status_code >= 400 or st.get("error"):
            said = json.dumps(result)[:500]
            return {"endpoint": endpoint, "error": res.status_code, "said": said}
        media = (result.get("images") or [{}])[0] if "images" in result else result["video"]
        url = media.get("url", "")
        t1 = time.monotonic()
        data = (await http.get(url)).content if url else b""
        fetch_s = round(time.monotonic() - t1, 2)
    kind = media.get("content_type", "image/png")
    ext = ".mp4" if "video" in result else "." + kind.split("/")[-1]
    path = out / f"{name}{ext}"
    path.write_bytes(data)
    return {
        "endpoint": endpoint, "request": body, "submit_answer": shape(sub), "states": states,
        "queued_s": queued_s, "done_s": done_s, "fetch_s": fetch_s, "bytes": len(data),
        "file": str(path), "result_shape": shape(result),
        "inference_s": (st.get("metrics") or {}).get("inference_time"),
    }  # fmt: skip


def brief(step: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in step.items() if k != "result_shape"}


async def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--chat-model", default=CHAT_MODEL)
    ap.add_argument("--picture", default=PICTURE)
    ap.add_argument("--clip", default=CLIP)
    ap.add_argument("--skip", choices=["chat", "picture", "clip"], action="append", default=[])
    a = ap.parse_args()
    or_key, fal_key = os.environ.get("OPENROUTER_API_KEY", ""), os.environ.get("FAL_KEY", "")
    needs = (("OPENROUTER_API_KEY", or_key, {"chat"}), ("FAL_KEY", fal_key, {"picture", "clip"}))
    missing = [n for n, k, uses in needs if not k and uses - set(a.skip)]
    if missing:
        print(f"Set {' and '.join(missing)} in the environment first.", file=sys.stderr)
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {}
    if "chat" not in a.skip:
        record["chat"] = await chat(or_key, a.chat_model)
        print("chat", json.dumps(record["chat"]))
    if "picture" not in a.skip:
        fox = "A red fox standing in fresh snow, soft morning light"
        body = {"prompt": fox, "image_size": "square_hd"}
        record["picture"] = await fal(fal_key, a.picture, body, a.out, "picture")
        print("picture", json.dumps(brief(record["picture"])))
    if "clip" not in a.skip:
        waves = "Waves rolling onto a sandy beach at sunset, slow camera pan"
        body = {"prompt": waves, "duration": 6, "resolution": "1080p", "generate_audio": False}
        record["clip"] = await fal(fal_key, a.clip, body, a.out, "clip")
        print("clip", json.dumps(brief(record["clip"])))
    (a.out / "k0.json").write_text(json.dumps(record, indent=2))
    print(f"wrote {a.out / 'k0.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
