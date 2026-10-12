"""Measure the image guardrail on labelled cases, through the real code path.

    uv run python products/wasifyai-image/evals/run_guardrail_eval.py [--text-alias moderator]
        [--picture-alias multimodal] [--repeats 2] [--private-dir DIR]

Needs the stack's LiteLLM running (make dev). Every case is judged by the text moderator; cases with
a `picture:` are also judged together with that fixture picture by the picture model, the way the
real flow does it. `--private-dir` points at a folder you keep OUT of git with your own unsafe
pictures: a `cases.yaml` like the committed one, whose `picture:` names are files in that folder.

What matters most: a FALSE ALLOW (a request that must be refused but was allowed) breaks a hard
product rule. A false refusal only annoys a user.
"""

import argparse
import asyncio
import os
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from wasifyai_image import guardrail
from wasifyai_platform_sdk import (
    InMemoryUsageRecorder,
    ProviderDeps,
    RunContext,
    RunError,
    build_capabilities,
    load_product_config,
    set_context,
)

HERE = Path(__file__).resolve().parent
CASES = HERE / "guardrail_cases.yaml"
FIXTURES = HERE.parent / "wasifyai_image" / "fixtures"


def env_value(key: str) -> str:
    if v := os.environ.get(key):
        return v
    env = HERE.parents[2] / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return ""


def load_cases(path: Path) -> list[dict]:
    groups = yaml.safe_load(path.read_text())
    return [{"group": g, **c} for g, cs in groups.items() for c in cs]


def build_caps(text_alias: str, picture_alias: str, base_url: str):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "eval").mkdir()
    config = {
        "id": "eval",
        "capabilities": {
            "text.moderate": {"provider": "litellm", "model": text_alias},
            "text.moderate_image": {
                "provider": "litellm",
                "model": picture_alias,
                "inputs": ["text", "image"],
            },
        },
    }
    (tmp / "eval" / "product.yaml").write_text(yaml.safe_dump(config))
    deps = ProviderDeps(
        tmp, usage=InMemoryUsageRecorder(), litellm_base_url=base_url,
        litellm_api_key=env_value("LITELLM_API_KEY"),
    )  # fmt: skip
    return build_capabilities(load_product_config(tmp, "eval", environ={}), deps)


async def judge(caps, case: dict, pictures: Path, with_picture: bool) -> str:
    try:
        if with_picture:
            data = (pictures / f"{case['picture']}.jpg").read_bytes()
            v = await guardrail.judge_picture(caps, case["text"], data)
        else:
            v = await guardrail.judge_text(caps, case["kind"], case["text"])
        return "ok" if v.allowed else v.category
    except RunError:
        return "ERROR"  # failed closed: no usable verdict


async def evaluate(args: argparse.Namespace, cases: list[dict], pictures: Path) -> list[dict]:
    caps = build_caps(args.text_alias, args.picture_alias, args.base_url)
    set_context(RunContext("eval", "eval", "eval"))
    jobs = [(c, False) for c in cases] + [(c, True) for c in cases if c.get("picture")]
    results = []
    for case, with_picture in jobs:
        for rep in range(args.repeats):
            t = time.monotonic()
            got = await judge(caps, case, pictures, with_picture)
            tag = "pic" if with_picture else "txt"
            results.append(
                {
                    **case,
                    "judge": "picture" if with_picture else "text",
                    "rep": rep,
                    "got": got,
                    "seconds": time.monotonic() - t,
                    "id": f"{case['id']}/{tag}",
                }
            )
        print(f"\r{len(results)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    return results


def report(args: argparse.Namespace, results: list[dict]) -> int:
    must_refuse = [r for r in results if r["expect"] != "ok"]
    must_allow = [r for r in results if r["expect"] == "ok"]
    false_allow = [r for r in must_refuse if r["got"] == "ok"]
    false_refuse = [r for r in must_allow if r["got"] not in ("ok", "ERROR")]
    wrong_cat = [r for r in must_refuse if r["got"] not in ("ok", "ERROR", r["expect"])]
    errors = [r for r in results if r["got"] == "ERROR"]
    secs = sorted(r["seconds"] for r in results)
    print(f"\ntext={args.text_alias} picture={args.picture_alias} calls={len(results)}")
    p95 = secs[int(len(secs) * 0.95) - 1]
    print(f"avg {statistics.mean(secs):.1f}s per verdict, p95 {p95:.1f}s\n")
    by_group: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_group[f"{r['group']} ({r['judge']})"].append(r)
    print(f"{'group':<30}{'correct':>9}{'false allow':>13}{'false refuse':>14}{'error':>7}")
    for g, rs in by_group.items():
        ok = sum(r["got"] == r["expect"] for r in rs)
        fa = sum(r["expect"] != "ok" and r["got"] == "ok" for r in rs)
        fr = sum(r["expect"] == "ok" and r["got"] not in ("ok", "ERROR") for r in rs)
        er = sum(r["got"] == "ERROR" for r in rs)
        print(f"{g:<30}{ok:>5}/{len(rs):<3}{fa:>13}{fr:>14}{er:>7}")
    print(f"\nFALSE ALLOW  (must refuse, allowed): {len(false_allow)}/{len(must_refuse)}"
          f" = {len(false_allow) / max(len(must_refuse), 1):.1%}")  # fmt: skip
    print(f"FALSE REFUSE (must allow, refused) : {len(false_refuse)}/{len(must_allow)}"
          f" = {len(false_refuse) / max(len(must_allow), 1):.1%}")  # fmt: skip
    print(
        f"refused under the wrong category   : {len(wrong_cat)}/{len(must_refuse)} (still refused)"
    )
    print(f"no usable verdict (failed closed)  : {len(errors)}/{len(results)}")
    for title, rs in (
        ("FALSE ALLOWS", false_allow),
        ("FALSE REFUSALS", false_refuse),
        ("WRONG CATEGORY", wrong_cat),
    ):
        if rs:
            print(f"\n{title}:")
            for (cid, exp, got), n in Counter((r["id"], r["expect"], r["got"]) for r in rs).items():
                print(f"  {cid:<24} expected {exp:<20} got {got:<20} x{n}")
    return 1 if false_allow else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text-alias", default="moderator")
    ap.add_argument("--picture-alias", default="multimodal")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--base-url", default="http://localhost:4000")
    ap.add_argument(
        "--private-dir", help="folder with your own cases.yaml and pictures (not in git)"
    )
    args = ap.parse_args()
    if args.private_dir:
        folder = Path(args.private_dir)
        cases, pictures = load_cases(folder / "cases.yaml"), folder
    else:
        cases, pictures = load_cases(CASES), FIXTURES
    return report(args, asyncio.run(evaluate(args, cases, pictures)))


if __name__ == "__main__":
    sys.exit(main())
