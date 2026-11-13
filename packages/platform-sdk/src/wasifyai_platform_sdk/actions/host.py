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

    async def run_state(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        """How a product run stands (a job follows it after a restart, stage J3): `status` is
        `running`, `waiting_job`, `waiting_input`, `done`, `error`, `cancelled` or `unknown`
        (no such run, or one that ended with an engine that closed), and `end` its last event
        once it has ended."""
        ...

    async def cancel_run(self, tenant_id: str, run_id: str) -> bool:
        """Stop a product run and the work it is waiting on. False when it had ended."""
        ...

    async def search_creations(self, query: str, limit: int = 6) -> list[dict[str, Any]]: ...

    async def search_notebooks(self, query: str, limit: int = 5) -> list[dict[str, Any]]: ...

    async def web_search(self, query: str, limit: int = 5) -> Any:
        """Search the web with the provider the person chose (a `web.SearchResponse`); raises
        `web.WebError` with a sentence for the person."""
        ...

    async def web_read(self, url: str) -> Any:
        """Read one public web page (a `web.WebPage`); raises `web.WebError`."""
        ...

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
