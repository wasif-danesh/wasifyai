# ADR-0023: Product-provided API routes

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

The generic run API (`POST /products/{id}/runs`, events, resume) is enough to create things, but a
product also needs to read its own data back: "My songs" needs a user's songs, and their audio links
expire after an hour, so each read must sign fresh ones. ADR-0003 said a product adds no API
endpoints; that holds for running graphs but not for reading a product's results.

## Decision

A product can register an authenticated router next to its graph, through the same entry point:

```python
def register(registry):
    registry.register("wasifyai-music", build_song)
    registry.add_routes(
        "wasifyai-music", build_routes
    )  # build_routes(deps: RouteDeps) -> APIRouter
```

The API mounts it under `/products/{product_id}/`. `RouteDeps` supplies what a route may use: the
identity dependency (`Depends(deps.identity)`), the database engine, storage, and `acting_as(...)`
to run storage calls for the requesting user. Routes are mounted when the app is created, so they
appear in the OpenAPI document and in the generated TypeScript types.

Rules for product routes: depend on `deps.identity` (rule 8), scope every query by tenant, product
and user, and answer 404 (not 403) for anything that is not the caller's, so existence is not leaked.

`wasifyai-music` uses this for `GET /products/wasifyai-music/songs` (newest first, keyset-paginated by
`before`) and `GET /products/wasifyai-music/songs/{song_id}` (with lyrics). Both sign fresh audio and
cover links on every call.

## Consequences

- A test (`test_every_product_route_requires_an_identity`) makes the identity dependency reject
  everyone and requires every product route to answer 401. A new product route that forgets identity
  fails CI.
- Product data stays in the product package; the platform learns nothing about songs.
- The shared `Identity` type moved into `wasifyai_platform_sdk` so products can use it.
- Writes still go through graphs. A product route that mutates data needs its own decision.
