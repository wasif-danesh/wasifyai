"""A song as a video: the cover as a still picture with the song playing (what social apps accept).

Runs `ffmpeg` as a separate program (H.264 video and AAC audio in an MP4; ADR-0034). The picture is
a single frame repeated at a low rate, so this is a second or two of CPU for a minute of music."""

import asyncio
import io
import logging
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

TIMEOUT_S = 45  # a minute of music with a still picture takes a second or two
MAX_COVER_PX = 2048


class VideoError(Exception):
    """ffmpeg failed. The details go to the log; the message is safe to show."""


class VideoUnavailable(VideoError):
    """ffmpeg is not installed where the API runs."""


def normalised_cover(cover: bytes) -> bytes:
    """The cover as a plain RGB PNG that ffmpeg can always read (a JPEG would make the video
    full-range). An unreadable image is refused here: ffmpeg looping over a broken picture does not
    fail, it waits until the timeout."""
    try:
        with Image.open(io.BytesIO(cover)) as im:
            rgb = im.convert("RGB")
    except Exception as exc:
        log.error("the cover cannot be read: %s", type(exc).__name__)
        raise VideoError("the video could not be made") from exc
    rgb.thumbnail((MAX_COVER_PX, MAX_COVER_PX))
    out = io.BytesIO()
    rgb.save(out, "PNG", compress_level=1)
    return out.getvalue()


def _clean(text: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", text).strip()[:120]


def ffmpeg_path() -> str:
    """The static ffmpeg that comes with the `imageio-ffmpeg` package (the same program on every
    machine and in the image), else whatever `ffmpeg` is on the PATH."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


async def _duration(path: Path, ffmpeg: str) -> float | None:
    """The audio's length in seconds, read from ffmpeg's own report. `-shortest` alone lets a looped
    picture run several seconds past the music, so the video is cut at exactly this length."""
    try:
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-hide_banner", "-i", str(path),  # no output file: it reports, then stops
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        _, err = await asyncio.wait_for(proc.communicate(), 20)
    except (OSError, TimeoutError):
        return None
    m = _DURATION.search(err.decode(errors="replace"))
    if not m:
        return None
    seconds = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    return seconds if seconds > 0 else None


async def encode_video(audio: bytes, cover: bytes, title: str, ffmpeg: str | None = None) -> bytes:
    ffmpeg = ffmpeg or ffmpeg_path()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cover_path, audio_path, out_path = d / "cover.img", d / "audio.mp3", d / "out.mp4"
        cover_path.write_bytes(await asyncio.to_thread(normalised_cover, cover))
        audio_path.write_bytes(audio)
        length = await _duration(audio_path, ffmpeg)
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-framerate", "1", "-i", str(cover_path),
            "-i", str(audio_path),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",  # H.264 wants even sizes
            "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast", "-crf", "28",
            "-r", "15", "-c:a", "aac", "-b:a", "192k", "-shortest",
            *(["-t", f"{length:.3f}"] if length else []),
            "-metadata", f"title={_clean(title)}",
            "-movflags", "+faststart", str(out_path),
        ]  # fmt: skip
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as exc:
            raise VideoUnavailable("ffmpeg is not installed") from exc
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), TIMEOUT_S)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise VideoError("making the video took too long") from None
        if proc.returncode != 0 or not out_path.exists():
            log.error(
                "ffmpeg failed (%s): %s", proc.returncode, stderr.decode(errors="replace")[:500]
            )
            raise VideoError("the video could not be made")
        return out_path.read_bytes()
