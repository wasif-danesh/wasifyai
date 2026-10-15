# ADR-0059: ComfyUI as the managed image engine of the desktop app

- **Status:** Accepted (2026-10-15)
- **Date:** 2026-10-14
- **Depends on:** ADR-0010, ADR-0017, ADR-0024, ADR-0051 (variants, `lora_chain`), ADR-0056 (profiles, slot
  manager, provisioning). Uses the provider interfaces of ADR-0032.

## Context

The desktop image vertical needs an engine. wasifyai already has verified ComfyUI workflows with map files, a
LoRA chain, remix and training outputs that load in ComfyUI. Unsloth chose an in-process Python diffusion engine
with many custom modules instead (read from file names; not run). Comfy Desktop, the official app, ships ComfyUI
with its own managed Python environment (this Mac has one); its repository was reported archived in June 2026,
which I could not confirm.

**Measured in Unsloth Phase 0** (`docs/spikes/unsloth-phase0.md`, M5 Pro, FLUX.2 klein 4B, 1024x1024, 4 steps):
ComfyUI 9 s warm (14 s cold); Unsloth's default diffusers path 17.6 to 18.9 s; its GGUF path 20.5 to 21.7 s; its
sd.cpp path 27 s; sd.cpp called directly 27 to 28 s of sampling; its MLX engine does not cover klein. For video
(Wan 2.2 TI2V 5B, 640x352, 33 frames, 10 steps) ComfyUI took 85 to 108 s and sd.cpp 58 s of sampling plus a
17.5 minute VAE decode. sd.cpp also crashes on the fp8 text-encoder files ComfyUI uses.

## Decision

**Run ComfyUI as a managed sidecar** of the desktop engine, behind the existing `comfyui` provider, with
these constraints:

1. **Our own environment,** created by the provisioner with uv from pinned versions and checksums. We do not use
   or redistribute Comfy Desktop's bundle and we do not touch a user's existing ComfyUI.
2. **Pinned ComfyUI version,** upgraded deliberately, with an integration suite that runs every shipped workflow
   through the HTTP and WebSocket API (ADR-0024 style) before an upgrade is accepted.
3. **Loopback only,** random port, a per-launch token injected by the shell, the process owned by the engine.
4. **Custom nodes are an allowlist** shipped with the app and pinned. No user-installed nodes in v1. Workflows
   come from our repository, never from user files (ComfyUI workflows can reference any installed node).
5. **Model paths** come from the configured models folder (external drives supported) through
   `extra_model_paths`; models are read-only to the sidecar.
6. **Slot-managed.** The slot manager (ADR-0056) loads and unloads through ComfyUI's API; idle unload after a
   timeout so memory returns to the OS.
7. **Provider interface stays open.** A second image provider (a diffusers or MLX engine, or stable-diffusion.cpp)
   can be added without touching products. The decision to add one is data-driven: size, start time, or memory
   on the target machines.

## Pros and cons (from the research and from our own runs)

| Pros | Cons |
|---|---|
| Reuses every workflow, map file, variant and `lora_chain` (ADR-0010/0051) and the verified real runs | Large: Python plus PyTorch environment, several GB, plus a long first provision |
| Broad model support quickly (new families appear in ComfyUI first) | Process supervision, port and crash handling are ours |
| Same engine as our web staging and as users' mental model of "ComfyUI" | No documented stable embedding API; internals change between releases (pin and test) |
| LoRA files trained here load without conversion (after the one key rename) | Custom nodes run arbitrary code in the process; registry nodes have had vulnerabilities |
| Official project shows the pattern works | GPL-3.0: keep it a separate process, ship its notice and source offer (NOTICE already records this) |
| Headless mode and localhost default are documented | Cold start is slower than an in-process engine; memory is separate from the Python engine |

## Consequences

- The provisioner owns a second environment (the engine's and ComfyUI's differ in versions).
- Security review of the allowlist is part of every release.
- A smaller "lite" tier (one binary, GGUF, no Python, for example stable-diffusion.cpp) can be added later
  behind the same interface if size or start time hurts adoption.

## Alternatives considered

- **In-process diffusers engine (Unsloth's approach):** measured at about half ComfyUI's speed on this Mac, and
  it duplicates model files that a shared folder already holds. Not adopted; its gallery, recipe and memory-guard
  ideas are reused as references (ADR-0062).
- **sd.cpp (native binary):** about 3x slower for images and unusable for video until the Wan VAE decode is fixed
  (measured). It remains a candidate provider for machines without torch acceleration. Re-measure on a newer build
  before reconsidering; the switch itself is a new provider, not a product change.
- **mflux / MLX only:** fastest on a Mac and already working for training; Apple-only and narrower model support.
  Kept for training and as a possible Mac image provider.
- **Use the user's installed ComfyUI:** unpredictable versions and nodes; supported later as an "external
  ComfyUI" backend address (already possible, ADR-0032).
