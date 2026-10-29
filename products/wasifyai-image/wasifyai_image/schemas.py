"""The run's input contract."""

from typing import Literal

MAX_PROMPT_CHARS = 500
Mode = Literal["text", "image", "reference", "inpaint"]
MODES: tuple[Mode, ...] = ("text", "image", "reference", "inpaint")

# size name -> (width, height). Multiples of 16, which FLUX.2 needs; about one megapixel each.
SIZES: dict[str, tuple[int, int]] = {
    "square": (1024, 1024),
    "landscape": (1152, 864),  # 4:3
    "portrait": (864, 1152),  # 3:4
    "wide": (1344, 768),  # 16:9
    "tall": (768, 1344),  # 9:16
}
DEFAULT_SIZE = "square"
