"""Graph registry: products register graph builders; the API exposes them generically."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from wasifyai_platform_sdk.capabilities import Capabilities
from wasifyai_platform_sdk.routes import RouteFactory
from wasifyai_platform_sdk.search import IndexSourceFactory

# builder(caps, checkpointer) -> compiled LangGraph graph
GraphBuilder = Callable[[Capabilities, Any], Any]


@dataclass
class CheckResult:
    """What a product's model check found: `failures` are short, safe-to-show sentences."""

    passed: bool
    failures: list[str] = field(default_factory=list)
    ran: int = 0


# check(caps) -> CheckResult, run with capabilities bound to a candidate model (ADR-0025). A product
# registers one for a capability whose model must be vetted before an admin can change it.
ModelCheck = Callable[[Capabilities], Awaitable[CheckResult]]


class GraphRegistry:
    def __init__(self) -> None:
        self._builders: dict[str, GraphBuilder] = {}
        self._routes: dict[str, RouteFactory] = {}
        self._checks: dict[tuple[str, str], ModelCheck] = {}
        self._sources: dict[str, IndexSourceFactory] = {}

    def register(self, product_id: str, builder: GraphBuilder) -> None:
        if product_id in self._builders:
            raise ValueError(f"graph already registered for product {product_id!r}")
        self._builders[product_id] = builder

    def add_routes(self, product_id: str, factory: RouteFactory) -> None:
        """Register product-provided API routes, mounted under /products/{product_id}/."""
        self._routes[product_id] = factory

    def add_index_source(self, product_id: str, factory: IndexSourceFactory) -> None:
        """Make this product's creations searchable (ADR-0041): `factory(engine)` returns an
        `IndexSource`. Every product that lets a user keep something must register one."""
        self._sources[product_id] = factory

    def index_sources(self) -> dict[str, IndexSourceFactory]:
        return dict(self._sources)

    def add_check(self, product_id: str, capability: str, check: ModelCheck) -> None:
        """Vet any model that is about to serve `capability` (for example `text.moderate`)."""
        self._checks[(product_id, capability)] = check

    def checks(self) -> dict[tuple[str, str], ModelCheck]:
        return dict(self._checks)

    def route_factories(self) -> dict[str, RouteFactory]:
        return dict(self._routes)

    def build(self, product_id: str, caps: Capabilities, checkpointer: Any) -> Any:
        try:
            return self._builders[product_id](caps, checkpointer)
        except KeyError:
            raise KeyError(f"unknown product {product_id!r}") from None

    def load_entry_points(self, group: str = "wasifyai.products") -> list[str]:
        """Let installed product packages register their graphs. A product declares

            [project.entry-points."wasifyai.products"]
            wasifyai-voice = "wasifyai_voice:register"

        where `register(registry)` calls `registry.register(...)`. Returns the names loaded."""
        loaded = []
        for ep in entry_points(group=group):
            ep.load()(self)
            loaded.append(ep.name)
        return loaded

    def products(self) -> list[str]:
        return sorted(self._builders)
