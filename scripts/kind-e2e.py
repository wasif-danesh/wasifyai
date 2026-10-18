#!/usr/bin/env python3
"""Make something with the image and video products through the BFF of a running stack.

Works against the kind cluster (`make kind-up`, auth stub) or the Compose stack:

    uv run python scripts/kind-e2e.py [base_url]       # default http://localhost:3000

Each check starts a run, follows its server-sent events and requires the terminal `done` event.
Prints one line per product and exits 1 if any failed."""

import io
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import wave
import zlib

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000").rstrip("/")


def png(size: int = 256) -> bytes:
    rows = b"".join(
        b"\x00" + b"".join(bytes(((x * 255) // size, (y * 255) // size, 120)) for x in range(size))
        for y in range(size)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def wav(seconds: float = 3.0, rate: int = 16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(
            b"".join(struct.pack("<h", (i % 80 - 40) * 150) for i in range(int(seconds * rate)))
        )
    return out.getvalue()


def post(path: str, body: bytes, ctype: str, timeout: int = 60):
    req = urllib.request.Request(BASE + path, body, {"content-type": ctype}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def upload(product: str, kind: str, data: bytes, ctype: str) -> str:
    status, body = post(f"/api/products/{product}/uploads/{kind}", data, ctype)
    if status != 201:
        raise RuntimeError(f"{kind} upload answered {status}: {body[:200]!r}")
    return json.loads(body)["key"]


def events(req: urllib.request.Request, timeout: int):
    """Yield (event, data) until the stream ends."""
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ev = ""
        for raw in resp:
            line = raw.decode().strip()
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:") and ev:
                try:
                    yield ev, json.loads(line[5:])
                except ValueError:
                    continue


def run(product: str, payload: dict, approve: bool = False, timeout: int = 600) -> str:
    """Start a run; return a one-line outcome or raise with why it failed."""
    req = urllib.request.Request(
        f"{BASE}/api/products/{product}/runs",
        json.dumps({"input": payload}).encode(),
        {"content-type": "application/json", "accept": "text/event-stream"},
        method="POST",
    )
    run_id, last, detail = None, "", ""
    for ev, data in events(req, timeout):
        run_id = data.get("run_id") or run_id
        last = ev
        if ev == "error":
            raise RuntimeError(f"error event: {data.get('code')} {data.get('message')}")
        if ev == "done":
            out = data.get("outputs") or {}
            if out.get("status") == "refused":
                raise RuntimeError(f"refused: {out.get('refusal')}")
            detail = f"status={out.get('status')}"
        if ev == "interrupt" and approve and (data.get("value") or data).get("kind") != "job":
            break
    if last == "interrupt" and approve and run_id:
        resume = urllib.request.Request(
            f"{BASE}/api/runs/{run_id}/resume",
            json.dumps({"value": {"action": "approve"}}).encode(),
            {"content-type": "application/json", "accept": "text/event-stream"},
            method="POST",
        )
        for ev, data in events(resume, timeout):
            last = ev
            if ev == "error":
                raise RuntimeError(f"error event: {data.get('code')} {data.get('message')}")
            if ev == "done":
                detail = f"status={(data.get('outputs') or {}).get('status')}"
    if last != "done":
        raise RuntimeError(f"the run ended with '{last or 'nothing'}', not done")
    return detail


def checks():
    yield "image", lambda: run("wasifyai-image", {"mode": "text", "prompt": "a lighthouse at dawn"})
    yield (
        "video",
        lambda: run(
            "wasifyai-video",
            {"mode": "text", "prompt": "waves on a beach", "shape": "landscape", "seconds": 2},
        ),
    )


def main() -> int:
    failed = 0
    only = os.environ.get("E2E_ONLY", "").lower()  # e.g. E2E_ONLY="lip sync"
    for name, check in checks():
        if only and only not in name:
            continue
        started = time.monotonic()
        try:
            detail = check()
            print(f"✓ {name:15} {detail} ({time.monotonic() - started:.0f}s)")
        except Exception as exc:  # report every product, not only the first failure
            failed += 1
            print(f"✗ {name:15} {exc}")
    print(f"\n{failed} failed" if failed else "\nall made something")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
