"""The picture a 3D model is made from: what is accepted, what is checked in words before the long
run, and the thumbnail (ADR-0080 decision 3).

The engine takes one object on a transparent background. A picture is cut out by the engine
(BiRefNet); then it is looked at, here, in plain words: is there an object, is it all in the
picture, is it big enough and in the middle, is it one object. Nothing is fixed silently and
nothing here decides: a warning is said and the person goes on or tries another picture."""

import io
from collections import deque

from PIL import Image, ImageOps

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
MIN_SIDE = 128
LONG_SIDE = 2048  # a picture is brought down to this before the engine sees it
ALLOWED = {"PNG", "JPEG", "WEBP"}
MASK_GRID = 96  # the object is counted on a small grid


class BadPicture(Exception):
    """A picture that cannot be used, with the sentence the person is shown."""


def open_picture(data: bytes) -> Image.Image:
    """The picture as RGBA, no larger than `LONG_SIDE`, without its metadata. Raises BadPicture."""
    if not data:
        raise BadPicture("That picture is empty.")
    if len(data) > MAX_BYTES:
        raise BadPicture("That picture is too big. Use one under 20 MB.")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        probe = Image.open(io.BytesIO(data))
        if probe.format not in ALLOWED:
            raise BadPicture("Use a PNG, JPEG or WebP picture.")
        w, h = probe.size
        if w * h > MAX_PIXELS:
            raise BadPicture("That picture is too large. Use one under 40 megapixels.")
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGBA")
    except BadPicture:
        raise
    except (OSError, Image.DecompressionBombError, ValueError, SyntaxError):
        raise BadPicture("That file could not be read as a picture.") from None
    if min(img.size) < MIN_SIDE:
        raise BadPicture(f"That picture is too small. Use one at least {MIN_SIDE} pixels wide.")
    if max(img.size) > LONG_SIDE:
        scale = LONG_SIDE / max(img.size)
        img = img.resize(
            (round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS
        )
    return img


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    return buf.getvalue()


def has_real_alpha(img: Image.Image) -> bool:
    """Already cut out: a good part of the picture is see-through."""
    alpha = img.getchannel("A")
    clear = sum(alpha.histogram()[:16])
    return clear >= 0.05 * img.width * img.height


def _mask(alpha: Image.Image) -> Image.Image:
    return alpha.point([0] * 25 + [255] * 231)  # a lookup table: 255 above 24


def _components(mask: Image.Image) -> list[int]:
    """The sizes of the separate blobs of the object, on a small grid."""
    small = mask.resize((MASK_GRID, MASK_GRID), Image.Resampling.BILINEAR).point(
        [0] * 65 + [255] * 191
    )
    px = small.load()
    assert px is not None
    seen = [[False] * MASK_GRID for _ in range(MASK_GRID)]
    sizes: list[int] = []
    for y in range(MASK_GRID):
        for x in range(MASK_GRID):
            if px[x, y] and not seen[y][x]:
                size, queue = 0, deque([(x, y)])
                seen[y][x] = True
                while queue:
                    cx, cy = queue.popleft()
                    size += 1
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if 0 <= nx < MASK_GRID and 0 <= ny < MASK_GRID and px[nx, ny]:
                            if not seen[ny][nx]:
                                seen[ny][nx] = True
                                queue.append((nx, ny))
                sizes.append(size)
    return sorted(sizes, reverse=True)


def check_cutout(cutout: Image.Image) -> list[dict[str, str]]:
    """What can be said about the cut-out, in words: `{code, level, message}` with level `ok`,
    `warn` or `stop` (nothing to make a model from). The last item is always the tip."""
    w, h = cutout.size
    mask = _mask(cutout.getchannel("A"))
    bbox = mask.getbbox()
    covered = sum(mask.histogram()[255:]) / (w * h)
    tip = {
        "code": "tip", "level": "ok",
        "message": "A straight-on picture at eye level works best. Glass, mirrors, thin parts "
        "and several objects do not come out well.",
    }  # fmt: skip
    if bbox is None or covered < 0.005:
        return [
            {"code": "no_object", "level": "stop", "message": (
                "No object was found in this picture. Use a picture of one object on a plain "
                "background.")},
            tip,
        ]  # fmt: skip
    out: list[dict[str, str]] = []
    left, top, right, bottom = bbox
    margin = max(2, round(0.01 * max(w, h)))
    if left <= margin or top <= margin or right >= w - margin or bottom >= h - margin:
        out.append({"code": "cut_off", "level": "warn", "message": (
            "The object touches the edge of the picture, so part of it may be cut off. "
            "Use a picture where all of it shows.")})  # fmt: skip
    if (right - left) * (bottom - top) < 0.10 * w * h:
        out.append(
            {
                "code": "small",
                "level": "warn",
                "message": (
                    "The object is small in the picture. Crop closer to it for a better model."
                ),
            }
        )
    cx, cy = (left + right) / 2 / w, (top + bottom) / 2 / h
    if abs(cx - 0.5) > 0.25 or abs(cy - 0.5) > 0.25:
        out.append(
            {
                "code": "off_centre",
                "level": "warn",
                "message": (
                    "The object is not in the middle of the picture. Centre it for a better model."
                ),
            }
        )
    sizes = _components(mask)
    if len(sizes) > 1 and sizes[1] >= 0.15 * sizes[0]:
        out.append(
            {
                "code": "several",
                "level": "warn",
                "message": ("More than one object was found. Use a picture of a single object."),
            }
        )
    if not out:
        out.append(
            {
                "code": "one_object",
                "level": "ok",
                "message": ("One object, in the middle, with all of it showing."),
            }
        )
    return [*out, tip]


def thumbnail(cutout: Image.Image, size: int = 384) -> bytes:
    """The object on a light background, cropped square around it: a card in the library."""
    mask = _mask(cutout.getchannel("A"))
    bbox = mask.getbbox() or (0, 0, *cutout.size)
    left, top, right, bottom = bbox
    side = round(max(right - left, bottom - top) * 1.15) or 1
    cx, cy = (left + right) // 2, (top + bottom) // 2
    box = (cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side)
    ground = Image.new("RGBA", (side, side), (242, 242, 240, 255))
    piece = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    piece.paste(cutout, (-box[0], -box[1]))
    ground.alpha_composite(piece)
    buf = io.BytesIO()
    ground.convert("RGB").resize((size, size), Image.Resampling.LANCZOS).save(
        buf, "JPEG", quality=86
    )
    return buf.getvalue()
