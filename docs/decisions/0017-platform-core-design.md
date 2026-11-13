# ADR-0017: Platform core: capability layer, usage events, storage and RAG

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

Phase 3 turns the walking skeleton into the reusable core that products build on: config-bound
capabilities (ADR-0010), usage metering (ADR-0011), object storage and vector search. MinIO's
community Docker image was withdrawn (pulls from Docker Hub and quay.io fail), so the storage
server named in earlier docs is no longer obtainable.

## Decision

- **Capability layer** (`wasifyai_platform_sdk`): `caps.text.stream/complete/embed(name, ...)` and
  `caps.image|music|video.generate(**inputs)`. A provider registry maps `provider:` in
  `product.yaml` to an implementation: `litellm` (text and embeddings), `comfyui` (media) and
  `fake` (tests). The API builds one `Capabilities` per product at startup.
- **Context, not parameters:** the runtime sets a task-local `RunContext` (tenant, product, user,
  run). Capabilities read it for usage events, job payloads and storage keys, so graph code
  cannot forget tenancy.
- **Config:** `product.yaml`, then `product.<env>.yaml`, then env vars `<PRODUCT_ID>__<PATH>`
  (e.g. `WASIFYAI_MUSIC__CAPABILITIES__MUSIC_GENERATE__WORKFLOW`). One Pydantic model validates the
  result at startup and reports every problem at once, including missing workflow or map files
  and mapped node IDs absent from the workflow JSON. Unknown keys are rejected. Free-form
  product values live under `settings:`.
- **Media jobs:** `comfyui` fills the workflow with mapped inputs and submits a `JobRequest` to a
  `JobSink`, returning a handle. It never calls ComfyUI. Until the Redis queue and worker land
  (Phase 4) the sink is in-memory.
- **Usage events:** LLM calls write `llm.input_tokens`, `llm.output_tokens` and
  `llm.embedding_tokens` rows to `usage_events` using the provider's reported usage. Recording
  failures are logged and never fail a request. Migration 0002 makes identity columns text (Auth.js
  subjects are strings) and adds indexes for quota and billing queries.
- **Storage:** one `Storage` interface over `obstore` (S3 API, GCS, Azure). Keys are
  `{tenant}/{product}/{user}/{path}`, built by `ScopedStorage` from the run context with segment
  validation. Responses carry presigned URLs. **SeaweedFS** replaces MinIO for dev
  and staging; because the interface is the S3 API, any S3-compatible server works.
- **RAG:** pgvector in the existing Postgres (`rag_chunks`, HNSW cosine index), scoped by tenant
  and product. Embeddings come from the product's `text.embed` capability: LiteLLM alias
  `embedder` to Ollama `nomic-embed-text` (768 dimensions). The column size is fixed by the
  migration; changing the embedding model means a new migration and re-embedding, and the code
  refuses to store vectors of the wrong size.
- **Gateway:** LiteLLM runs with `drop_params: true`, so parameters a backend rejects (for
  example `encoding_format` on Ollama embeddings) are dropped instead of failing the call.

## Consequences

- Graphs stay free of model names, node IDs and tenancy plumbing.
- Billing and quotas read existing rows. Per-user quotas (Phase 5) are a query on `usage_events`.
- The Helm chart does not deploy object storage yet; it is added when the media worker needs it
  (Phase 4). Locally, `make dev` runs SeaweedFS.
- Swapping the embedding model is deliberately a visible, migrated change.
