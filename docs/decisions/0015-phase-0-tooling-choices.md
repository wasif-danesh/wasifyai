# ADR-0015: Phase 0 tooling choices

- **Status:** Accepted (prototype LLM superseded by ADR-0018)
- **Date:** 2026-10-07

## Decision

- Type checking: pyright. TS lint/format: Biome. TS tests: Vitest.
- Streaming client: a small custom `EventSource`/fetch hook (no Vercel AI SDK).
- Object storage interface: obstore.
- Primary cloud: GCP (GKE, Cloud SQL, GCS). AWS and Azure stay deployable but not running.
- Prototype LLM: `gpt-oss:20b` via Ollama, behind the LiteLLM aliases `lyrics-writer` and `moderator`.
- Prototype defaults: 10 songs per user per day; MP3 audio output.
