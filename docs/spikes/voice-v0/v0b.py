import json, os, subprocess, sys, time, socket, tempfile, urllib.request, urllib.error, io, wave, threading, hashlib
from pathlib import Path
exec(open("v0/v0.py").read().split("TEXT = ")[0].replace('log_("models:"', 'pass #'))  # reuse server start + helpers
def loaded():
    return {m["id"]: m["loaded"] for m in json.loads(call("/v1/models")[1])["data"]}
def err(fn):
    try: fn(); return "ok"
    except urllib.error.HTTPError as e: return f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e: return f"{type(e).__name__}: {e}"
TEXT = "Hello there, this is a test of the voice."
log_("start", loaded())
w1, _ = speak("kokoro", TEXT, voice="af_heart"); log_("after tts", loaded(), f"{rss():.0f} MB")
w2, _ = speak("kokoro", TEXT, voice="am_adam"); log_("other voice differs:", hashlib.md5(w1).hexdigest() != hashlib.md5(w2).hexdigest(), len(w1), len(w2))
log_("bad voice:", err(lambda: speak("kokoro", TEXT, voice="nope")))
log_("bad option:", err(lambda: speak("kokoro", TEXT, options={"nonsense": 1})))
log_("speed 1.5:", f"{wav_seconds(speak('kokoro', TEXT, voice='af_heart', options={'speed': 1.5})[0]):.2f}s vs {wav_seconds(w1):.2f}s")
log_("unknown model:", err(lambda: speak("ghost", TEXT)))
log_("wrong task (asr model for speech):", err(lambda: speak("parakeet", TEXT)))
txt, dt = transcribe("parakeet", w1); log_("after stt", loaded(), f"{rss():.0f} MB", txt[:80])
# concurrent: two TTS requests while kokoro must reload
res = {}
def go(n): 
    t = time.time(); b, _ = speak("kokoro", TEXT, voice="af_heart"); res[n] = time.time() - t
ths = [threading.Thread(target=go, args=(i,)) for i in range(2)]
[t.start() for t in ths]; [t.join() for t in ths]
log_("two concurrent tts (kokoro cold):", {k: round(v, 2) for k, v in res.items()}, loaded())
# long text
long = " ".join([TEXT] * 12)
b, dt = speak("kokoro", long, voice="af_heart"); log_(f"long text {len(long)} chars: {dt:.2f}s -> {wav_seconds(b):.1f}s audio")
print((d/"server.log").read_text().count("error"), "error lines in log")
p.terminate(); p.wait(10)
