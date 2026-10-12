"""Small real files for the download tests, made and inspected with ffmpeg itself (the static
ffmpeg that ships with imageio-ffmpeg, so these tests run wherever the dependencies do)."""

import io
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from wasifyai_music.video import ffmpeg_path

FFMPEG = ffmpeg_path()
# What the start of an MP3 audio frame looks like (not a valid ID3 header)
FAKE_FRAMES = b"\xff\xfb\x90\x00" + bytes(range(256)) * 8


def have_ffmpeg() -> bool:
    try:
        return subprocess.run([FFMPEG, "-version"], capture_output=True).returncode == 0
    except OSError:
        return False


HAVE_FFMPEG = have_ffmpeg()


def png(width=64, height=48) -> bytes:
    im = Image.new("RGBA", (width, height))
    px = im.load()
    assert px is not None
    for x in range(width):
        for y in range(height):
            px[x, y] = (x * 255 // width, y * 255 // height, 120, 255)
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def real_mp3(seconds: int = 2) -> bytes:
    out = subprocess.run(
        [FFMPEG, "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "libmp3lame", "-b:a", "96k", "-f", "mp3", "-"],
        capture_output=True, check=True,
    )  # fmt: skip
    return out.stdout


def probe(data: bytes, suffix: str) -> dict:
    """What ffmpeg reports about a file: {"duration", "tags", "streams": [{"kind", "codec", "line",
    "size", "pix_fmt", "attached_pic"}]}."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / f"f{suffix}"
        path.write_bytes(data)
        report = subprocess.run(
            [FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True
        ).stderr
    duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", report)
    streams = []
    for line in report.splitlines():
        m = re.search(r"Stream #\d+:\d+.*?: (Audio|Video): (\w+)", line)
        if m:
            size = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
            pix = re.search(r"\b(yuvj?\d+p|rgb\w*)\b", line)
            streams.append(
                {
                    "kind": m[1].lower(), "codec": m[2], "line": line.strip(),
                    "size": (int(size[1]), int(size[2])) if size else None,
                    "pix_fmt": pix[1] if pix else None, "attached_pic": "attached pic" in line,
                }
            )  # fmt: skip
    tags: dict[str, str] = {}
    for key, value in re.findall(r"^\s{4}([A-Za-z_-]+)\s*:\s(.*)$", report, re.M):
        tags.setdefault(key.lower(), value.strip())
    seconds = (
        int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3]) if duration else 0.0
    )
    return {"duration": seconds, "tags": tags, "streams": streams, "report": report}


def decodes_cleanly(data: bytes, suffix: str) -> bool:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / f"f{suffix}"
        path.write_bytes(data)
        res = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True
        )
    return res.returncode == 0 and not res.stderr
