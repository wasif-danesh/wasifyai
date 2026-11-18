"""Telling the speakers of a recording apart (ADR-0108, decision 8): NVIDIA's Streaming Sortformer
(4 speakers, v2.1) as ONNX, on ONNX Runtime, on the processor.

The model sees about ten seconds at a time (a chunk) together with what it kept of the meeting so
far (the speaker cache and a short queue, FIFO); our own code runs that loop. The loop, the
compression of the speaker cache and the post-processing follow NVIDIA's NeMo, as checked against
FluidAudio in spike MT0b (docs/spikes/meetings-mt0.md). The features (log-mel, 128 bands) are made
one chunk at a time from the WAV on disk, so a long meeting does not have to fit in memory:
whole-meeting features took 2.9 GB in the spike.

    Sortformer(path).run(wav, progress, stop)  -> Diarization(turns, speakers, seconds)
"""

import math
import mmap
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SR, NFFT, WIN, HOP, NMELS, PREEMPH = 16_000, 512, 400, 160, 128, 0.97
LOG_GUARD = np.float32(5.960464478e-8)
CHUNK, FIFO_LEN, SUB, EMB, NSPK = 124, 124, 8, 512, 4
CACHE_LEN, CACHE_PERIOD, BOOST_LATEST, CACHE_SIL = 188, 124, 0.05, 3
FRAME = 0.08  # seconds per output frame (HOP x SUB samples)
SIL_THR, MED_WIN = 0.2, 11
ONSET, OFFSET, PAD_ON, PAD_OFF, MIN_ON, MIN_OFF = 0.641, 0.561, 0.229, 0.079, 0.511, 0.296
STRIDE = CHUNK * SUB  # feature frames per chunk


class Stopped(Exception):
    """The person stopped the work."""


class BadAudio(Exception):
    """Not a 16 kHz, 16-bit, one-channel WAV (the converter makes one)."""


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    speaker: int  # 0..3, in the order the model found them


@dataclass(frozen=True)
class Diarization:
    turns: list[Turn]
    speakers: int  # how many speakers spoke
    seconds: float  # how long the recording is
    elapsed_s: float


# ---- the features -----------------------------------------------------------------------------


def _hz_to_mel(hz: float) -> float:
    if hz >= 1000.0:
        return 15.0 + math.log(hz / 1000.0) / (math.log(6.4) / 27.0)
    return hz / (200.0 / 3.0)


def _mel_to_hz(m: float) -> float:
    if m >= 15.0:
        return 1000.0 * math.exp(math.log(6.4) / 27.0 * (m - 15.0))
    return (200.0 / 3.0) * m


def _filterbank() -> np.ndarray:
    bins = NFFT // 2 + 1
    f = np.arange(bins, dtype=np.float64) * SR / NFFT
    pts = np.linspace(_hz_to_mel(0.0), _hz_to_mel(SR / 2.0), NMELS + 2)
    hz = np.array([_mel_to_hz(p) for p in pts])
    d = np.diff(hz)
    fb = np.zeros((NMELS, bins), dtype=np.float32)
    for i in range(NMELS):
        fb[i] = np.maximum(0.0, np.minimum((f - hz[i]) / d[i], (hz[i + 2] - f) / d[i + 1]))
        fb[i] *= 2.0 / (hz[i + 2] - hz[i])
    return fb


