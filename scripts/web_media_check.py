"""Every image and video mode once, through the web API (what the web screens call), against a
real ComfyUI: Create, Edit, Inpaint and Reference; then Make a video, Animate and Extend. Run it
with the stack up (`make dev`) and the media worker running on this Mac (`scripts/worker.sh
start`), which replaces the stack's placeholder worker:

    uv run python scripts/web_media_check.py          # images, then video (video takes minutes)
    uv run python scripts/web_media_check.py images   # only the pictures
    uv run python scripts/web_media_check.py video

A result under 20 KB or made in under 3 s is reported as a placeholder, because the stack's own
worker makes those when the Mac's worker is not running."""

import base64
import hashlib
import hmac
import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "products" / "wasifyai-voice" / "wasifyai_voice" / "fixtures"
API = os.environ.get("API_URL", "http://localhost:8000")


def env(key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} is not set")


def token() -> str:
    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    now = int(time.time())
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = {"iss": "wasifyai-web", "aud": "wasifyai-api", "sub": "desktop:local",
              "iat": now, "exp": now + 7200}  # fmt: skip
    body = b64(json.dumps(claims).encode())
    sig = hmac.new(env("API_AUTH_SECRET").encode(), f"{head}.{body}".encode(), hashlib.sha256)
    return f"{head}.{body}.{b64(sig.digest())}"


TOKEN = token()


def call(
    path: str, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 60
):
    req = urllib.request.Request(
        API + path, data=data, headers={"Authorization": f"Bearer {TOKEN}", **(headers or {})}
    )
    return urllib.request.urlopen(req, timeout=timeout)


def upload(product: str, data: bytes, content_type: str) -> str:
    with call(f"/products/{product}/uploads/images", data, {"content-type": content_type}) as r:
        return json.loads(r.read())["key"]


def mask_png(width: int, height: int) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("L", (width, height), 0)
    ImageDraw.Draw(img).rectangle(
        (width // 4, height // 4, width * 3 // 4, height * 3 // 4), fill=255
    )
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def run(product: str, payload: dict) -> tuple[dict, float]:
    """Start a run and read its events until it ends: (the `done` data, seconds)."""
    t0 = time.monotonic()
    body = json.dumps({"input": payload}).encode()
    event, last = "", {}
    with call(
        f"/products/{product}/runs", body, {"content-type": "application/json"}, 3 * 3600
    ) as r:
        for raw in r:
            line = raw.decode().rstrip("\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:") and event:
                data = json.loads(line[5:])
                if event == "job_progress" and data.get("progress") is not None:
                    print(
                        f"    {data.get('status')} {data.get('progress'):.0%}", end="\r", flush=True
                    )
                if event in ("done", "error", "refused"):
                    last = {"event": event, **data, **(data.get("outputs") or {})}
    return last, time.monotonic() - t0


def fetch(url: str) -> bytes:
    full = url if url.startswith("http") else API + url
    with urllib.request.urlopen(full, timeout=120) as r:
        return r.read()


def check(name: str, product: str, payload: dict, url_key: str, results: list) -> dict:
    print(f"  {name} ...", flush=True)
    try:
        out, secs = run(product, payload)
    except Exception as e:
        results.append((name, "FAILED", str(e)))
        return {}
    if out.get("event") != "done":
        results.append(
            (name, "FAILED", f"{out.get('event')}: {out.get('message') or out.get('code')}")
        )
        return {}
    data = fetch(out[url_key])
    verdict = "ok" if len(data) > 20_000 and secs > 3 else "PLACEHOLDER?"
    results.append((name, verdict, f"{len(data) / 1024:.0f} KB in {secs:.0f} s"))
    return out


def main(which: set[str]) -> int:
    results: list[tuple[str, str, str]] = []
    image, video = "wasifyai-image", "wasifyai-video"
    street = (FIXTURES / "street.jpg").read_bytes()
    if not which or "images" in which:
        print("images")
        prompt = "a red ceramic teapot on a wooden table"
        check(
            "create",
            image,
            {"mode": "text", "prompt": prompt, "size": "square"},
            "image_url",
            results,
        )
        key = upload(image, street, "image/jpeg")
        edit = {"mode": "image", "prompt": "the same street at night, lights on", "image_key": key}
        check("edit", image, edit, "image_url", results)
        from PIL import Image

        w, h = Image.open(io.BytesIO(street)).size
        key = upload(image, street, "image/jpeg")
        mask = upload(image, mask_png(w, h), "image/png")
        paint = {"mode": "inpaint", "prompt": "a parked red bicycle", "image_key": key,
                 "mask_key": mask}  # fmt: skip
        check("inpaint", image, paint, "image_url", results)
        k1 = upload(image, (FIXTURES / "person.jpg").read_bytes(), "image/jpeg")
        k2 = upload(image, (FIXTURES / "product.jpg").read_bytes(), "image/jpeg")
        both = {"mode": "reference", "size": "square", "image_key": k1, "image2_key": k2,
                "prompt": "the person from picture 1 holding the product from picture 2",
                }  # fmt: skip
        check("reference", image, both, "image_url", results)
    if not which or "video" in which:
        print("video (each clip takes minutes)")
        text = {"mode": "text", "prompt": "a fox walking through snow", "seconds": 5,
                "shape": "landscape"}  # fmt: skip
        clip = check("make a video", video, text, "video_url", results)
        key = upload(video, street, "image/jpeg")
        move = {"mode": "image", "prompt": "cars drive by slowly", "seconds": 5, "image_key": key}
        check("animate", video, move, "video_url", results)
        source = clip.get("video_id") or clip.get("videoId")
        if source:
            more = {"mode": "extend", "prompt": "the fox keeps walking", "seconds": 5,
                    "source_id": source}  # fmt: skip
            check("extend", video, more, "video_url", results)
    print()
    width = max((len(n) for n, _, _ in results), default=0)
    for name, verdict, detail in results:
        print(f"{name:<{width}}  {verdict:<12} {detail}")
    return 1 if any(v == "FAILED" for _, v, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main(set(sys.argv[1:])))
