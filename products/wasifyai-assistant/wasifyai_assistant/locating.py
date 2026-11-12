"""An area named in words is found before the card (docs/chat-does-everything-plan.md, CE6).

"Change only the sky into a sunset": the model proposes `image.inpaint` with `area: "the sky"`.
Before the card is shown, the chat asks `image.find_area` (a read, run without asking) where that
is, and puts the rectangle in the proposal, so the card draws it on the picture: the person runs
it, or draws another box. When it cannot be found here the proposal is left as it was, and the
action says what is wrong when it runs."""

from collections.abc import Awaitable, Callable
from typing import Any

FIND = "image.find_area"
TAKES_AREA = {"image.inpaint"}

# runs `image.find_area` for a picture and words: the region, or None
Find = Callable[[str, str], Awaitable[dict[str, Any] | None]]


async def area_found(action_id: str, params: dict[str, Any], find: Find) -> dict[str, Any]:
    """`params` with the region its words name, when it names an area in words and no region."""
    if action_id not in TAKES_AREA or params.get("region"):
        return params
    area, image_id = params.get("area"), params.get("image_id")
    if not isinstance(area, str) or not area.strip() or not isinstance(image_id, str):
        return params
    region = await find(image_id, area)
    return {**params, "region": region} if region else params
