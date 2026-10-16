"""What a product's tool-using graph (the assistant, ADR-0057) may ask of the platform.

A product never reaches into the run manager or the search index. The API gives it a `ToolHost`
(through `Capabilities.extras["tool_host"]`), which acts for the user of the current run: it starts
another product's graph as a child run, searches that user's creations, and searches the passages of
that user's notebooks."""

from collections.abc import AsyncIterator
from typing import Any, Protocol


class ToolUnavailable(Exception):
    """A tool cannot run in this deployment or right now. `message` is for the person, plainly."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


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

    async def search_notebooks(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """The best passages across the current user's notebooks: dicts with `notebook_id`,
        `notebook`, `document_id`, `title`, `text`. Raises `ToolUnavailable` when notebooks are
        not served here or their search model is missing."""
        ...
