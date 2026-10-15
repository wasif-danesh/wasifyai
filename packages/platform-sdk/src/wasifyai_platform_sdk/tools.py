"""What a product's tool-using graph (the assistant, ADR-0057) may ask of the platform.

A product never reaches into the run manager or the search index. The API gives it a `ToolHost`
(through `Capabilities.extras["tool_host"]`), which acts for the user of the current run: it starts
another product's graph as a child run, and searches that user's creations."""

from collections.abc import AsyncIterator
from typing import Any, Protocol


class ToolHost(Protocol):
    def run_product(
        self, product_id: str, graph_input: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Run another product's graph for the current user and yield its events (dicts with an
        `event` name) until it ends with `done` or `error`."""
        ...

    async def search_creations(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        """The current user's creations that match `query`: dicts with `kind`, `product_id`,
        `id`."""
        ...
