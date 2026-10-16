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


async def to_wav(data: bytes, filename: str, rate: int = 16000, force: bool = False) -> bytes:
    """WAV bytes for `data`: as it is when it already is WAV (unless `force`), else converted to
    mono at `rate`."""
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
            [exe, "-nostdin", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(rate),
             "-f", "wav", str(dst)]
            if name == "ffmpeg"
            else [exe, "-f", "WAVE", "-d", f"LEI16@{rate}", "-c", "1", str(src), str(dst)]
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
