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
