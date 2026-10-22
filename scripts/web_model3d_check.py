"""A real 3D model through the web API (what the web screen calls): a picture is added and cut
out, a model is made on the engine worker, and the GLB is read back. Run it with the stack up
(`make dev`) and the workers running (`scripts/worker.sh start`). It takes five to twenty-five
minutes.

    uv run python scripts/web_model3d_check.py [path/to/picture]"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_media_check import FIXTURES, call  # noqa: E402

BASE = "/products/wasifyai-model3d/m3d"


def get(path: str):
    with call(BASE + path) as r:
        return json.loads(r.read())


def post(path: str, body: bytes, content_type: str):
    with call(BASE + path, body, {"content-type": content_type}, 120) as r:
        return json.loads(r.read())


def main() -> int:
    picture = Path(sys.argv[1]) if len(sys.argv) > 1 else FIXTURES / "product.jpg"
    status = get("/status")
    print(f"3D ready: {status['ready']} ({status.get('problem')}), place: {status.get('place')}")
    if not status["ready"]:
        return 2
    row = post("/inputs?name=" + picture.name, picture.read_bytes(), "image/jpeg")
    while row["status"] == "checking":
        time.sleep(2)
        row = get(f"/inputs/{row['id']}")
        print(f"  picture: {row['status']} {row.get('stage') or ''}", end="\r", flush=True)
    print(f"\npicture {row['status']}: {[c['message'][:60] for c in row['checks']]}")
    if not row["can_go_on"]:
        return 1
    made = post("/models", json.dumps({"input_id": row["id"], "rights": True,
                                       "title": "Check", "detail": "light"}).encode(),
                "application/json")  # fmt: skip
    t0 = time.monotonic()
    while made["status"] == "working":
        time.sleep(10)
        made = get(f"/models/{made['id']}")
        print(f"  {made['progress']:.0%} {made['stage']}   ", end="\r", flush=True)
    print(f"\nmodel {made['status']} in {time.monotonic() - t0:.0f} s, error: {made['error']}")
    if made["status"] != "done":
        return 1
    with call(f"{BASE}/models/{made['id']}/file") as r:
        glb = r.read()
        print("GLB", len(glb) // 1024, "KB, starts", glb[:4], r.headers.get("content-disposition"))
    return 0 if glb[:4] == b"glTF" else 1


if __name__ == "__main__":
    sys.exit(main())
