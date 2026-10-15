# ADR-0056: The desktop app and the web product share one engine; image first

- **Status:** Proposed
- **Date:** 2026-10-14
- **Depends on:** ADR-0002 (monorepo), ADR-0003 (FastAPI + LangGraph), ADR-0010/0017 (capabilities), ADR-0011
  (tenancy seams), ADR-0021 (event log and queue), ADR-0032 (media backends). Related: ADR-0057 (assistant),
  ADR-0058 (desktop link), ADR-0059 (ComfyUI sidecar). Supersedes the "separate product" decision recorded in
  ADR-0052 to 0054, which were withdrawn when the art studio moved to its own repository.

## Context

The owner wants one product family that people run **on their own computer** (desktop first, Mac first, local
models first, a cloud option with the user's own API key) and also in a **browser** (the web product, Linux only,
on the home lab's CPU nodes with paid API keys, no local GPU). The two must reuse code. wasifyai is the only
source of truth: the `wasifyai-art` repository (model hub, generation, remix, LoRAs, training spike) and the
`character-lora` dataset project are folded in and will be deleted.

What was checked for this decision:

- **Unsloth Desktop** (AGPL-3.0, Tauri 2) is a thin Rust shell around a Python backend and a React single-page
  app. The shell supervises processes, provisions a managed Python environment on first run (a bundled install
  script writing progress markers), updates itself, and hands the webview a token over loopback. The web
  "Studio" and the desktop window share one frontend build. Its image feature offers Create, Transform, Inpaint,
  Extend, Upscale, Reference and Edit, LoRA weights 0 to 2, ControlNet, a gallery that stores each result's recipe,
  and a model status/load/unload lifecycle. Generation is one synchronous request with a separate progress poll;
  the engine is an in-process Python diffusion stack (many `diffusion_*` modules for quantisation, GGUF, MPS fp16,
  offload, compilation). I read file lists and one API client, not the engine code.
- **wasifyai** already separates what the web product needs from what only a GPU host needs (remote media
  backends, ADR-0032; `SAFEGUARDS_FORCE_ON`, ADR-0047; hosted aliases, ADR-0025).
- **LangGraph weight, measured** in this repository's environment on the Mac: importing FastAPI, SQLAlchemy and
  LangGraph together peaks at about 105 MB resident and takes about 0.8 s; LangGraph itself adds about 35 MB and
  0.5 s. It is not heavy. LiteLLM is not installed in the API environment (it is a separate service), so it is
  not measured.
- **wasifyai-art results** (spike docs there): mflux trains FLUX.2 klein base 4B at about 7.5 s/step on the Mac;
  an adapter needs one key rename for ComfyUI; the trigger word binds with the shipped defaults **only** when
  the full timestep range is trained (mflux's own README example uses 25 to 40 of 40 and fails to bind).
- **Unsloth Phase 0, measured** (`docs/spikes/unsloth-phase0.md`, M5 Pro, 64 GB): ComfyUI makes a klein 4B image
  in 9 s warm against 17.6 to 18.9 s for Unsloth's default diffusers path and 27 s for its sd.cpp path; Wan 2.2 5B
  video runs in ComfyUI in 85 to 108 s while sd.cpp needs about 17 minutes for the VAE decode; audio.cpp
  transcribes at about 150x realtime and synthesises speech at about 10x; Unsloth's RAG store, chunker and
  retrieval work as source suggested, with dense search best on paraphrased questions.

## Decision

1. **One engine, two distributions.** `services/api`, the SDK and the contracts run under a **deployment
   profile**. `web`: Postgres, Redis Streams, S3 storage, the Next.js BFF, Helm. `desktop`: SQLite, an
   in-process queue and event log, local files, loopback plus a shell-issued token. A profile is configuration
   and adapters behind the interfaces that already exist (store, queue/event log, storage, secret store); product
   code never asks which profile it runs in (the rule 1 idea, for profiles).
2. **New workspace members.**
   - `apps/desktop`: the Tauri 2 shell (process supervision, provisioning, updater, tray, keychain, pairing,
     deep links). Written in Rust. AGPL-3.0-derived code, if any is taken from Unsloth, lives only here, with its
     notice.
   - `packages/ui` and `packages/client`: components (today in `apps/web/components/ui`) and a typed API client
     with a pluggable transport (BFF fetch on the web, loopback fetch on desktop). Screens move to shared
     modules that both a Next.js route and the desktop single-page app mount. The first spike is extracting one
     screen (the image create form) and proving it in both.
3. **Keep LangGraph.** The measurement above does not justify a second runner. Revisit only if the packaged
   desktop app exceeds a memory budget set in the spike (suggested: engine process idle under 300 MB).
4. **LLM gateway behind an interface.** Rule 5 stays: application code asks for an alias. Web: the LiteLLM
   service. Desktop: an in-process alias router over OpenAI-compatible endpoints (managed llama.cpp server,
   Ollama if present, a cloud provider with the user's key). LiteLLM as a library is adopted only if measured
   acceptable in the packaged app.
5. **One resident local model.** A **slot manager** in the engine owns the single large local model. A request
   for a different model queues behind the running job, then unloads and loads; the UI shows "switching model".
   Cloud calls never take the slot. **Utility models** (embedder for search, moderation classifier) are a named
   class that runs on CPU or is exempt; the class and its limits are set in config, not in code.
6. **Provisioning is a first-class feature.** Managed environments under the app data directory (uv, pinned
   versions, checksums from a component manifest), install progress as typed events, disk and memory checks
   before downloads, a repair action, configurable model and data folders including external drives, a
   graceful state when a drive is unplugged. Models download straight from their hosts.
7. **Mac first, three-OS CI from day one.** Builds and smoke tests run on macOS, Windows and Linux even before
   the latter two ship. Engines sit behind provider interfaces (MLX on Mac; CUDA or ROCm later). No hard-coded
   macOS paths or APIs outside `apps/desktop`.
8. **Order of verticals: image, documents, audio, video.** Image first because it is furthest along (create,
   remix, base models, LoRAs, ADR-0051 to 0053 in the art repository). Each later vertical is a product folder
   on the same engine. "Documents" is taken to mean document understanding (chat with files, retrieval,
   summaries); the owner confirms before it is designed.
9. **Consolidation.** The art repository's code moves in as the image product and the training service
   (inventory below). ADR-0052 to 0054 are re-opened as Proposed in a follow-up edit once this ADR is accepted.
10. **What the first image slice takes from Unsloth's feature set** (Phase 0 ran it): Create, Transform and Edit;
    LoRA weights; the gallery with a restorable recipe; a model status/load/unload panel with memory estimates.
    Inpaint, Extend, Upscale and ControlNet are listed for later. The engine for each capability is recorded in
    ADR-0062.
11. **English first.** Bengali and Hindi are not required in v1 and are added after release. Interfaces, data
    models and prompts still assume no particular language, so adding them is configuration and evaluation work.

## Port inventory from `wasifyai-art` (keep, with the lessons)

| Item | Where it goes | Note |
|---|---|---|
| Model registry, scanner, header-only safetensors parsing, family hints | catalog (ADR-0051) | `.safetensors` only |
| Generation, remix, `lora_chain`, stored recipe, upload hardening | image product, platform uploads | Overlaps ADR-0035/0052; reconcile, do not duplicate |
| LoRA training: datasets, captions, trainer service, converter, publish | `services/lora-trainer`, ADR-0054 re-opened | Default `timestep_low: 0`, `timestep_high: 40`, `sigmoid`; verify by the memorisation test |
| Spike results and grids | `docs/spikes/` | Binding on a mascot and on a synthetic and an external-character set |
| `character-lora` dataset tooling | evaluate; keep only what feeds training | Not read in full |

## Consequences

- Desktop and web evolve together; a feature is built once, in the engine, with two shells.
- A real extraction job: screens now live in a Next.js app and use server components; they must be restructured.
- Two storage back ends and two queue back ends to keep behaviourally identical (contract tests run on both).
- Provisioning and updates are new, large, platform-specific work (signing, notarization, AV quirks on Windows).
- The desktop product is AGPL-3.0 where it contains Unsloth-derived code; the platform stays Apache-2.0 and the
  NOTICE file records the boundary.

## Alternatives considered

- **Fork Unsloth Studio wholesale.** Fast start, but its backend is built around LLM chat and training; we would
  replace most of it and carry upstream churn. Kept as a reference and a source for the shell.
- **Electron.** Larger runtime, but a bundled Chromium. Rejected: Tauri is smaller and the shell is mostly
  process management.
- **A separate desktop repository.** Rejected: it recreates the divergence this ADR removes.
- **Replace LangGraph.** Rejected on measurement.

## Open questions

1. Meaning of "documents" for the second vertical.
2. Memory budget and the utility-model class.
3. Whether the SPA is Vite plus TanStack Router (as Unsloth) or Next.js static export.
