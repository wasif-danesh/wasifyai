"""A stand-in for `audiocpp_server`, to test the engine without the real runtime or its models.

It speaks the part of the protocol the engine uses (see docs/spikes/voice-v0.md): `--version`,
`--config`, `/health`, `/v1/models` with `loaded` flags and one model resident at a time,
`/v1/audio/speech` and `/v1/audio/transcriptions/details`. Like the real one it answers a user's
mistake with HTTP 500."""

import io
import json
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RATE = 24000


def wav_bytes(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"\x00\x01" * int(RATE * seconds))
    return buf.getvalue()


def main() -> None:
    if "--version" in sys.argv:
        print("audio.cpp vTEST\nbackends: cpu")
        return
    cfg = json.load(open(sys.argv[sys.argv.index("--config") + 1]))
    models = {m["id"]: m for m in cfg["models"]}
    state = {"loaded": None, "speech": 0, "log": []}
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            pass

        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def fail(self, message):
            self.send(500, {"error": {"message": message, "type": "server_error"}})

        def do_GET(self):
            if self.path == "/health":
                return self.send(200, {"status": "ok"})
            if self.path == "/v1/models":
                data = [
                    {
                        "id": i,
                        "family": m["family"],
                        "task": m["task"],
                        "loaded": state["loaded"] == i,
                    }
                    for i, m in models.items()
                ]
                return self.send(200, {"object": "list", "data": data})
            if self.path == "/_last":
                return self.send(200, state.get("last") or {})
            self.send(404, {})

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("content-length", 0)))
            with lock:
                if self.path == "/v1/audio/speech":
                    req = json.loads(body)
                    m = models.get(req.get("model"))
                    if m is None:
                        return self.fail(f"unknown model id: {req.get('model')}")
                    if m["task"] not in ("tts", "vdes"):
                        return self.fail("prepare() requires an audio contract")
                    state["last"] = req
                    if m["task"] == "vdes" and not (req.get("options") or {}).get("instruct"):
                        return self.fail("voice design requires an instruction")
                    if m["family"] == "qwen3_tts" and m["task"] == "tts":
                        ref = req.get("voice_ref")
                        if not ref or not __import__("os").path.isfile(ref):
                            return self.fail("Qwen3 base TTS requires voice clone reference audio")
                        if not req.get("reference_text"):
                            return self.fail("reference_text is required")
                    if req.get("voice") not in (None, "af_heart", "am_adam"):
                        return self.fail(f"unknown Kokoro voice id: {req['voice']}")
                    allowed = {"speed", "seed"} | ({"instruct"} if m["task"] == "vdes" else set())
                    if set(req.get("options") or {}) - allowed:
                        return self.fail("unknown Kokoro TTS request option")
                    if req["input"].startswith("BOOM"):
                        return self.fail("failed to allocate buffer: out of memory")
                    if req["input"].startswith("SLOW"):
                        threading.Event().wait(30)
                    state["loaded"] = req["model"]
                    state["speech"] += 1
                    return self.send(200, wav_bytes(max(0.2, len(req["input"]) / 20)), "audio/wav")
                if self.path == "/v1/tasks/run":
                    req = json.loads(body)
                    m = models.get(req.get("model"))
                    if m is None or m["task"] != "gen":
                        return self.fail("unknown model id or not a music model")
                    r = req.get("request") or {}
                    state["last"] = req
                    if not r.get("text"):
                        return self.fail("text is required")
                    if "audio" in r and not __import__("os").path.isfile(r["audio"]):
                        return self.fail("source audio file not found")
                    seconds = float(
                        r.get("duration_seconds")
                        or (r.get("options") or {}).get("duration_sec")
                        or 0
                    )
                    if not seconds and "audio" not in r:
                        return self.fail("duration is required")
                    seconds = seconds or 3.0
                    if r["text"].startswith("BOOM"):
                        return self.fail("failed to allocate buffer")
                    state["loaded"] = req["model"]
                    data = wav_bytes(min(seconds, 3.0))
                    if r["text"].startswith("RAW"):
                        return self.send(200, data, "audio/wav")
                    import base64

                    return self.send(
                        200,
                        {"outputs": [{"id": "audio", "audio": base64.b64encode(data).decode()}]},
                    )
                if self.path == "/v1/audio/transcriptions/details":
                    if b"RIFF" not in body:
                        return self.fail("invalid WAV RIFF header")
                    name = body.split(b'name="model"\r\n\r\n', 1)[1].split(b"\r\n", 1)[0].decode()
                    if name not in models:
                        return self.fail(f"unknown model id: {name}")
                    state["loaded"] = name
                    words = [
                        ("Hello", 0, 12000),
                        ("there.", 12000, 24000),
                        ("Second", 30000, 36000),
                        ("sentence", 36000, 48000),
                        ("here.", 48000, 60000),
                    ]
                    return self.send(
                        200,
                        {
                            "text": "Hello there. Second sentence here.",
                            "words": [
                                {"word": w, "start_sample": a, "end_sample": b} for w, a, b in words
                            ],
                            "sample_rate": RATE,
                            "timing": {"audio_duration_ms": 2500},
                        },
                    )
            self.send(404, {})

    ThreadingHTTPServer((cfg["host"], cfg["port"]), H).serve_forever()


if __name__ == "__main__":
    main()
