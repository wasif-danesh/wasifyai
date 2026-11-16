"""A meeting recorded in the app (ADR-0108 decision 4): one WAV with two channels, the microphone
("You") first and the computer's sound ("Others") second, 16 kHz, 16-bit, written by the window's
shell. It is split into one file per channel, for the speaker model and the transcriber, and one
file of both together, for playing back."""

import struct
from pathlib import Path

import numpy as np

from wasifyai_meetings.sortformer import SR, BadAudio

CHUNK_FRAMES = SR * 30  # read and written 30 s at a time: a long meeting is not loaded whole


def _header(frames: int, channels: int = 1) -> bytes:
    size = frames * channels * 2
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + size, b"WAVE", b"fmt ", 16, 1, channels, SR,
        SR * 2 * channels, 2 * channels, 16, b"data", size,
    )  # fmt: skip


def _data_of(path: Path) -> tuple[int, int, int]:
    """(channels, offset of the samples, their size in bytes) of a 16 kHz, 16-bit WAV."""
    with path.open("rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise BadAudio("The recording is not a WAV file.")
        fmt = None
        while True:
            chunk = f.read(8)
            if len(chunk) < 8:
                raise BadAudio("The recording has no sound in it.")
            cid, size = chunk[:4], struct.unpack("<I", chunk[4:])[0]
            if cid == b"fmt ":
                fmt = struct.unpack("<HHIIHH", f.read(16))
                f.seek(size - 16 + (size & 1), 1)
            elif cid == b"data":
                if fmt is None:
                    raise BadAudio("The recording has no sound in it.")
                tag, channels, rate, _, _, bits = fmt
                if tag != 1 or rate != SR or bits != 16 or channels not in (1, 2):
                    raise BadAudio("The recording must be 16 kHz, 16-bit, one or two channels.")
                start = f.tell()
                total = path.stat().st_size - start
                # a recording the app was closed on has no size written: take what is there
                size = total if size in (0, 0xFFFFFFFF) or size > total else size
                return channels, start, size - size % (2 * channels)
            else:
                f.seek(size + (size & 1), 1)


def split(src: Path, you: Path, others: Path, both: Path) -> float:
    """Write the two channels of `src` as one-channel WAVs, and both mixed into one; the seconds.
    A one-channel recording is "You" only, with a silent "Others"."""
    channels, start, size = _data_of(src)
    frames = size // (2 * channels)
    outs = [p.open("wb") for p in (you, others, both)]
    try:
        for o in outs:
            o.write(_header(frames))
        with src.open("rb") as f:
            f.seek(start)
            left = frames
            while left > 0:
                n = min(CHUNK_FRAMES, left)
                raw = np.frombuffer(f.read(n * 2 * channels), dtype="<i2")
                n = len(raw) // channels
                if n == 0:
                    break
                x = raw[: n * channels].reshape(n, channels).astype(np.int32)
                mine = x[:, 0]
                theirs = x[:, 1] if channels == 2 else np.zeros(n, dtype=np.int32)
                mixed = np.clip((mine + theirs), -32768, 32767)
                outs[0].write(mine.astype("<i2").tobytes())
                outs[1].write(theirs.astype("<i2").tobytes())
                outs[2].write(mixed.astype("<i2").tobytes())
                left -= n
    finally:
        for o in outs:
            o.close()
    return frames / SR


def loud(path: Path, floor: float = 0.002) -> bool:
    """Whether a one-channel recording has any sound above `floor` (a share of full scale): the
    computer's channel is silent when nothing played, or when the Mac did not allow its capture."""
    _, start, size = _data_of(path)
    with path.open("rb") as f:
        f.seek(start)
        while size > 0:
            raw = np.frombuffer(f.read(min(size, CHUNK_FRAMES * 2)), dtype="<i2")
            if not len(raw):
                break
            if float(np.sqrt(np.mean(raw.astype(np.float64) ** 2))) / 32768 > floor:
                return True
            size -= len(raw) * 2
    return False


__all__ = ["loud", "split"]
