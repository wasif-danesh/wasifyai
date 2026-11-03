# SPDX-License-Identifier: Apache-2.0
"""Getting a recording into the form the speech runtime reads. It reads WAV (any rate, channels or
float
samples) and refuses everything else (docs/spikes/voice-v0.md), so other formats are converted
first, with
ffmpeg when it is on this computer, else with macOS's own `afconvert`. When neither is there the
person is
told what to do; nothing is bundled yet (an open question for the owner)."""

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

MAX_BYTES = 300 * 1024 * 1024
_EXTRA_FFMPEG = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg")


class AudioInputError(Exception):
    """`code` is stable; `str(e)` is a sentence safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def is_wav(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def find_converter() -> tuple[str, str] | None:
    ffmpeg = shutil.which("ffmpeg") or next((p for p in _EXTRA_FFMPEG if Path(p).is_file()), None)
    if ffmpeg:
        return "ffmpeg", ffmpeg
    if sys.platform == "darwin" and (afconvert := shutil.which("afconvert")):
        return "afconvert", afconvert
    return None


async def to_wav(
    data: bytes, filename: str, rate: int = 16000, force: bool = False, channels: int = 1
) -> bytes:
    """WAV bytes for `data`: as it is when it already is WAV (unless `force`), else converted to
    `channels` (mono by default) at `rate`."""
    if len(data) > MAX_BYTES:
        raise AudioInputError(
            "too_large", "That file is larger than 300 MB. Use a shorter recording."
        )
    if not data:
        raise AudioInputError("empty", "That file is empty.")
    if is_wav(data) and not force:
        return data
    tool = find_converter()
    if tool is None:
        raise AudioInputError(
            "needs_converter",
            "This file is not a WAV. Install ffmpeg to use other formats, or save it as WAV first.",
        )
    suffix = Path(filename).suffix[:12] or ".bin"
    with tempfile.TemporaryDirectory(prefix="voice-in-") as tmp:
        src, dst = Path(tmp) / f"in{suffix}", Path(tmp) / "out.wav"
        await asyncio.to_thread(src.write_bytes, data)
        name, exe = tool
        args = (
            [exe, "-nostdin", "-loglevel", "error", "-i", str(src), "-ac", str(channels),
             "-ar", str(rate), "-f", "wav", str(dst)]
            if name == "ffmpeg"
            else [exe, "-f", "WAVE", "-d", f"LEI16@{rate}", "-c", str(channels), str(src), str(dst)]
        )  # fmt: skip
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
            await asyncio.wait_for(proc.wait(), timeout=300)
        except (OSError, TimeoutError):
            raise AudioInputError(
                "convert_failed", "That recording could not be converted."
            ) from None
        if proc.returncode != 0 or not dst.is_file():
            raise AudioInputError(
                "unsupported_audio", "That file is not audio this app can read. Try a WAV or MP3."
            )
        return await asyncio.to_thread(dst.read_bytes)


def wav_facts(wav: bytes) -> tuple[int, int, float] | None:
    """(rate, channels, seconds) of a 16-bit PCM WAV, or None for anything else."""
    import io
    import wave

    try:
        with wave.open(io.BytesIO(wav)) as w:
            if w.getsampwidth() != 2 or w.getframerate() <= 0:
                return None
            return w.getframerate(), w.getnchannels(), w.getnframes() / w.getframerate()
    except (wave.Error, EOFError):
        return None


async def at_rate(data: bytes, filename: str, rate: int, channels: int) -> tuple[bytes, float]:
    """(WAV at exactly `rate` and `channels`, its length in seconds) for a recording in any format.
    A recording that already is that is used as it is; anything else is converted."""
    wav = await to_wav(data, filename, rate, channels=channels)
    facts = wav_facts(wav)
    if facts is None or facts[:2] != (rate, channels):
        wav = await to_wav(data, filename, rate, force=True, channels=channels)
        facts = wav_facts(wav)
    if facts is None or facts[:2] != (rate, channels):
        raise AudioInputError(
            "unsupported_audio", "That recording could not be read. Try a WAV or MP3."
        )
    return wav, facts[2]


def _frames(wav: bytes) -> tuple[int, int, bytes]:
    import io
    import wave

    with wave.open(io.BytesIO(wav)) as w:
        return w.getframerate(), w.getnchannels(), w.readframes(w.getnframes())


def _wav(rate: int, channels: int, frames: bytes) -> bytes:
    import io
    import wave

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return out.getvalue()


def slice_wav(wav: bytes, start: float, end: float) -> tuple[bytes, float]:
    """The part of a 16-bit WAV from `start` to `end` seconds (a sung line of a song), with its
    length."""
    rate, channels, frames = _frames(wav)
    width = 2 * channels
    total = len(frames) // width
    a = max(0, min(total, round(start * rate)))
    b = max(a, min(total, round(end * rate)))
    return _wav(rate, channels, frames[a * width : b * width]), (b - a) / rate


def join_wavs(parts: list[tuple[bytes, float]]) -> tuple[bytes, list[tuple[float, float]]]:
    """16-bit WAVs of one rate and channel count, one after another, each followed by its pause in
    seconds. Returns the joined WAV and where each part starts and ends in it."""
    rate = channels = 0
    out = bytearray()
    times: list[tuple[float, float]] = []
    for wav, pause in parts:
        r, c, frames = _frames(wav)
        if rate and (r, c) != (rate, channels):
            raise AudioInputError("unsupported_audio", "The parts do not have the same rate.")
        rate, channels = r, c
        start = len(out) / (2 * c * r)
        out += frames
        times.append((round(start, 3), round(len(out) / (2 * c * r), 3)))
        out += b"\0" * (round(max(0.0, pause) * r) * 2 * c)
    return _wav(rate or 24000, channels or 1, bytes(out)), times


# ---- encoding for saving -----------------------------------------------------------------------

ENCODINGS = {
    "mp3": ("audio/mpeg", "mp3"),
    "m4a": ("audio/mp4", "m4a"),
}


def available_encodings() -> list[str]:
    """The formats a track can be saved in besides WAV, with the tools on this computer: MP3 needs
    ffmpeg; M4A (AAC) needs ffmpeg or macOS's own `afconvert`."""
    tool = find_converter()
    if tool is None:
        return []
    return ["mp3", "m4a"] if tool[0] == "ffmpeg" else ["m4a"]


