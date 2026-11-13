# ADR-0019: Cover image model: FLUX.2 [klein] 4B

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

`wasifyai-music` generates cover art through ComfyUI behind the `image.generate` capability. The
first choice, Qwen-Image, is too large for a prototype. Candidates were FLUX.2 [klein] 4B and
Stable Diffusion 1.5.

## Decision

Use **FLUX.2 [klein] 4B** (distilled) at 1024x1024 as the cover image model, via
mainline ComfyUI. The workflow name is `flux2-klein-4b`.

Why not SD 1.5: native 512x512 (the config asks for 1024), noticeably weaker prompt following and
composition, and a repository that is a community mirror of a deprecated original.

Not chosen for laptops either: neither model is practical on CPU-only machines. Developers
without a capable GPU use the stub media worker (Phase 4), which returns sample images. If real
images on small machines become necessary, SD 1.5 can be added as a `product.dev.yaml` overlay,
because swapping a workflow is a config change (ADR-0010).

## Consequences

- Needs about 13 GB VRAM at full precision (about 7.8 GB at FP8, about 5.9 GB at NVFP4, per the
  vendor). The staging 24 GB GPU is ample, and the worker unloads the LLM before each job.
- Rendered text in images can be distorted; cover prompts should avoid asking for lettering.
- The 9B klein variant is not used.
- **To verify in Phase 5:** exact ComfyUI nodes and text-encoder files (they add to the download),
  real generation time on the lab GPU, and Apple Silicon feasibility. Vendor figures are
  unmeasured on our hardware.
