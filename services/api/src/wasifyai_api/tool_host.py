"""What the assistant's tools reach (ADR-0057): the `ToolHost` the API gives a tool-using product.

It acts for the user of the current run (the tenant and user come from the run context), so a tool
can only ever touch that user's own creations, and a child run is a normal run: its own events,
guardrails, quotas and job queue, saved to the same library."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from wasifyai_platform_sdk import ToolUnavailable, require_context

log = logging.getLogger(__name__)

Describer = Callable[[str, str, str], Awaitable[str]]  # (tenant, user, item_id) -> a short text
NotebookSearch = Callable[[str, str, str, int], Awaitable[list[dict[str, Any]]]]
# (tenant, user, query, limit) -> passages; raises ToolUnavailable


class ApiToolHost:
    def __init__(
        self,
        runs: Callable[[], Any],
        index: Callable[[], Any],
        describers: dict[str, Describer] | None = None,
        notebook_search: NotebookSearch | None = None,
        available: Callable[[], set[str]] | None = None,
    ):
        self._runs = runs
        self._index = index
        self._describers = describers or {}
        self._notebook_search = notebook_search
        self._available = available

    def available_tools(self) -> set[str] | None:
        """The tools this deployment can run (the assistant offers the model only these); `None`
        when it was not told, which means all of them."""
        return self._available() if self._available else None

    def run_product(
        self, product_id: str, graph_input: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        ctx = require_context()
        return self._runs().run_child(product_id, ctx.tenant_id, ctx.user_id, graph_input)

    async def search_creations(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        ctx = require_context()
        hits, _degraded = await self._index().search(
            ctx.tenant_id, ctx.user_id, query.strip()[:200], None, max(1, min(limit, 12))
        )
        out: list[dict[str, Any]] = []
        for h in hits:
            if h.kind == "conversation":
                continue  # the assistant finds creations, not its own chats
            row: dict[str, Any] = {"kind": h.kind, "product_id": h.product_id, "id": h.item_id}
            describe = self._describers.get(h.kind)
            if describe is not None:
                try:
                    row["text"] = (await describe(ctx.tenant_id, ctx.user_id, h.item_id))[:200]
                except Exception:
                    log.warning("could not describe %s %s", h.kind, h.item_id)
            out.append(row)
        return out

    async def search_notebooks(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if self._notebook_search is None:
            raise ToolUnavailable("Notebooks are not available here.")
        ctx = require_context()
        return await self._notebook_search(
            ctx.tenant_id, ctx.user_id, query.strip()[:300], max(1, min(limit, 8))
        )
