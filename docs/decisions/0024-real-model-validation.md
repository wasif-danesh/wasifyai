# ADR-0024: Real-model validation of the music and cover workflows

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

The ACE-Step 1.5 and FLUX.2 klein 4B workflows (ADR-0012, ADR-0019) had only been
structure-validated. Phase 5 required running them for real on the dev Mac (ComfyUI 0.39,
native) and through the full product UI.

## Decision

- **Both workflows are confirmed** as written: they match the official ComfyUI templates.
  ACE-Step uses the all-in-one Turbo checkpoint (8 steps, cfg 1, euler/simple, shift 3); klein
  uses separate UNET, `qwen_3_4b` text encoder and VAE (4 steps, cfg 1).
- **Measured on the dev Mac:** a 60 s song takes about 77 s; a 1024x1024 cover about 25 s.
  The output is a valid MP3 of the requested length with the lyrics sung in order; the cover is
  a valid 1024x1024 PNG.
- **Lyric length is a product constraint.** ACE-Step fits about four seconds per sung line, so
  the prompt asks for 12 to 16 lines for 60 s and the validator rejects more than 20.
  Section tags must be on their own line; inline tags are split out by `normalise_lyrics`.
- **VAE:** Klein 4B's VAE is taken from the Comfy-Org/flux2-klein repo. The official template
  points at the flux2-dev VAE; do not use it.
- **Style control** (genre, tempo, vocal gender) is measurable but imperfect. Judging it with
  `gemma4:e4b` as a listener was unreliable, so objective audio metrics were used instead.
- **Opt-in tests:** `make test-comfyui` runs both product workflows through the job processor
  against a real ComfyUI and skips any whose models are not installed.

## Consequences

- Real generation needs `COMFYUI_MODE=real`, ComfyUI running, and the three model files.
- The worker unloads the LLM before GPU work, so a first run after a song pays a model reload.
