# ADR-0012: Music model: ACE-Step 1.5, not YuE2

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

`wasifyai-music` needs lyrics-to-song generation on a 24 GB GPU. YuE2-3B (released 2026-09) has strong benchmarks, but its ComfyUI support was initially on a separate branch.

## Decision

Use ACE-Step 1.5 (Turbo variant to start) via mainline ComfyUI, behind the `music.generate` capability.

## Consequences

- Swapping models later is a config change (ADR-0010).
