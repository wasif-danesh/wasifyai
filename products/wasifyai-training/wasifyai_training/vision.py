"""What the captioner and the judge share (ADR-0076, ADR-0073 decision 10): their prompts and the
small copy of a picture they look at."""

import io
from pathlib import Path

from PIL import Image as PILImage

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"  # in the package: the wheel has it
REVIEW_PX = 768  # the model needs a look at the picture, not every pixel


def prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def review_copy(png: bytes) -> bytes:
    """A small JPEG of the picture for the captioner and the judge."""
    with PILImage.open(io.BytesIO(png)) as im:
        rgb = im.convert("RGB")
    rgb.thumbnail((REVIEW_PX, REVIEW_PX))
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=85)
    return out.getvalue()
