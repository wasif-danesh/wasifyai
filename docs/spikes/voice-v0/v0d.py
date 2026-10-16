import json, os, hashlib
exec(open("v0/v0c.py").read().split("REF = ")[0])
import numpy as np
def f0(b):
    w = wave.open(io.BytesIO(b)); sr = w.getframerate(); x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768
    n = int(0.04 * sr); vals = []
    for i in range(0, len(x) - 2 * n, n):
        s = x[i:i + n]
        if np.sqrt((s ** 2).mean()) < 0.02: continue
        s = s - s.mean(); ac = np.correlate(s, s, "full")[n - 1:]; lo, hi = int(sr / 400), int(sr / 70); k = lo + np.argmax(ac[lo:hi])
        if ac[k] > 0.4 * ac[0]: vals.append(sr / k)
    return round(float(np.median(vals)), 1) if vals else 0
SAY = "Our new product ships in March, and the team is very excited about it."
a, _ = speak("voxcpm2", SAY)
b, _ = speak("voxcpm2", SAY, options={"instruct": "A young woman with a gentle, soft voice"})
c, dt = speak("voxcpm2", "(A deep, calm elderly man with a slow British voice)" + SAY)
e, _ = speak("voxcpm2", "(A bright, energetic young woman speaking quickly)" + SAY)
log_("same bytes with/without instruct option:", hashlib.md5(a).digest() == hashlib.md5(b).digest())
log_("f0 plain", f0(a), "| paren-design man", f0(c), "| paren-design woman", f0(e), "| seconds", wav_seconds(c), wav_seconds(e))
p.terminate(); p.wait(10)
