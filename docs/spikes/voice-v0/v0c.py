import json, os, subprocess, sys, time, socket, tempfile, urllib.request, urllib.error, io, wave, hashlib
from pathlib import Path
M = Path("v0/models").resolve()
extra = {
    "qwen_base": dict(family="qwen3_tts", task="tts", path=str(M / "qwen3-tts-12hz-0.6b-base-q8_0.gguf")),
    "qwen_design": dict(family="qwen3_tts", task="vdes", path=str(M / "qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf")),
    "voxcpm2": dict(family="voxcpm2", task="tts", path=str(M / "voxcpm2-q8_0.gguf")),
}
os.environ["V0_EXTRA"] = json.dumps(extra)
src = open("v0/v0.py").read().split("TEXT = ")[0].replace('log_("models:"', 'pass #')
exec(src)
def loaded():
    return [k for k, v in json.loads(call("/v1/models")[1])["data"] and {m["id"]: m["loaded"] for m in json.loads(call("/v1/models")[1])["data"]}.items() if v]
def err(fn):
    try: return fn()
    except urllib.error.HTTPError as e: return f"HTTP {e.code}: {e.read().decode()[:240]}"
    except Exception as e: return f"{type(e).__name__}: {e}"
def stt(wav):
    r = err(lambda: transcribe("parakeet", wav))
    return r[0].split('"text":"')[1].split('","timing')[0] if isinstance(r, tuple) else r
def step(label, fn):
    t = time.time(); r = err(fn); dt = time.time() - t
    if isinstance(r, bytes):
        log_(f"{label}: {dt:.2f}s -> {wav_seconds(r):.1f}s audio | rss {rss():.0f} MB | loaded {loaded()}")
    else:
        log_(f"{label}: {dt:.2f}s -> {str(r)[:260]}")
    return r
REF = "The marketing budget for the launch is three hundred and fifty thousand dollars."
ref, _ = speak("kokoro", REF, voice="af_heart")
refpath = str(d / "ref.wav"); open(refpath, "wb").write(ref)
SAY = "Our new product ships in March, and the team is very excited about it."
out = {}
out["qb1"] = step("qwen_base clone, cold", lambda: speak("qwen_base", SAY, voice_ref=refpath, reference_text=REF)[0])
out["qb2"] = step("qwen_base clone, warm", lambda: speak("qwen_base", SAY, voice_ref=refpath, reference_text=REF)[0])
step("qwen_base without a reference", lambda: speak("qwen_base", SAY)[0])
out["qd1"] = step("qwen_design, cold", lambda: speak("qwen_design", SAY, options={"instruct": "A deep, calm, elderly man with a slow, warm British voice."})[0])
out["qd2"] = step("qwen_design other voice, warm", lambda: speak("qwen_design", SAY, options={"instruct": "A bright, energetic young woman speaking quickly."})[0])
out["v1"] = step("voxcpm2 plain, cold", lambda: speak("voxcpm2", SAY)[0])
out["v2"] = step("voxcpm2 clone, warm", lambda: speak("voxcpm2", SAY, voice_ref=refpath, reference_text=REF)[0])
out["v3"] = step("voxcpm2 design (instruct)", lambda: speak("voxcpm2", SAY, options={"instruct": "A young woman with a gentle, soft voice"})[0])
for k, v in out.items():
    if isinstance(v, bytes): log_(f"  heard [{k}]: {stt(v)}")
step("swap back to kokoro", lambda: speak("kokoro", SAY, voice="af_heart")[0])
step("swap to qwen_design", lambda: speak("qwen_design", SAY, options={"instruct": "A calm narrator."})[0])
step("swap to voxcpm2", lambda: speak("voxcpm2", SAY)[0])
r = step("stt after voxcpm2", lambda: transcribe("parakeet", out["qb2"])[0] if isinstance(out["qb2"], bytes) else "")
log_("log lines with backend:", [l for l in (d/'server.log').read_text().splitlines() if 'backend' in l.lower() and 'metal' in l.lower()][:2])
for k, v in out.items():
    if isinstance(v, bytes): open(d / f"{k}.wav", "wb").write(v)
log_("wavs in", d)
p.terminate(); p.wait(10)
