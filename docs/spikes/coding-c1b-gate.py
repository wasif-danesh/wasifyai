"""Measure stage C1b's gate through the API of the real desktop engine (docs/spikes/coding-c1b.md).

    CODING_OLLAMA_URL=http://127.0.0.1:11434 uv run python docs/spikes/coding-c1b-gate.py \
        --data "<app data with the coding engine set up>" --model qwen-27b-ollama \
        --project ~/Projects/a --project ~/Projects/b --project ~/Projects/c --out gate.json

It starts the desktop engine the way the shell does (`python -m wasifyai_api.desktop`, a port of its
own, a token signed as the window's is), and then only calls the coding product's routes:

    analyse   for each project: a new session, "Analyse this codebase.", wait for the end. The time,
              the steps, the counted cost and the answer are kept. Every file of the project is
              listed before and after (path, size, time of last change, mode): a difference is a
              failed gate
    stop      on the first project: a long request, then Stop after 0, 0.5, 2, 5 and 10 seconds; the
              time until the stop route answers with the turn closed
    the key   every file the coding engine could write, and its log, is searched for anything that
              looks like a provider's key (`sk-ant-`, `sk-`), and for the gateway's own token

A cloud model needs `--keychain` (the engine then opens the app's own secret store, as the real app
does) and costs money: only when the owner has said so. This script never reads a key itself.
A measurement script, kept beside its results; not product code.
"""

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import jwt

REPO = Path(__file__).resolve().parents[2]
BASE = "/products/wasifyai-code/code"
SKIP = {".git", "node_modules", ".venv", "target", "__pycache__", "dist", ".next", ".turbo"}
ASK = "Analyse this codebase."
LONG_ASK = (
    "Analyse this codebase in great detail: read every source file you can find, one by one, "
    "and describe each of them."
)
KEY_LIKE = re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}")


def listing(folder: Path) -> dict[str, tuple[int, int, int]]:
    """Every file under a folder with its size, time of last change and mode. The folders that
    hold other programs' output (`node_modules`, `.git`, ...) are listed by their own entry only:
    a write into one of them changes the folder's own time."""
    out: dict[str, tuple[int, int, int]] = {}
    stack = [folder]
    while stack:
        here = stack.pop()
        try:
            entries = list(os.scandir(here))
        except OSError:
            continue
        for entry in entries:
            st = entry.stat(follow_symlinks=False)
            out[os.path.relpath(entry.path, folder)] = (st.st_size, st.st_mtime_ns, st.st_mode)
            if entry.is_dir(follow_symlinks=False) and entry.name not in SKIP:
                stack.append(Path(entry.path))
    return out


