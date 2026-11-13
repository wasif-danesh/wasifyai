"""A real Video Builder video through the web API (what the web screen calls): a title composition
is made, its words are checked on the worker's sandboxed browser, a still is drawn, and a video is
rendered and read back. Run it with the stack up (`make dev`) and the workers running
(`scripts/worker.sh start`).

    uv run python scripts/web_builder_check.py"""

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_media_check import call  # noqa: E402

BASE = "/products/wasifyai-video/builder"


def get(path: str):
    with call(BASE + path) as r:
        return json.loads(r.read())


def post(path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else b""
    with call(BASE + path, data, {"content-type": "application/json"}, 600) as r:
        return json.loads(r.read())


def main() -> int:
    status = get("/status")
    print(f"ready: {status['ready']} ({status.get('problem')}), place: {status.get('place')}")
    if not status["ready"]:
        return 2
    made = post("/projects", {"template": "title", "slots": {
        "title": "Launch day", "subtitle": "Wasify AI is here", "theme": "sunrise"}})  # fmt: skip
    print("project", made["id"][:8], made["title"])
    t0 = time.monotonic()
    report = post(f"/projects/{made['id']}/check")
    print(f"check: {report['ok']} ({report['checked']} words) in {time.monotonic() - t0:.1f} s")
    if not report["ok"]:
        print(report["message"])
        return 1
    with call(f"{BASE}/projects/{made['id']}/preview", timeout=300) as r:
        still = r.read()
    print("preview", len(still) // 1024, "KB", still[:4])
    render = post(f"/projects/{made['id']}/render")
    t0 = time.monotonic()
    while render["status"] == "working":
        time.sleep(3)
        render = get(f"/renders/{render['id']}")
        print(f"  {render['progress']:.0%} {render.get('stage') or ''}   ", end="\r", flush=True)
    secs = time.monotonic() - t0
    print(f"\nrender {render['status']} in {secs:.0f} s, error: {render.get('error')}")
    if render["status"] != "done":
        return 1
    with urllib.request.urlopen(render["video_url"], timeout=120) as r:  # a signed link
        video = r.read()
    print("video", len(video) // 1024, "KB", video[4:12])
    return 0 if video[4:8] == b"ftyp" else 1


if __name__ == "__main__":
    sys.exit(main())
