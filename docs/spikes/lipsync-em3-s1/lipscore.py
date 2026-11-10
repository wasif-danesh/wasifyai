"""A rough lip sync score: how well the mouth's opening follows the voice's loudness.

Run with MuseTalk's environment (it has face-alignment): python lipscore.py clip.mp4 [...]
For each frame, the inner lips' gap (landmarks 62-66 / 61-67 / 63-65) over the face height; the voice's loudness per
frame (RMS, 25 fps). Prints the best correlation within +-4 frames and its lag (positive: the mouth is late), and
how much the mouth moves at all (the spread of the gap)."""

import subprocess
import sys
import tempfile

import cv2
import face_alignment
import numpy as np


def frames(path):
    cap = cv2.VideoCapture(path)
    while True:
        ok, f = cap.read()
        if not ok:
            break
        yield cv2.cvtColor(f, cv2.COLOR_BGR2RGB)


def loudness(path, n):
    with tempfile.NamedTemporaryFile(suffix=".raw") as t:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", t.name],
                       check=True)
        a = np.frombuffer(open(t.name, "rb").read(), np.int16).astype(np.float32)
    hop = 16000 // 25
    return np.array([np.sqrt(np.mean(a[i * hop:(i + 1) * hop] ** 2) + 1e-9) for i in range(n)])


def score(path, fa):
    gaps, last = [], None
    for f in frames(path):
        lm = fa.get_landmarks(f)
        if lm:
            p = lm[0]
            gap = np.mean([np.linalg.norm(p[a] - p[b]) for a, b in ((62, 66), (61, 67), (63, 65))])
            last = gap / (np.max(p[:, 1]) - np.min(p[:, 1]))
        gaps.append(last if last is not None else 0.0)
    g = np.array(gaps)
    v = loudness(path, len(g))
    best = (-1.0, 0)
    for lag in range(-4, 5):
        a, b = (g[lag:], v[: len(v) - lag]) if lag >= 0 else (g[:lag], v[-lag:])
        c = float(np.corrcoef(a, b)[0, 1])
        if c > best[0]:
            best = (c, lag)
    return {"clip": path.rsplit("/", 1)[-1], "corr": round(best[0], 3), "lag_frames": best[1],
            "mouth_spread": round(float(g.std()), 4), "frames": len(g)}


if __name__ == "__main__":
    fa = face_alignment.FaceAlignment(face_alignment.LandmarksType.TWO_D, device="cpu")
    for p in sys.argv[1:]:
        print(score(p, fa), flush=True)
