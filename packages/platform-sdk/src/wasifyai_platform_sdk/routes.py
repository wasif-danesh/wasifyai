"""Product-provided API routes (ADR-0023).

A product can expose read endpoints for its own data (a user's songs, say) next to its graph. It
registers a factory; the API mounts the router under `/products/{product_id}/` and supplies what a
route needs: the identity dependency, the database and storage. Routes must depend on
`deps.identity` (rule 8: no endpoint skips identity) and must scope every query by tenant, product
and user.

    def register(registry):
        registry.register("my-product", build_graph)
        registry.add_routes("my-product", build_routes)

    def build_routes(deps: RouteDeps) -> APIRouter:
        router = APIRouter()

        @router.get("/things")
        async def things(identity: Identity = Depends(deps.identity)): ...
        return router
"""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.context import RunContext, reset_context, set_context
from wasifyai_platform_sdk.identity import Identity
from wasifyai_platform_sdk.services import EngineServices
from wasifyai_platform_sdk.storage import ScopedStorage

MAX_IDS = 50


def parse_ids(raw: str | None) -> list[str] | None:
    """A comma-separated `ids` query parameter (what My creations asks a list route for after a
    search, ADR-0041): None when absent, else up to 50 distinct UUIDs in the order given."""
    if raw is None:
        return None
    ids = list(dict.fromkeys(i.strip() for i in raw.split(",") if i.strip()))
    if len(ids) > MAX_IDS:
        raise HTTPException(422, f"Please ask for at most {MAX_IDS} items at a time.")
    for i in ids:
        try:
            UUID(i)
        except ValueError:
            raise HTTPException(422, "Those ids are not valid.") from None
    return ids


@dataclass
class RouteDeps:
    """What a product's routes can use. `state` is the engine's services (stage F1): one object made
    with the app and filled in when it starts, so what a route uses is read at request time, not
    when routes are built."""

    state: EngineServices
    identity: Callable[
        ..., Identity | Awaitable[Identity]
    ]  # a FastAPI dependency: Depends(deps.identity)

    @property
    def engine(self) -> AsyncEngine:
        if self.state.engine is None:  # only before the app has started
            raise RuntimeError("the engine has not started yet")
        return self.state.engine

    @property
    def storage(self) -> ScopedStorage | None:
        return self.state.storage

    async def unindex(self, identity: Identity, product_id: str, item_id: str) -> None:
        """Take a deleted creation out of search (ADR-0041). Best effort: the background indexer
        also removes rows whose item is gone."""
        index = self.state.creation_index
        if index is None:
            return
        try:
            await index.remove(identity.tenant_id, product_id, item_id)
        except Exception:
            pass

    @contextmanager
    def acting_as(self, identity: Identity, product_id: str) -> Iterator[None]:
        """Run storage calls (`ScopedStorage`) for this user, as a graph run would."""
        token = set_context(RunContext(identity.tenant_id, product_id, identity.user_id))
        try:
            yield
        finally:
            reset_context(token)


RouteFactory = Callable[[RouteDeps], APIRouter]
