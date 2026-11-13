"""The pictures a character or style is taught from: what is accepted, and what is said about
each one in plain words as it arrives (ADR-0076 decision 1, step 1).

Nothing is fixed silently and nothing is thrown away: a picture is tagged *Good*, *Too small*,
*Blurry* or *Looks like a copy of another*, and the person removes what they want to (one click
suggests the lot)."""

import hashlib
import io
from typing import Any

from PIL import Image, ImageFilter, ImageOps, ImageStat

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
REFUSE_SIDE = 64  # below this nothing can be learnt from it: refused at the door
SMALL_SIDE = 512  # below this it is tagged "too small": the trainer works at 512 and up
LONG_SIDE = 2048  # a picture is brought down to this: the trainer never sees more
THUMB_SIDE = 320
ALLOWED = {"PNG", "JPEG", "WEBP"}
BLURRY_BELOW = (
    8.0  # the spread of the edges in a 256 pixel copy, measured on sharp and soft photographs
)
NEAR_COPY_BITS = (
    4  # of 64: pictures this close in their dhash are the same picture, resized or recompressed
)


class BadPicture(Exception):
    """A picture that cannot be used, with the sentence the person is shown."""


def open_picture(data: bytes) -> Image.Image:
    """The picture as RGB, turned upright, no larger than `LONG_SIDE`, without its metadata."""
    if not data:
        raise BadPicture("That picture is empty.")
    if len(data) > MAX_BYTES:
        raise BadPicture("That picture is too big. Use one under 20 MB.")
    try:
        probe = Image.open(io.BytesIO(data))
        if probe.format not in ALLOWED:
            raise BadPicture("Use a PNG, JPEG or WebP picture.")
        w, h = probe.size
        if w * h > MAX_PIXELS:
            raise BadPicture("That picture is too large. Use one under 40 megapixels.")
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        img = img.convert("RGBA")
    except BadPicture:
        raise
    except (OSError, Image.DecompressionBombError, ValueError, SyntaxError):
        raise BadPicture("That file could not be read as a picture.") from None
    if min(img.size) < REFUSE_SIDE:
        raise BadPicture(f"That picture is too small. Use one at least {SMALL_SIDE} pixels wide.")
    flat = Image.new(
        "RGB", img.size, (255, 255, 255)
    )  # transparency becomes white: captions see it so
    flat.paste(img, mask=img.getchannel("A"))
    if max(flat.size) > LONG_SIDE:
        scale = LONG_SIDE / max(flat.size)
        flat = flat.resize(
            (round(flat.width * scale), round(flat.height * scale)), Image.Resampling.LANCZOS
        )
    return flat


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    return buf.getvalue()


def thumbnail(img: Image.Image) -> bytes:
    small = img.copy()
    small.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def content_hash(png: bytes) -> str:
    return hashlib.sha256(png).hexdigest()


def dhash(img: Image.Image) -> int:
    """A 64 bit fingerprint that survives resizing and recompression."""
    g = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = g.tobytes()
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (px[y * 9 + x] > px[y * 9 + x + 1])
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def sharpness(img: Image.Image) -> float:
    """How much fine detail there is: the spread of a Laplacian filter on a 256 pixel copy, away
    from the border (where a filter always finds an edge). A soft or out of focus picture has
    little."""
    g = img.convert("L")
    g.thumbnail((256, 256), Image.Resampling.LANCZOS)
    kernel = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)
    edges = g.filter(kernel).crop((2, 2, g.width - 2, g.height - 2))
    return float(ImageStat.Stat(edges).stddev[0])


def check(img: Image.Image, others: list[int]) -> list[dict[str, Any]]:
    """The checks of one picture in plain words: `level` is `ok` or `warn` (a warning suggests
    removing the picture)."""
    out: list[dict[str, Any]] = []
    if min(img.size) < SMALL_SIDE:
        out.append(
            {"code": "too_small", "level": "warn",
             "message": f"Too small: {img.width} by {img.height}. "
             f"Pictures at least {SMALL_SIDE} pixels wide teach best."}
        )  # fmt: skip
    if sharpness(img) < BLURRY_BELOW:
        out.append(
            {"code": "blurry", "level": "warn", "message": "Blurry: it would teach a soft look."}
        )
    mine = dhash(img)
    if any(hamming(mine, other) <= NEAR_COPY_BITS for other in others):
        out.append(
            {"code": "copy", "level": "warn",
             "message": "Looks like a copy of another picture you added."}
        )  # fmt: skip
    return out or [{"code": "good", "level": "ok", "message": "Good."}]
