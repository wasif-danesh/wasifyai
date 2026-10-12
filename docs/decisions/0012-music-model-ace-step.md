# ADR-0012: Music model: ACE-Step 1.5, not YuE2

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

`wasifyai-music` needs lyrics-to-song generation on a 24 GB GPU. YuE2-3B (released 2026-09) has strong benchmarks but is licensed CC-BY-NC-4.0 (non-commercial), and its ComfyUI support was initially on a separate branch.

## Decision

Use ACE-Step 1.5 (Turbo variant to start) via mainline ComfyUI, behind the `music.generate` capability. Its model card states generated music may be used commercially; sources differ on MIT vs Apache 2.0, so the licence must be verified before launch. YuE2 may be reconsidered only if relicensed for commercial use.

## Consequences

- Commercial launch is not blocked by the music model licence.
- Swapping models later is a config change (ADR-0010).
