"""A fake engine for tests of actions: scripted child runs, scripted readiness, scripted hits.

    host = FakeActionHost()
    host.script("wasifyai-image", [{"event": "done", "outputs": {...}}])
    host.not_ready(need_model("speak"), Readiness.needs_setup("Set up the speech models"))

Every action of every product is run against it by the catalogue tests, so a product that adds an
action adds its case there (`services/api/tests/test_actions_catalogue.py`)."""

from collections.abc import AsyncIterator, Callable
from typing import Any

from wasifyai_platform_sdk.actions.model import Need, Readiness
from wasifyai_platform_sdk.tools import ToolUnavailable

Script = list[dict[str, Any]] | Callable[[dict[str, Any]], list[dict[str, Any]]]


class FakeActionHost:
    def __init__(self, deps: Any = None) -> None:
        self.runs: list[tuple[str, dict[str, Any]]] = []
        self.searches: list[str] = []
        self.notebook_searches: list[str] = []
        self.notebook_error: str | None = None
        self.hits: list[dict[str, Any]] = []
        self.passages: list[dict[str, Any]] = []
        self.fact_values: dict[str, Any] = {"disk_free_bytes": 10_000_000_000}
        self._deps = deps
        self._scripts: dict[str, Script] = {}
        self._readiness: dict[str, Readiness] = {}

    def script(self, product_id: str, events: Script) -> None:
        self._scripts[product_id] = events

    def not_ready(self, need: Need, readiness: Readiness) -> None:
        self._readiness[str(need)] = readiness

    @property
    def deps(self) -> Any:
        return self._deps

    def facts(self) -> dict[str, Any]:
        return dict(self.fact_values)

    async def readiness(self, need: Need) -> Readiness:
        return self._readiness.get(str(need), Readiness.ready())

    async def run_product(
        self, product_id: str, graph_input: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        self.runs.append((product_id, graph_input))
        script = self._scripts.get(product_id, [])
        for ev in script(graph_input) if callable(script) else script:
            yield ev

    async def search_creations(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        self.searches.append(query)
        return self.hits[:limit]

    async def search_notebooks(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        self.notebook_searches.append(query)
        if self.notebook_error:
            raise ToolUnavailable(self.notebook_error)
        return self.passages[:limit]
