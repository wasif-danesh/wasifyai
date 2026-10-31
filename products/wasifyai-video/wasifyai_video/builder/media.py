"""The files of a project of scenes (ADR-0096 MX5): checked when they come in, kept in the storage
interface under the owner's own prefix, and put next to the page before anything opens it.

An upload is untrusted. Its type comes from its first bytes, never its name. A picture is decoded
and written again, which leaves nothing of the original file but its pixels (and keeps transparency,
for a logo). A clip or a sound must be read by ffmpeg, told exactly which format to expect and with
only the file protocol; it is kept as it came, because re-encoding footage costs quality and
minutes, and it is only ever played in the render's sandbox and the preview's frame."""

import io
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from wasifyai_platform_sdk.media_upload import sniff

from wasifyai_video.videos import ffmpeg_path

MAX_BYTES = 100 * 1024 * 1024  # the web's proxy lets 110 MB through
MAX_PIXELS = 24_000_000  # refuses decompression bombs before the pixels are decoded
MAX_SIDE = 4096
PROBE_TIMEOUT_S = 30
PICTURES = {"PNG", "JPEG", "WEBP"}
MEDIA_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".mp4": "video/mp4", ".mov": "video/quicktime",
    ".webm": "video/webm", ".mkv": "video/x-matroska", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
    ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac",
}  # fmt: skip
_DEMUXER = {
    "wav": "wav", "ogg": "ogg", "flac": "flac", "mp3": "mp3", "matroska": "matroska,webm",
    "mp4": "mov,mp4,m4a,3gp,3g2,mj2",
}  # fmt: skip
_DURATION = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO = re.compile(r"Stream #[^\n]*Video: (\w+)")
_AUDIO = re.compile(r"Stream #[^\n]*Audio: (\w+)")
_SIZE = re.compile(r"Stream #[^\n]*Video: [^\n]*?(\d{2,5})x(\d{2,5})")


class MediaError(ValueError):
    """The file cannot be used; the message says why, in plain words."""


@dataclass(frozen=True)
class Checked:
    data: bytes
    asset: dict[str, Any]


def rel_path(cid: str, file: str) -> str:
    """Where a project's file is kept, under its owner's prefix. Never taken from a document."""
    return f"motion/{cid}/{file}"


def _clean_name(name: str) -> str:
    stem = re.sub(r"[\x00-\x1f/\\]+", " ", name).strip()
    return stem[:120] or "My file"


def _picture(data: bytes, name: str, asset_id: str) -> Checked:
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in PICTURES:
                raise MediaError("Please use a PNG, JPEG or WebP picture.")
            if img.width * img.height > MAX_PIXELS:
                raise MediaError("That picture has too many pixels. Try a smaller one.")
            img = ImageOps.exif_transpose(img)
            lowest = img.convert("RGBA").getchannel("A").getextrema()[0]
            clear = isinstance(lowest, int) and lowest < 255  # a logo keeps its see-through parts
            img = img.convert("RGBA" if clear else "RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            img.save(out, "PNG" if clear else "JPEG", quality=92)
            width, height = img.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise MediaError("That file could not be read as a picture.") from None
    ext = ".png" if clear else ".jpg"
    return Checked(
        out.getvalue(),
        {
            "id": asset_id, "kind": "image", "name": _clean_name(name), "file": f"{asset_id}{ext}",
            "seconds": 0, "width": width, "height": height, "has_audio": False, "codec": "",
        },
    )  # fmt: skip


def _probe(data: bytes, container: str) -> str:
    """What ffmpeg says about the file: told the format, with only the file protocol."""
    with tempfile.NamedTemporaryFile() as f:
        f.write(data)
        f.flush()
        try:
            done = subprocess.run(
                [ffmpeg_path(), "-hide_banner", "-protocol_whitelist", "file", "-f",
                 _DEMUXER[container], "-i", f.name],
                capture_output=True, timeout=PROBE_TIMEOUT_S, check=False,
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            raise MediaError("That file could not be read. Try another one.") from None
    return done.stderr.decode(errors="replace")


def _timed(data: bytes, name: str, asset_id: str, container: str) -> Checked:
    report = _probe(data, container)
    length = _DURATION.search(report)
    video, audio = _VIDEO.search(report), _AUDIO.search(report)
    if not length or not (video or audio):
        raise MediaError("That file could not be read as a video or a sound. Try another one.")
    seconds = int(length[1]) * 3600 + int(length[2]) * 60 + float(length[3])
    if seconds <= 0:
        raise MediaError("That file is empty.")
    size = _SIZE.search(report) if video else None
    kind = "video" if video else "audio"
    wanted = Path(name).suffix.lower()
    ext = {"wav": ".wav", "ogg": ".ogg", "flac": ".flac", "mp3": ".mp3", "matroska": ".webm"}.get(
        container, wanted if wanted in (".mov", ".m4a") else ".mp4"
    )
    if kind == "audio" and container == "mp4":
        ext = ".m4a"
    return Checked(
        data,
        {
            "id": asset_id, "kind": kind, "name": _clean_name(name), "file": f"{asset_id}{ext}",
            "seconds": round(seconds, 2), "width": int(size[1]) if size else 0,
            "height": int(size[2]) if size else 0, "has_audio": bool(video and audio),
            "codec": video[1] if video else audio[1] if audio else "",
        },
    )  # fmt: skip


def check_upload(data: bytes, name: str) -> Checked:
    """A file from a person, ready to keep: its clean bytes and what the document says about it."""
    if not data:
        raise MediaError("No file was sent.")
    if len(data) > MAX_BYTES:
        raise MediaError(f"That file is too large. The limit is {MAX_BYTES // 2**20} MB.")
    asset_id = uuid.uuid4().hex[:8]
    container = sniff(data)
    if container is not None:
        return _timed(data, name, asset_id, container)
    return _picture(data, name, asset_id)


def parse_range(header: str | None, size: int, longest: int) -> tuple[int, int] | None:
    """A `bytes=a-b` request as (first, last) within the file, at most `longest` long. None when
    there is no such request; a range outside the file raises ValueError."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
    if not match or not (match[1] or match[2]):
        return None
    if match[1]:
        first = int(match[1])
        last = int(match[2]) if match[2] else size - 1
    else:
        first = max(0, size - int(match[2]))
        last = size - 1
    if first >= size or first > last:
        raise ValueError("outside the file")
    return first, min(last, size - 1, first + longest - 1)