FB_T = _filterbank().T.copy()
WINDOW = np.zeros(NFFT, dtype=np.float32)
WINDOW[(NFFT - WIN) // 2 : (NFFT - WIN) // 2 + WIN] = np.hanning(WIN + 1)[:-1]


def frame_count(samples: int) -> int:
    """Feature frames of a recording of `samples` samples (centred frames, one per HOP)."""
    return samples // HOP + 1


def log_mel(x: np.ndarray, f0: int = 0, f1: int | None = None) -> np.ndarray:
    """Log-mel features of frames `f0`..`f1` of the recording `x` (float samples, or int16 read
    from disk), shaped (frames, 128). Frames are centred on `f * HOP` with zeros beyond the ends,
    after pre-emphasis of the whole signal, so any range equals the same rows of the whole."""
    n = len(x)
    if f1 is None:
        f1 = frame_count(n)
    s0, s1 = f0 * HOP - NFFT // 2 - 1, (f1 - 1) * HOP + NFFT // 2  # one more sample before
    seg = np.zeros(s1 - s0, dtype=np.float32)
    a, b = max(s0, 0), min(s1, n)
    if b > a:
        part = np.asarray(x[a:b])
        seg[a - s0 : b - s0] = part / 32768.0 if part.dtype == np.int16 else part
    e = seg[1:] - PREEMPH * seg[:-1]
    if s1 > n:  # beyond the end the signal is zeros after pre-emphasis, not before it
        e[max(n - s0 - 1, 0) :] = 0.0
    frames = np.lib.stride_tricks.sliding_window_view(e, NFFT)[::HOP][: f1 - f0]
    s = np.fft.rfft(frames * WINDOW, n=NFFT, axis=-1)
    power = (s.real**2 + s.imag**2).astype(np.float32)
    return np.log(power @ FB_T + LOG_GUARD).astype(np.float32)


class Wav:
    """A 16 kHz, 16-bit, mono WAV read from disk without loading it (`samples[a:b]`)."""

    def __init__(self, path: Path):
        self._f = open(path, "rb")  # noqa: SIM115 - closed by close()
        try:
            self._m = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError:  # an empty file
            self._f.close()
            raise BadAudio("The recording is empty.") from None
        m = self._m
        if m[:4] != b"RIFF" or m[8:12] != b"WAVE":
            self.close()
            raise BadAudio("The recording is not a WAV file.")
        pos, fmt, data = 12, None, None
        while pos + 8 <= len(m):
            cid, size = m[pos : pos + 4], struct.unpack("<I", m[pos + 4 : pos + 8])[0]
            if cid == b"fmt ":
                fmt = struct.unpack("<HHIIHH", m[pos + 8 : pos + 24])
            elif cid == b"data":
                data = (pos + 8, min(size, len(m) - pos - 8))
                break
            pos += 8 + size + (size & 1)
        if fmt is None or data is None:
            self.close()
            raise BadAudio("The WAV file has no sound in it.")
        tag, channels, rate, _, _, bits = fmt
        if tag != 1 or channels != 1 or rate != SR or bits != 16:
            self.close()
            raise BadAudio("The recording must be 16 kHz, 16-bit, one channel.")
        start, size = data
        self.samples = np.frombuffer(m, dtype="<i2", count=size // 2, offset=start)

    @property
    def seconds(self) -> float:
        return len(self.samples) / SR

    def close(self) -> None:
        self.samples = np.zeros(0, dtype=np.int16)
        try:
            self._m.close()
        except (AttributeError, BufferError):
            pass
        self._f.close()


# ---- the model and its streaming loop ---------------------------------------------------------


class _Stream:
    """The state the model carries from one chunk to the next."""

    def __init__(self, session: Any):
        self.s = session
        self.cache = np.zeros((1, 0, EMB), np.float32)
        self.cache_preds: np.ndarray | None = None
        self.fifo = np.zeros((1, 0, EMB), np.float32)
        self.fifo_preds = np.zeros((1, 0, NSPK), np.float32)
        self.sil_emb = np.zeros(EMB, np.float32)
        self.n_sil = 0

    def _sil(self, embs: np.ndarray, preds: np.ndarray) -> None:
        for i in np.nonzero(preds[0].sum(axis=1) < SIL_THR)[0]:
            self.n_sil += 1
            self.sil_emb = (self.sil_emb * (self.n_sil - 1) + embs[0, i]) / self.n_sil

    def _compress(self) -> None:
        assert self.cache_preds is not None
        p = self.cache_preds[0]
        n = p.shape[0]
        per = CACHE_LEN // NSPK - CACHE_SIL
        q = np.maximum(1.0 - p, 0.25)
        sc = np.log(np.maximum(p, 0.25)) - np.log(q)
        sc += np.sum(np.log(q), axis=1, keepdims=True) - math.log(0.5)
        neg = p <= 0.5
        sc[neg] = -np.inf
        pos = np.sum(sc > 0.0, axis=0)
        for k in range(NSPK):
            if pos[k] >= int(per * 0.5):
                sc[(~neg[:, k]) & (sc[:, k] <= 0.0), k] = -np.inf
        sc[CACHE_LEN:, :] += BOOST_LATEST
        for count, scale in ((int(per * 0.75), 2.0), (int(per * 1.5), 1.0)):
            b = scale * math.log(0.5)
            for k in range(NSPK):
                col = sc[:, k]
                for t in sorted(range(n), key=lambda t, c=col: (-c[t], t))[:count]:
                    if not np.isneginf(sc[t, k]):
                        sc[t, k] -= b
        ext = np.full((n + CACHE_SIL, NSPK), np.inf, np.float32)
        ext[:n] = sc
        et = ext.shape[0]
        flat = sorted(
            ((float(ext[t, k]), t, k) for t in range(et) for k in range(NSPK)),
            key=lambda it: (-it[0], it[1], it[2]),
        )
        picked = []
        for s, t, k in flat[:CACHE_LEN]:
            ninf = math.isinf(s) and s < 0
            picked.append((t, ninf or t >= n, (1 << 62) if ninf else k * et + t))
        picked.sort(key=lambda it: it[2])
        embs = np.zeros((1, CACHE_LEN, EMB), np.float32)
        preds = np.zeros((1, CACHE_LEN, NSPK), np.float32)
        for i, (t, off, _) in enumerate(picked):
            if off:
                embs[0, i] = self.sil_emb
            else:
                embs[0, i] = self.cache[0, t]
                preds[0, i] = self.cache_preds[0, t]
        self.cache, self.cache_preds = embs, preds

    def step(self, chunk: np.ndarray, n: int) -> np.ndarray:
        """Feed one chunk (1, STRIDE, 128) of which `n` frames are real; the speakers' chances
        for its output frames, shaped (frames, 4)."""
        preds, embs = self.s.run(
            ["spkcache_fifo_chunk_preds", "chunk_pre_encode_embs"],
            {
                "chunk": chunk,
                "chunk_lengths": np.array([n], np.int64),
                "spkcache": self.cache,
                "spkcache_lengths": np.array([self.cache.shape[1]], np.int64),
                "fifo": self.fifo,
                "fifo_lengths": np.array([self.fifo.shape[1]], np.int64),
            },
        )
        ct, ft = self.cache.shape[1], self.fifo.shape[1]
        valid = (n + SUB - 1) // SUB
        fp = preds[:, ct : min(ct + ft, preds.shape[1])]
        cp = preds[:, ct + ft : min(ct + ft + valid, preds.shape[1])]
        ce = embs[:, : min(valid, embs.shape[1])]
        self.fifo = np.concatenate([self.fifo, ce], axis=1)
        self.fifo_preds = np.concatenate([fp, cp], axis=1) if fp.shape[1] else cp
        if self.fifo.shape[1] > FIFO_LEN:
            pop = min(max(CACHE_PERIOD, CHUNK - FIFO_LEN + ft), self.fifo.shape[1])
            pe, pp = self.fifo[:, :pop], self.fifo_preds[:, :pop]
            self._sil(pe, pp)
            self.fifo, self.fifo_preds = self.fifo[:, pop:], self.fifo_preds[:, pop:]
            self.cache = np.concatenate([self.cache, pe], axis=1)
            if self.cache_preds is not None:
                self.cache_preds = np.concatenate([self.cache_preds, pp], axis=1)
            if self.cache.shape[1] > CACHE_LEN:
                if self.cache_preds is None:
                    self.cache_preds = np.concatenate([preds[:, :ct], pp], axis=1)
                self._compress()
        return np.asarray(cp[0])


# ---- from chances to turns --------------------------------------------------------------------


def median(p: np.ndarray, win: int = MED_WIN) -> np.ndarray:
    """A running median of each speaker's chances; near the ends the window is shorter."""
    h = win // 2
    t = p.shape[0]
    out = np.empty_like(p)
    if t > 2 * h:
        view = np.lib.stride_tricks.sliding_window_view(p, win, axis=0)  # (t-2h, k, win)
        out[h : t - h] = np.median(view, axis=-1)
        edges = list(range(h)) + list(range(t - h, t))
    else:
        edges = list(range(t))
    for i in edges:
        out[i] = np.median(p[max(i - h, 0) : i + h + 1], axis=0)
    return out


def turns_of(p: np.ndarray) -> list[Turn]:
    """Each speaker's turns, from their smoothed chances per frame (onset and offset with padding,
    too-short turns dropped, near gaps closed), sorted by start."""
    out: list[Turn] = []
    for k in range(p.shape[1]):
        found: list[tuple[float, float]] = []
        on, st = False, 0
        for t in range(p.shape[0] + 1):
            v = p[t, k] if t < p.shape[0] else -1.0
            if t < p.shape[0] and v >= ONSET and not on:
                on, st = True, t
            elif on and v < OFFSET:
                on = False
                a, b = max(st * FRAME - PAD_ON, 0.0), t * FRAME + PAD_OFF
                if b - a >= MIN_ON:
                    found.append((a, b))
        merged: list[tuple[float, float]] = []
        for a, b in found:
            if merged and a - merged[-1][1] < MIN_OFF:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        out += [Turn(round(a, 3), round(b, 3), k) for a, b in merged]
    return sorted(out, key=lambda x: (x.start, x.speaker))


class Sortformer:
    """The model, loaded once and used for one recording at a time."""

    def __init__(self, model: Path, threads: int = 0):
        import onnxruntime as ort

        so = ort.SessionOptions()
        if threads:
            so.intra_op_num_threads = threads
        so.log_severity_level = 3
        self._session = ort.InferenceSession(
            str(model), sess_options=so, providers=["CPUExecutionProvider"]
        )

    def run(
        self,
        wav: Path,
        progress: Callable[[float], None] | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> Diarization:
        """Who spoke when in `wav` (16 kHz mono 16-bit). `progress` hears 0..1 after each chunk;
        `stop` is asked before each chunk and ends the work with `Stopped`."""
        t0 = time.monotonic()
        audio = Wav(wav)
        try:
            seconds = audio.seconds
            total = frame_count(len(audio.samples))
            stream = _Stream(self._session)
            chunks = (total + STRIDE - 1) // STRIDE
            preds: list[np.ndarray] = []
            for i in range(chunks):
                if stop is not None and stop():
                    raise Stopped()
                a = i * STRIDE
                n = min(a + STRIDE, total) - a
                chunk = np.zeros((1, STRIDE, NMELS), np.float32)
                chunk[0, :n] = log_mel(audio.samples, a, a + n)
                preds.append(stream.step(chunk, n))
                if progress is not None:
                    progress((i + 1) / chunks)
        finally:
            audio.close()
        probs = np.concatenate(preds, axis=0) if preds else np.zeros((0, NSPK), np.float32)
        turns = turns_of(median(probs))
        return Diarization(
            turns=turns,
            speakers=len({t.speaker for t in turns}),
            seconds=round(seconds, 2),
            elapsed_s=round(time.monotonic() - t0, 2),
        )


def wav_bytes(samples: np.ndarray, start_s: float, end_s: float) -> bytes:
    """A piece of a recording (`Wav.samples`) as WAV bytes of its own (16 kHz mono 16-bit)."""
    a, b = max(0, int(start_s * SR)), min(len(samples), int(end_s * SR))
    data = np.asarray(samples[a:b], dtype="<i2").tobytes()
    head = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE", b"fmt ", 16, 1, 1, SR, SR * 2, 2,
        16, b"data", len(data),
    )  # fmt: skip
    return head + data


__all__ = [
    "BadAudio", "Diarization", "Sortformer", "Stopped", "Turn", "Wav", "frame_count", "log_mel",
    "median", "turns_of", "wav_bytes",
]  # fmt: skip