async def encode(wav: bytes, fmt: str) -> bytes:
    """`wav` as `fmt` ("mp3" or "m4a"), or an AudioInputError that says what is missing."""
    if fmt not in ENCODINGS:
        raise AudioInputError("bad_format", "That format is not offered.")
    if fmt not in available_encodings():
        raise AudioInputError(
            "needs_converter",
            "Saving as MP3 needs ffmpeg on this computer."
            if fmt == "mp3"
            else "Saving as M4A needs ffmpeg, or macOS.",
        )
    tool = find_converter()
    assert tool is not None
    name, exe = tool
    with tempfile.TemporaryDirectory(prefix="voice-out-") as tmp:
        src, dst = Path(tmp) / "in.wav", Path(tmp) / f"out.{fmt}"
        await asyncio.to_thread(src.write_bytes, wav)
        if name == "ffmpeg":
            codec = (
                ["-c:a", "libmp3lame", "-b:a", "192k"]
                if fmt == "mp3"
                else ["-c:a", "aac", "-b:a", "192k"]
            )
            args = [exe, "-nostdin", "-loglevel", "error", "-i", str(src), *codec, str(dst)]
        else:  # afconvert, M4A only
            args = [exe, "-f", "m4af", "-d", "aac", "-b", "192000", str(src), str(dst)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
            await asyncio.wait_for(proc.wait(), timeout=300)
        except (OSError, TimeoutError):
            raise AudioInputError("convert_failed", "That could not be converted.") from None
        if proc.returncode != 0 or not dst.is_file():
            raise AudioInputError("convert_failed", "That could not be converted.")
        return await asyncio.to_thread(dst.read_bytes)