class Engine:
    """The desktop engine as the shell runs it."""

    def __init__(self, data: Path, keychain: bool):
        self.secret = secrets.token_urlsafe(48)
        env = {
            **os.environ,
            "DEPLOYMENT_PROFILE": "desktop",
            "DESKTOP_DATA_DIR": str(data),
            "API_AUTH_SECRET": self.secret,
            "AUTH_MODE": "jwt",
            "WASIFYAI_PORT": "0",
            "PRODUCTS_DIR": str(REPO / "products"),
            "DESKTOP_IMAGE_ENGINE": "stub",
            "LITELLM_BASE_URL": "",
            "METRICS_PORT": "0",
            "WASIFYAI_EXIT_ON_STDIN_EOF": "1",
            "LOG_LEVEL": "WARNING",
            "DESKTOP_SECRET_STORE": "keychain" if keychain else "file",
        }
        self.log = open(data / "gate-engine.log", "ab")  # noqa: SIM115
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "wasifyai_api.desktop"],
            env=env, cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
        )  # fmt: skip
        assert self.proc.stdout is not None
        port = None
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and port is None:
            line = self.proc.stdout.readline()
            if not line:
                raise SystemExit("the engine did not start: see gate-engine.log in the data folder")
            try:
                said = json.loads(line)
            except ValueError:
                continue
            port = said.get("port")
        self.url = f"http://127.0.0.1:{port}"
        self.http = httpx.Client(base_url=self.url, timeout=60)

    def headers(self) -> dict[str, str]:
        now = int(time.time())
        claims = {
            "iss": "wasifyai-web", "aud": "wasifyai-api", "iat": now, "exp": now + 300,
            "sub": "desktop:local",
        }  # fmt: skip
        return {"authorization": f"Bearer {jwt.encode(claims, self.secret, algorithm='HS256')}"}

    def call(self, method: str, path: str, **more: Any) -> httpx.Response:
        return self.http.request(method, path, headers=self.headers(), **more)

    def close(self) -> None:
        self.http.close()
        if self.proc.stdin is not None:
            self.proc.stdin.close()  # the shell going away: the engine ends itself
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def wait_done(engine: Engine, session: str, limit_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        seen = engine.call("GET", f"{BASE}/sessions/{session}").json()
        if not seen["working"] and seen["state"] == "done":
            return seen
        time.sleep(0.5)
    engine.call("POST", f"{BASE}/sessions/{session}/stop")
    return {**engine.call("GET", f"{BASE}/sessions/{session}").json(), "timed_out": True}


def analyse(
    engine: Engine, project: Path, model: str, limit_s: float, limit_usd: float = 0.0
) -> dict[str, Any]:
    before = listing(project)
    body = {"folder": str(project), "model": model, "cost_limit_usd": limit_usd}
    made = engine.call("POST", f"{BASE}/sessions", json=body)
    if made.status_code != 201:
        return {"project": str(project), "error": made.text}
    session = made.json()["id"]
    began = time.monotonic()
    engine.call("POST", f"{BASE}/sessions/{session}/messages", json={"text": ASK})
    seen = wait_done(engine, session, limit_s)
    seconds = round(time.monotonic() - began, 1)
    turns = engine.call("GET", f"{BASE}/sessions/{session}/turns").json()["items"]
    after = listing(project)
    changed = sorted(
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    )
    return {
        "project": str(project),
        "files_listed": len(before),
        "session": session,
        "ended": seen.get("ended"),
        "timed_out": bool(seen.get("timed_out")),
        "seconds": seconds,
        "steps": turns[-1]["steps"] if turns else 0,
        "notes": turns[-1]["notes"] if turns else [],
        "cost_usd": seen.get("cost_usd"),
        "tokens_in": seen.get("tokens_in"),
        "tokens_out": seen.get("tokens_out"),
        "changed": changed,
        "answer": seen.get("answer", ""),
    }


def stops(engine: Engine, project: Path, model: str) -> list[dict[str, Any]]:
    made = engine.call("POST", f"{BASE}/sessions", json={"folder": str(project), "model": model})
    session = made.json()["id"]
    out = []
    for delay in (0.0, 0.5, 2.0, 5.0, 10.0):
        engine.call("POST", f"{BASE}/sessions/{session}/messages", json={"text": LONG_ASK})
        time.sleep(delay)
        working = engine.call("GET", f"{BASE}/sessions/{session}").json()["working"]
        began = time.monotonic()
        said = engine.call("POST", f"{BASE}/sessions/{session}/stop").json()
        took = round(time.monotonic() - began, 3)
        out.append(
            {
                "after_s": delay,
                "was_working": working,
                "stop_seconds": took,
                "stopped": said["stopped"],
                "ended": said["session"]["ended"],
                "still_working": said["session"]["working"],
            }
        )
    return out


def key_search(data: Path) -> dict[str, Any]:
    """Anything that looks like a provider's key, or the gateway's token, in what the coding
    engine could write or read of ours."""
    found: list[str] = []
    tokens = 0
    files = 0
    for folder in (data / "coding", data / "coding-fixed", data / "logs"):
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            files += 1
            try:
                blob = path.read_bytes()
            except OSError:
                continue
            if KEY_LIKE.search(blob):
                found.append(str(path.relative_to(data)))
            tokens += blob.count(b"wcg-")
    return {"files_searched": files, "files_with_a_key": found, "gateway_tokens_seen": tokens}


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--project", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--keychain", action="store_true", help="a cloud model: costs money")
    parser.add_argument("--limit-s", type=float, default=900.0, help="for one analysis")
    parser.add_argument("--no-stops", action="store_true")
    parser.add_argument("--limit-usd", type=float, default=0.0, help="for one session")
    args = parser.parse_args()
    projects = [Path(os.path.realpath(p.expanduser())) for p in args.project]
    engine = Engine(args.data, args.keychain)
    result: dict[str, Any] = {"model": args.model, "analyses": [], "stops": []}
    try:
        models = engine.call("GET", f"{BASE}/models").json()["items"]
        result["models"] = models
        for project in projects:
            one = analyse(engine, project, args.model, args.limit_s, args.limit_usd)
            result["analyses"].append(one)
            print(
                f"{project.name:28} {one.get('ended')!s:10} {one.get('seconds')!s:>7} s "
                f"{one.get('steps')!s:>3} steps  ${one.get('cost_usd')}  "
                f"changed: {len(one.get('changed', []))}",
                flush=True,
            )
            args.out.write_text(json.dumps(result, indent=1))
        if not args.no_stops:
            result["stops"] = stops(engine, projects[0], args.model)
            for s in result["stops"]:
                print(f"stop after {s['after_s']:4} s: {s['stop_seconds']} s -> {s['ended']}")
        result["coding_engine"] = engine.call("GET", "/desktop/coding-engine").json()
    finally:
        engine.close()
        result["key_search"] = key_search(args.data)
        args.out.write_text(json.dumps(result, indent=1))
    print(json.dumps(result["key_search"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
