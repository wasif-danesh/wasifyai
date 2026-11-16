"""A recording made ready for the speaker model and the transcriber: one channel, 16 kHz, 16-bit
WAV, written to the meeting's folder. Any format FFmpeg reads is taken (the app bundles FFmpeg for
Motion graphics, through `imageio-ffmpeg`); without FFmpeg, macOS's own `afconvert`; else only a
WAV already in that form."""

import asyncio
import shutil
import sys
from pathlib import Path

from wasifyai_meetings.sortformer import SR, BadAudio, Wav

MAX_BYTES = 2 * 1024 * 1024 * 1024  # a long meeting as a WAV from a recorder
_EXTRA_FFMPEG = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg")
SUFFIXES = (
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".mp4", ".mov", ".mkv",
    ".wma", ".aiff", ".aif", ".caf",
)  # fmt: skip


class AudioError(Exception):
    """`code` is stable; `str(e)` is a sentence safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _bundled() -> str | None:
    try:
        import imageio_ffmpeg  # type: ignore[import-untyped]

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # not bundled here
        return None


def find_converter() -> tuple[str, str] | None:
    ffmpeg = (
        _bundled()
        or shutil.which("ffmpeg")
        or next((p for p in _EXTRA_FFMPEG if Path(p).is_file()), None)
    )
    if ffmpeg:
        return "ffmpeg", ffmpeg
    if sys.platform == "darwin" and (afconvert := shutil.which("afconvert")):
        return "afconvert", afconvert
    return None


def _ready_as_is(path: Path) -> bool:
    try:
        Wav(path).close()
        return True
    except (BadAudio, OSError):
        return False


async def prepare(src: Path, dst: Path) -> float:
    """Write `src` to `dst` as one-channel 16 kHz 16-bit WAV; its length in seconds."""
    if not await asyncio.to_thread(lambda: src.is_file() and src.stat().st_size > 0):
        raise AudioError("empty", "That file is empty.")
    if await asyncio.to_thread(_ready_as_is, src):
        if src != dst:
            await asyncio.to_thread(shutil.copyfile, src, dst)
    else:
        tool = find_converter()
        if tool is None:
            raise AudioError(
                "needs_converter",
                "This recording needs FFmpeg to be read. Save it as a WAV file, or install FFmpeg.",
            )
        name, exe = tool
        args = (
            [exe, "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-vn", "-ac", "1",
             "-ar", str(SR), "-c:a", "pcm_s16le", "-f", "wav", str(dst)]
            if name == "ffmpeg"
            else [exe, "-f", "WAVE", "-d", f"LEI16@{SR}", "-c", "1", str(src), str(dst)]
        )  # fmt: skip
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )  # fmt: skip
        except OSError:
            raise AudioError("convert_failed", "That recording could not be read.") from None
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=1800)
        except TimeoutError:
            proc.kill()  # a converter that hangs is not left running
            raise AudioError("convert_failed", "That recording could not be read.") from None
        except asyncio.CancelledError:
            proc.kill()
            raise
        if proc.returncode != 0 or not await asyncio.to_thread(dst.is_file):
            raise AudioError(
                "convert_failed", "That recording could not be read. Is it a sound or video file?"
            )
    try:
        wav = Wav(dst)
    except BadAudio as e:
        raise AudioError("convert_failed", str(e)) from None
    seconds = wav.seconds
    wav.close()
    if seconds < 1.0:
        raise AudioError("too_short", "That recording is shorter than a second.")
    return seconds


__all__ = ["MAX_BYTES", "SUFFIXES", "AudioError", "find_converter", "prepare"]
