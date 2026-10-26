# ruff: noqa: E501  (the sentences shown to people, and made-up media in a test, are easier to read on one line)
"""The short clips a video model is taught from, and what is said about each one in plain words as it
arrives (ADR-0073, video amendment, decision 2). Like a picture, a clip is tagged, never changed or
thrown away: *Good*, *Too short*, *Too small*, *Too dark*, *Looks still*, *Blurry*, *Looks like a copy*.
The person removes what they want to.

`ffmpeg` does all of the reading (the static one that comes with `imageio-ffmpeg`, else the one on the
PATH); no other tool is needed. A clip is kept as it came; the description and the checks look at a frame
from the middle of it, and the trainer cuts the windows it learns from."""

import asyncio
import io
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from wasifyai_training import pictures

MAX_BYTES = 300 * 1024 * 1024
MAX_SECONDS = 600  # longer than this is refused at the door
MIN_SECONDS = (
    1.2  # a window of 25 frames at 24 a second is 1.04 s: shorter than this has no motion to learn
)
LONG_SECONDS = 30  # a warning: only a few windows of the clip are used
SMALL_SIDE = 384  # below this it is tagged "too small": the trainer works at 512 and up
REFUSE_SIDE = 64
DARK_BELOW = 18.0  # mean brightness of the middle frame, of 255
STILL_BELOW = 1.5  # mean change of a 64 pixel copy between frames, of 255: below this nothing moves
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO = re.compile(r"Stream #\d+:\d+[^:]*:\s*Video:.*?,\s*(\d{2,5})x(\d{2,5})")
_FPS = re.compile(r"(\d+(?:\.\d+)?)\s*fps")


class BadClip(Exception):
    """A clip that cannot be used, with the sentence the person is shown."""


@dataclass(frozen=True)
class ClipInfo:
    width: int
    height: int
    seconds: float
    fps: float

    @property
    def frames(self) -> int:
        return max(1, round(self.seconds * self.fps))


def ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


async def _run(args: list[str], limit: float = 60) -> tuple[int, bytes, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    try:
        out, err = await asyncio.wait_for(proc.communicate(), limit)
    except TimeoutError:
        proc.kill()
        raise BadClip("That clip took too long to read.") from None
    return proc.returncode or 0, out, err.decode(errors="replace")


def parse_info(report: str) -> ClipInfo:
    """What `ffmpeg -i` says about a file: its size, length and frame rate. Raises `BadClip`."""
    video = _VIDEO.search(report)
    length = _DURATION.search(report)
    if not video or not length:
        raise BadClip("That file could not be read as a video.")
    seconds = int(length.group(1)) * 3600 + int(length.group(2)) * 60 + float(length.group(3))
    fps = _FPS.search(report[video.start() :])
    return ClipInfo(
        width=int(video.group(1)), height=int(video.group(2)), seconds=seconds,
        fps=float(fps.group(1)) if fps else 24.0,
    )  # fmt: skip


async def probe(path: Path) -> ClipInfo:
    """The clip's size, length and frame rate. Raises `BadClip` in words."""
    _, _, report = await _run([ffmpeg_path(), "-hide_banner", "-i", str(path)])
    info = parse_info(report)
    if min(info.width, info.height) < REFUSE_SIDE:
        raise BadClip(
            f"That clip is too small. Use one at least {SMALL_SIDE} pixels on its shorter side."
        )
    if info.seconds > MAX_SECONDS:
        raise BadClip("That clip is too long. Use one under 10 minutes.")
    if info.seconds < 0.3:
        raise BadClip("That clip is too short to learn from. Use one of at least 2 seconds.")
    return info


async def frame_at(path: Path, seconds: float) -> Image.Image:
    """One frame of the clip, as RGB, upright, no larger than a picture may be."""
    code, out, report = await _run(
        [ffmpeg_path(), "-v", "error", "-ss", f"{max(0.0, seconds):.3f}", "-i", str(path),
         "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
    )  # fmt: skip
    if code != 0 or not out:
        raise BadClip("That clip could not be read.")
    img = Image.open(io.BytesIO(out)).convert("RGB")
    if max(img.size) > pictures.LONG_SIDE:
        scale = pictures.LONG_SIDE / max(img.size)
        img = img.resize(
            (round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS
        )
    return img


def brightness(img: Image.Image) -> float:
    g = img.convert("L")
    g.thumbnail((64, 64))
    px = g.tobytes()
    return sum(px) / max(1, len(px))


def change(a: Image.Image, b: Image.Image) -> float:
    """How much two frames differ: the mean change of their grey values in a 64 pixel copy."""
    ga, gb = a.convert("L"), b.convert("L")
    ga.thumbnail((64, 64))
    gb = gb.resize(ga.size)
    pa, pb = ga.tobytes(), gb.tobytes()
    return sum(abs(x - y) for x, y in zip(pa, pb, strict=True)) / max(1, len(pa))


def check(
    info: ClipInfo, middle: Image.Image, other_frames: list[Image.Image], others: list[int]
) -> list[dict[str, Any]]:
    """The checks of one clip in plain words: `level` is `ok` or `warn` (a warning suggests removing the clip)."""
    out: list[dict[str, Any]] = []
    if info.seconds < MIN_SECONDS:
        out.append(
            {
                "code": "too_short",
                "level": "warn",
                "message": f"Too short: {info.seconds:.1f} seconds. Clips of 2 to 10 seconds teach best.",
            }
        )
    if min(info.width, info.height) < SMALL_SIDE:
        out.append(
            {
                "code": "too_small",
                "level": "warn",
                "message": f"Too small: {info.width} by {info.height}. Clips at least {SMALL_SIDE} pixels on the shorter side teach best.",
            }
        )
    if brightness(middle) < DARK_BELOW:
        out.append(
            {"code": "dark", "level": "warn", "message": "Too dark: it would teach a dim look."}
        )
    if pictures.sharpness(middle) < pictures.BLURRY_BELOW:
        out.append(
            {"code": "blurry", "level": "warn", "message": "Blurry: it would teach a soft look."}
        )
    if other_frames:
        if all(change(middle, f) < STILL_BELOW for f in other_frames):
            out.append(
                {
                    "code": "still",
                    "level": "warn",
                    "message": "Looks still: nothing seems to move. A picture teaches that as well.",
                }
            )
    if any(
        pictures.hamming(pictures.dhash(middle), other) <= pictures.NEAR_COPY_BITS
        for other in others
    ):
        out.append(
            {
                "code": "copy",
                "level": "warn",
                "message": "Looks like a copy of another picture or clip you added.",
            }
        )
    return out or [{"code": "good", "level": "ok", "message": "Good."}]
