# ADR-0061: How Unsloth code enters wasifyai: a reference clone and selective import, not a repo move

- **Status:** Proposed
- **Date:** 2026-10-14
- **Depends on:** ADR-0056 (one engine, two shells), ADR-0059 (image engine), ADR-0002 (monorepo).

## Context

The owner asked whether to clone the Unsloth project, move wasifyai's code into it, and call that wasifyai. The
facts that decide it, from the research for ADR-0056 (file lists and selected source files read, the engine not run):

- Unsloth's repository is an **LLM fine-tuning library** (`unsloth/`, Apache-2.0) with an app under `studio/`
  (AGPL-3.0). The app has a Python backend (about 17 packages: inference, hub, library, models, training, export,
  data recipes, rag, mcp, auth, plugins, many `diffusion_*` modules), a React frontend with **33 feature folders**,
  and a Tauri 2 shell of about 36 Rust files.
- wasifyai has 56 ADRs, a platform core, 8 products, Helm and OpenTofu, tenancy and usage seams, an eval culture,
  and its own history. The rename to wasifyai alone touched 428 files.
- The app will diverge heavily: new look, removed features, changed workflow, new verticals. Merging upstream
  releases into a heavily changed tree is not realistic.

## Decision

1. **wasifyai stays the repository.** We do not move it into a clone of Unsloth. It is the single source of
   truth (owner's decision) and keeps its history, ADRs, licence (Apache-2.0) and CI.
2. **A reference clone lives outside the repo** (`~/Projects/_reference/unsloth`, pinned to a release tag). It is
   read and run for study. It is not a git remote of wasifyai and is never merged.
3. **Selective, recorded import.** Code is copied into wasifyai folder by folder, by decision, each with a
   `PROVENANCE.md` (source path, commit, date, what changed) and, for AGPL-3.0 material, a `LICENSE-AGPL` and
   header notice. Imported code lives only in `apps/desktop` (Rust shell) and clearly named packages, so the
   Apache-2.0 platform core stays separable (NOTICE records the boundary).
4. **Ownership after import.** Imported code is ours: we rename, restyle, delete and change it. Upstream fixes are
   cherry-picked only for security issues in the shell.
5. **Keep, adapt, replace, drop** (to be confirmed folder by folder in the Phase 0 spike, by running the app):

| Unsloth area | Plan |
|---|---|
| `src-tauri` shell: process supervision, single instance, tray, deep links, updater, staged updates, auth handoff, installer driver, log capture | **Import and adapt** (the main reuse) |
| `install.sh` / `install.ps1` and progress markers | **Adapt** for our component manifest (ComfyUI, models, ffmpeg) |
| Frontend app shell: routing, layout, settings, tour, i18n checks, bundle budget, model picker, loaded-models panel, generation presets | **Import as references, re-implement on `packages/ui`** (shadcn, our tokens) |
| Frontend `chat`, `images`, `library`, `audio`, `video`, `rag` features | **Reference** for UX; rebuilt on our contracts (ADR-0057, 0059, 0060) |
| Backend `inference`/llama.cpp lifecycle, hub download, model library | **Evaluate for reuse as library code** in the engine if it does not drag in torch; otherwise re-implement the small part we need |
| Backend `diffusion_*` modules | **Reference** only: measured about half ComfyUI's speed on this Mac (ADR-0059) |
| Backend `audio_cpp_*` and the prebuilt `audiocpp_server`, whisper.cpp | **Adopt as an engine** (measured: STT about 150x realtime, TTS about 10x; ADR-0062) |
| Backend `rag` parsers, chunker, locators, SQLite store | **Import** (ADR-0060; measured) |
| `training`, `export`, data recipes, LLM fine-tuning UI | **Drop** (our training is image LoRA, ADR-0056 inventory) |
| `cloudflare_tunnel`, `lan_access`, `mcp_server` | **Reference** for the remote UI and later features (ADR-0058) |
| `unsloth/` core library | **Not used** |

6. **Phases and gates.**
   - **Phase 0 (done, 2026-10-15):** the reference clone was installed in isolation and run: image engines,
     LoRA, cancel, TTS, STT and RAG were measured; video was measured only through ComfyUI and sd.cpp because no
     model family is shared. Results: `docs/spikes/unsloth-phase0.md`; the resulting reuse matrix is ADR-0062.
     Gate: the owner reviews ADR-0062.
   - **Phase 1 (first window):** import the Tauri shell into `apps/desktop`, point it at the wasifyai engine
     (desktop profile), show one shared screen (image create). Gate: it runs on macOS and the CI builds on all
     three OSes.
   - **Phase 2 (image slice):** ADR-0059 engine, provisioning, gallery with recipes, LoRAs and remix from the art
     repository's inventory. Then the assistant (ADR-0057), then documents (ADR-0060).
7. **The repo move was reconsidered at the Phase 0 gate and rejected.** Measured and read: the image and video
   engines are not kept, and the backend is 365k lines of LLM-centric code of which a few bounded parts are used.
8. **Licence boundary.** The owner accepts AGPL-3.0 for the product. The root licence of the repository is still
   to be decided explicitly (AGPL for all, or Apache-2.0 core with AGPL under `apps/desktop`); until then
   imported code keeps its notice and lives in clearly named folders.

## Consequences

- No history is lost and no licence is changed at the repository root; the AGPL surface is small and recorded.
- We pay for import work and for re-implementing what we do not copy, and we own all maintenance of the shell.
- Phase 0 delays the first import by a week, in exchange for decisions made from running software.

## Alternatives considered

- **Clone Unsloth and move wasifyai into it.** Fastest first window, but it makes an LLM fine-tuning repository the
  root of an unrelated platform: AGPL at the root, 56 ADRs and Helm charts inside a repo with a different purpose,
  a 428-file rename again, and history split. Rejected.
- **Long-lived fork with upstream merges.** Rejected: the divergence makes merges cost more than the code is worth.
- **Reference only, no code.** Cheapest legally, but throws away the hardest part to write (the cross-platform shell
  and provisioning). Rejected for the shell; kept for the frontend features.
