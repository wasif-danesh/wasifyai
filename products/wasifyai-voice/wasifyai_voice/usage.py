# SPDX-License-Identifier: Apache-2.0
"""The usage events the voice product records for its tools, dubs and audiobooks: counted once a
node has made something, so the usage pages know what was made."""

from collections.abc import Awaitable, Callable
from typing import Any

from wasifyai_platform_sdk import Capabilities

TOOLS = "voice.tool"
DUBS = "voice.dub"
BOOKS = "voice.audiobook"


def metered(
    caps: Capabilities,
    event: str,
    node: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    amount: Callable[[dict[str, Any]], int] = lambda state: 1,
    unit: str = "runs",
    **meta: Any,
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """A graph node whose result is counted (as `amount(state)` of `unit`) once it has made
    something."""

    async def run(state: dict[str, Any]) -> dict[str, Any]:
        out = await node(state)
        if out.get("status") == "done":
            await caps.record_usage(event, amount(state), unit, **meta)
        return out

    return run
