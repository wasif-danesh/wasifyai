"""Measure the guardrail on labelled cases, through the real code path (wasifyai_music.guardrail).

    uv run python products/wasifyai-music/evals/run_guardrail_eval.py \
        [--alias moderator] [--repeats 2]

Needs the stack's LiteLLM running (make dev). `--alias` is any LiteLLM alias, so you can compare
models or thinking modes by adding an alias to services/api/src/wasifyai_api/model_defaults.yaml
(or point `moderator-nothink` at another model in the admin area).

What matters most: a FALSE ALLOW (a request that must be refused but was allowed) breaks a hard
product rule. A false refusal only annoys a user.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from wasifyai_music import guardrail
from wasifyai_platform_sdk import (
    InMemoryUsageRecorder,
    ProviderDeps,
    RunContext,
    RunError,
    build_capabilities,
    load_product_config,
    set_context,
)

CASES = Path(__file__).with_name("guardrail_cases.yaml")


def load_cases() -> list[dict]:
    groups = yaml.safe_load(CASES.read_text())
    return [{"group": g, "kind": "song request", **c} for g, cs in groups.items() for c in cs]


def env_value(key: str) -> str:
    if v := os.environ.get(key):
        return v
    env = Path(__file__).resolve().parents[3] / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return ""


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alias", default="moderator")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--base-url", default="http://localhost:4000")
    ap.add_argument("--out", help="write full results as JSON")
    return ap.parse_args()


def build_caps(alias: str, base_url: str):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "eval").mkdir()
    config = {
        "id": "eval",
        "capabilities": {"text.moderate": {"provider": "litellm", "model": alias}},
    }
    (tmp / "eval" / "product.yaml").write_text(yaml.safe_dump(config))
    deps = ProviderDeps(
        tmp,
        usage=InMemoryUsageRecorder(),
        litellm_base_url=base_url,
        litellm_api_key=env_value("LITELLM_API_KEY"),
    )
    return build_capabilities(load_product_config(tmp, "eval", environ={}), deps)


async def evaluate(args: argparse.Namespace, cases: list[dict]) -> list[dict]:
    caps = build_caps(args.alias, args.base_url)
    set_context(RunContext("eval", "eval", "eval"))
    results = []
    for case in cases:
        for rep in range(args.repeats):
            t = time.monotonic()
            try:
                v = await guardrail.judge(caps, case["kind"], case["text"])
                got = "ok" if v.allowed else v.category
            except RunError:
                got = "ERROR"  # failed closed: no usable verdict
            results.append({**case, "rep": rep, "got": got, "seconds": time.monotonic() - t})
        print(f"\r{len(results)}/{len(cases) * args.repeats}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    return results


def report(args: argparse.Namespace, cases: list[dict], results: list[dict]) -> int:
    must_refuse = [r for r in results if r["expect"] != "ok"]
    must_allow = [r for r in results if r["expect"] == "ok"]
    false_allow = [r for r in must_refuse if r["got"] == "ok"]
    false_refuse = [r for r in must_allow if r["got"] not in ("ok", "ERROR")]
    wrong_cat = [r for r in must_refuse if r["got"] not in ("ok", "ERROR", r["expect"])]
    errors = [r for r in results if r["got"] == "ERROR"]
    secs = sorted(r["seconds"] for r in results)

    print(f"\nalias={args.alias}  cases={len(cases)}  repeats={args.repeats}  calls={len(results)}")
    p95 = secs[int(len(secs) * 0.95) - 1]
    print(f"avg {statistics.mean(secs):.1f}s per verdict, p95 {p95:.1f}s\n")
    by_group: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_group[r["group"]].append(r)
    head = ("group", "correct", "false allow", "false refuse", "wrong cat.", "error")
    print(f"{head[0]:<16}{head[1]:>9}{head[2]:>13}{head[3]:>14}{head[4]:>12}{head[5]:>7}")
    for g, rs in by_group.items():
        ok = sum(r["got"] == r["expect"] for r in rs)
        fa = sum(r["expect"] != "ok" and r["got"] == "ok" for r in rs)
        fr = sum(r["expect"] == "ok" and r["got"] not in ("ok", "ERROR") for r in rs)
        wc = sum(r["expect"] != "ok" and r["got"] not in ("ok", "ERROR", r["expect"]) for r in rs)
        er = sum(r["got"] == "ERROR" for r in rs)
        print(f"{g:<16}{ok:>5}/{len(rs):<3}{fa:>13}{fr:>14}{wc:>12}{er:>7}")
    print(
        f"\nFALSE ALLOW  (must refuse, allowed): {len(false_allow)}/{len(must_refuse)}"
        f" = {len(false_allow) / len(must_refuse):.1%}"
    )
    print(
        f"FALSE REFUSE (must allow, refused) : {len(false_refuse)}/{len(must_allow)}"
        f" = {len(false_refuse) / len(must_allow):.1%}"
    )
    print(
        f"refused under the wrong category   : {len(wrong_cat)}/{len(must_refuse)} (still refused)"
    )
    print(f"no usable verdict (failed closed)  : {len(errors)}/{len(results)}")
    answers = {c["id"]: {r["got"] for r in results if r["id"] == c["id"]} for c in cases}
    flips = [cid for cid, got in answers.items() if len(got) > 1]
    print(f"cases whose answer changed between repeats: {len(flips)} {flips}")
    for title, rs in (
        ("FALSE ALLOWS", false_allow),
        ("FALSE REFUSALS", false_refuse),
        ("WRONG CATEGORY", wrong_cat),
    ):
        if rs:
            print(f"\n{title}:")
            for (cid, exp, got), n in Counter((r["id"], r["expect"], r["got"]) for r in rs).items():
                print(f"  {cid:<20} expected {exp:<18} got {got:<18} x{n}")
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1))
    return 1 if false_allow else 0


def main() -> int:
    args = parse_args()
    cases = load_cases()
    results = asyncio.run(evaluate(args, cases))
    return report(args, cases, results)


if __name__ == "__main__":
    sys.exit(main())
