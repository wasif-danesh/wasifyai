# ADR-0003: FastAPI hosting LangGraph as a library

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

LangGraph is a library and needs an HTTP host. Options: a custom FastAPI service, LangGraph's own server (LangSmith Deployment), or LangGraph.js inside Next.js.

## Decision

Write a FastAPI service that runs LangGraph as a library, with the Postgres checkpointer. Products register graphs at startup through a graph registry; generic routes (`/products/{product_id}/runs`, `/runs/{id}/events`, `/runs/{id}/resume`, job callbacks) serve all graphs. `langgraph dev` / Studio may still be used locally for debugging.

## Consequences

- Full control over identity, tenancy, metering and job callbacks; plain container.
- Thread/run management and streaming plumbing must be built (a one-off cost).
- LangGraph.js rejected: long-running graphs don't belong in web request handlers, and the AI tooling is Python.
