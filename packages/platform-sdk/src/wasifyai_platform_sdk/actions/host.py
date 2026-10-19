"""What the executor asks of the engine (ADR-0068 decision 8): the part of the product that is not
in the catalogue. The API implements it (`wasifyai_api.tool_host.ApiToolHost`); tests use a fake.

It extends `ToolHost` (ADR-0057): the same child runs and searches, plus the readiness of what an
action `requires`."""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from wasifyai_platform_sdk.actions.model import Need, Readiness


class ActionHost(Protocol):
    def run_product(
        self, product_id: str, graph_input: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """A child run of another product's graph for the current user; yields its events until
        `done` or `error`."""
        ...

    async def search_creations(self, query: str, limit: int = 6) -> list[dict[str, Any]]: ...

    async def search_notebooks(self, query: str, limit: int = 5) -> list[dict[str, Any]]: ...

    async def readiness(self, need: Need) -> Readiness:
        """Whether one thing an action requires is ready here."""
        ...

    @property
    def deps(self) -> Any:
        """The `RouteDeps` (app state, database, storage, search index) that product code uses to
        reach the stores of the current user; `None` in a host that has none."""
        ...

    def facts(self) -> dict[str, Any]:
        """What `app.status` adds to the readiness list: free disk, models ready, the open screen.
        Small, no secrets, no paths of the person's files."""
        ...
