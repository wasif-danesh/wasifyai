# ruff: noqa: E501  (prose in the docstrings is easier to read on one line)
"""Find the beats, downbeats, tempo and sections of one recording. Run by `music_analysis_setup` in the
tool's own environment (beat_this, librosa, PyTorch), never imported by the engine:

    python -I music_analysis_worker.py <song.wav> <model.ckpt> <out.json>

Sections have boundaries and an energy label, no names like verse or chorus: the tool does not give
them (`docs/spikes/creative-cs0.md`)."""

import json
import sys

SR = 22050
SECONDS_PER_SECTION = 15.0  # about what the spike's six sections in 90 s gave
MIN_SECTIONS, MAX_SECTIONS = 3, 16


def sections(y, beats, duration):  # type: ignore[no-untyped-def]
    import librosa  # type: ignore[import-not-found]
    import numpy as np

    wanted = int(np.clip(round(duration / SECONDS_PER_SECTION), MIN_SECTIONS, MAX_SECTIONS))
    if len(beats) <= wanted * 2:  # too few beats to tell parts apart
        starts = [0.0]
    else:
        frames = librosa.time_to_frames(beats, sr=SR)
        features = librosa.util.sync(
            np.vstack(
                [
                    librosa.feature.mfcc(y=y, sr=SR, n_mfcc=13),
                    librosa.feature.chroma_cqt(y=y, sr=SR),
                ]
            ),
            frames,
        )
        found = librosa.segment.agglomerative(features, wanted)
        at = beats[np.minimum(found, len(beats) - 1)]
        starts = sorted({0.0, *[float(t) for t in at if t > 0.5]})
    rms = librosa.feature.rms(y=y)[0]
    times = librosa.times_like(rms, sr=SR)
    out = []
    for a, b in zip(starts, [*starts[1:], duration], strict=True):
        inside = (times >= a) & (times < b)
        out.append(
            {
                "start": round(a, 2),
                "end": round(float(b), 2),
                "energy": round(float(rms[inside].mean()), 4) if inside.any() else 0.0,
            }
        )
    ranked = sorted(s["energy"] for s in out)
    low, high = ranked[len(ranked) // 3], ranked[-(len(ranked) // 3) - 1]
    for s in out:
        s["label"] = "high" if s["energy"] > high else "low" if s["energy"] < low else "mid"
    return out


def main() -> None:
    song, model, target = sys.argv[1:4]
    import librosa  # type: ignore[import-not-found]
    import numpy as np
    from beat_this.inference import File2Beats  # type: ignore[import-not-found]

    beats, downbeats = File2Beats(checkpoint_path=model, device="cpu", dbn=False)(song)
    beats, downbeats = np.asarray(beats, dtype=float), np.asarray(downbeats, dtype=float)
    y, _ = librosa.load(song, sr=SR, mono=True)
    duration = len(y) / SR
    gaps = np.diff(beats)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(
            {
                "seconds": round(duration, 3),
                "bpm": round(float(60 / np.median(gaps)), 1) if len(gaps) else 0.0,
                "beats": [round(float(t), 3) for t in beats],
                "downbeats": [round(float(t), 3) for t in downbeats],
                "sections": sections(y, beats, duration),
                "tool": "beat_this small0, librosa",
            },
            f,
        )


if __name__ == "__main__":
    main()
