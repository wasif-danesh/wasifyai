"""V0 spike: ONE audiocpp_server, several models, lazy load, max_loaded_models=1."""
import json, os, subprocess, sys, time, socket, tempfile, urllib.request, urllib.error, io, uuid, wave
from pathlib import Path
BIN = str(Path.home() / ".unsloth/audio.cpp/audiocpp_server")
LINKS = Path.home() / ".cache/huggingface/unsloth-audiocpp-links"
MODELS = {
    "kokoro": dict(family="kokoro_tts", task="tts", path=str(next(LINKS.glob("kokoro*/*.gguf")))),
    "parakeet": dict(family="parakeet_tdt", task="asr", path=str(next(LINKS.glob("parakeet*/*.gguf")))),
}
extra = json.loads(os.environ.get("V0_EXTRA", "{}"))
MODELS.update(extra)
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
d = Path(tempfile.mkdtemp(prefix="v0-"))
cfg = {"host": "127.0.0.1", "port": port, "backend": "metal", "lazy_load": True, "max_loaded_models": 1,
       "busy_timeout_ms": 0,
       "models": [dict(id=k, mode="offline", **v) for k, v in MODELS.items()]}
(d / "server.json").write_text(json.dumps(cfg))
log = open(d / "server.log", "wb")
t0 = time.time()
p = subprocess.Popen([BIN, "--config", str(d / "server.json"), "--no-ui"], stdout=log, stderr=subprocess.STDOUT, cwd=d)
def rss():
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(p.pid)], capture_output=True, text=True).stdout.strip()
    return int(out) / 1024 if out else 0
def call(path, body=None, data=None, headers=None, timeout=600):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data if data is not None else (json.dumps(body).encode() if body is not None else None),
                                 headers=headers or ({"content-type": "application/json"} if body is not None else {}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.headers.get("content-type"), r.read()
def log_(*a): print(*a, flush=True)
for _ in range(600):
    try:
        call("/health", timeout=2); break
    except Exception: time.sleep(0.2)
log_(f"server up in {time.time()-t0:.1f}s, rss {rss():.0f} MB")
log_("models:", call("/v1/models")[1].decode()[:600])
def wav_seconds(b):
    w = wave.open(io.BytesIO(b)); return w.getnframes() / w.getframerate()
def speak(model, text, **extra):
    t = time.time(); ct, b = call("/v1/audio/speech", {"model": model, "input": text, **extra}); dt = time.time() - t
    return b, dt
def transcribe(model, wav):
    boundary = uuid.uuid4().hex
    parts = []
    for name, val in (("model", model),):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + wav + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    t = time.time(); ct, b = call("/v1/audio/transcriptions", data=b"".join(parts), headers={"content-type": f"multipart/form-data; boundary={boundary}"}); dt = time.time() - t
    return b.decode(), dt
TEXT = "The marketing budget for the launch is three hundred and fifty thousand dollars."
try:
    log_("voices:", call("/v1/audio/voices?model=kokoro")[1].decode()[:300])
except Exception as e: log_("voices err", e)
for i in range(3):
    wav, dt = speak("kokoro", TEXT, voice="af_heart")
    log_(f"TTS #{i}: {dt:.2f}s for {wav_seconds(wav):.1f}s audio, rss {rss():.0f} MB")
    if i == 0: keep = wav
(d / "out.wav").write_bytes(keep)
for i in range(2):
    txt, dt = transcribe("parakeet", keep)
    log_(f"STT #{i} (switch from tts): {dt:.2f}s rss {rss():.0f} MB -> {txt[:160]}")
for i in range(2):
    wav, dt = speak("kokoro", TEXT, voice="af_heart")
    log_(f"TTS again #{i}: {dt:.2f}s rss {rss():.0f} MB")
for name, v in extra.items():
    pass
if os.environ.get("V0_DESIGN"):
    pass
print("log tail:", (d / "server.log").read_text()[-1500:])
p.terminate(); p.wait(10)
