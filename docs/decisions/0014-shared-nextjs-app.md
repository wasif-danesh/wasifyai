# ADR-0014: One shared Next.js app with route groups

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

Each product needs a frontend. Separate apps duplicate Auth.js config, the BFF proxy and the streaming hook.

## Decision

A single `apps/web` Next.js app with one route group per product (e.g. `app/(wasifyai-music)/`). Shared auth, BFF and SSE client code live once.

## Consequences

- Less duplication; one deployable.
- Products share a release cadence. Split an app out later if that becomes a problem.
