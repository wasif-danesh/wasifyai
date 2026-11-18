"""Voiceprints (ADR-0108 decision 11): 3D-Speaker's ERes2Net (VoxCeleb) as ONNX, on ONNX Runtime,
the
same file on every platform, so a voice saved on one computer is known on another.

A voiceprint is 192 numbers, made from a stretch of one person's speech. Two voiceprints of the same
person are close (cosine about 0.6 to 0.8 across meetings in spike MT0b); of different people,
further
(about 0.2 to 0.4). The model takes Kaldi's 80-band log filterbank of 16 kHz sound with each band's
mean
taken out (the model's own metadata: `feature_normalize_type: global-mean`). It is computed here
with
numpy exactly as sherpa-onnx's extractor, which the spike measured with, computes it: filters from
20 Hz
to 7,600 Hz and frames centred on every 10 ms with the ends mirrored (Kaldi's `snip_edges` off). The
two
give the same voiceprint (cosine 1.000, `docs/spikes/meetings-mt3.md`)."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

SR = 16000
DIM = 192
FRAME = 400  # 25 ms
SHIFT = 160  # 10 ms
FFT = 512
BANDS = 80
LOW_HZ = 20.0
HIGH_HZ = 7600.0  # sherpa-onnx's default (Nyquist less 400 Hz)
MIN_SPEECH_S = 1.0  # shorter than this says too little about a voice
MOST_SPEECH_S = 30.0  # enough for one voiceprint: more is cut, to keep it quick


def _mel(hz: np.ndarray | float) -> np.ndarray:
    return 1127.0 * np.log(1.0 + np.asarray(hz, dtype=np.float64) / 700.0)


def _bank() -> np.ndarray:
    """Kaldi's triangular mel filters, (BANDS, FFT/2 + 1)."""
    lo, hi = _mel(LOW_HZ), _mel(HIGH_HZ)
    centres = lo + (hi - lo) * np.arange(BANDS + 2) / (BANDS + 1)
    bins = _mel(np.arange(FFT // 2 + 1) * SR / FFT)
    out = np.zeros((BANDS, FFT // 2 + 1))
    for m in range(BANDS):
        left, mid, right = centres[m], centres[m + 1], centres[m + 2]
        up = (bins - left) / (mid - left)
        down = (right - bins) / (right - mid)
        out[m] = np.maximum(0.0, np.minimum(up, down))
    out[:, -1] = 0.0  # Kaldi leaves out the Nyquist bin
    return out


_BANK = _bank()
_WINDOW = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(FRAME) / (FRAME - 1))) ** 0.85  # Povey


def features(wav: np.ndarray) -> np.ndarray:
    """(frames, 80) log mel filterbank, each band's mean taken out. `wav` is float, -1 to 1,
    16 kHz."""
    x = np.asarray(wav, dtype=np.float64)
    if len(x) < FRAME:
        return np.zeros((0, BANDS), dtype=np.float32)
    # a frame centred on every 10 ms; the ends mirrored where a frame runs past them
    n = (len(x) + SHIFT // 2) // SHIFT
    idx = (SHIFT * np.arange(n) + SHIFT // 2 - FRAME // 2)[:, None] + np.arange(FRAME)[None, :]
    idx = np.where(idx < 0, -idx - 1, idx)
    idx = np.where(idx >= len(x), 2 * len(x) - 1 - idx, idx)
    frames = x[idx]
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate(
        [frames[:, :1] * (1 - 0.97), frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1
    )
    frames = frames * _WINDOW
    power = np.abs(np.fft.rfft(frames, n=FFT)) ** 2
    fb = np.log(np.maximum(power @ _BANK.T, np.finfo(np.float32).eps))
    fb -= fb.mean(axis=0, keepdims=True)
    return fb.astype(np.float32)


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return (v / n).astype(np.float32) if n > 0 else v.astype(np.float32)


class Voiceprints:
    """The voiceprint model, loaded once."""

    def __init__(self, path: Path) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        self._session: Any = ort.InferenceSession(
            str(path), opts, providers=["CPUExecutionProvider"]
        )
        self._input = self._session.get_inputs()[0].name

    def of(self, wav: np.ndarray) -> np.ndarray | None:
        """One voiceprint (unit length) of a stretch of one person's speech; None when too short."""
        if len(wav) < MIN_SPEECH_S * SR:
            return None
        feats = features(wav[: int(MOST_SPEECH_S * SR)])
        out = self._session.run(None, {self._input: feats[None, :, :]})[0]
        return unit(np.asarray(out, dtype=np.float32).reshape(-1))

    def of_spans(self, wav: np.ndarray, spans: Sequence[tuple[float, float]]) -> np.ndarray | None:
        """One voiceprint from several stretches of the same person, joined (longest first, up to
        MOST_SPEECH_S)."""
        parts: list[np.ndarray] = []
        total = 0
        for a, b in sorted(spans, key=lambda s: s[0] - s[1]):
            piece = wav[int(a * SR) : int(b * SR)]
            parts.append(piece)
            total += len(piece)
            if total >= MOST_SPEECH_S * SR:
                break
        if not parts:
            return None
        return self.of(np.concatenate(parts))


__all__ = ["DIM", "MIN_SPEECH_S", "Voiceprints", "features", "unit"]
