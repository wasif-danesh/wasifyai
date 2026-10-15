# Phase 2, stage A: real images in the desktop app (plan)

Status: **Approved 2026-10-15** with the five recommended answers below. **A1 and A2 done** (see
`docs/spikes/desktop-phase1.md`, "stage A1" and "stage A2"). Implements ADR-0059 (ComfyUI sidecar), ADR-0056
decisions 5 and 6 (slot manager, provisioning) and the first slice of ADR-0061 phase 2. Evidence base:
`docs/spikes/unsloth-phase0.md` (ComfyUI 9 s warm, 14 s cold for klein 4B on the M5 Pro, 17.6 GB process peak)
and `docs/spikes/desktop-phase1.md`.

**Goal.** On an Apple-silicon Mac, type a prompt in the window and get a real FLUX.2 klein 4B image, through
the same queue, events and storage as today, with no manual setup beyond two clicks ("Set up image
generation", "Get the model") and no change to the web product.

**Not in this stage:** gallery and recipes (stage B), LoRAs and remix (stage C), Windows and Linux GPUs,
quantised models for 16 GB Macs, video. The window keeps the placeholder engine as a fallback and for CI.

## What exists and what changes

| Exists | Change |
|---|---|
| `ComfyUIProvider` builds a job from `flux2-klein-4b` and `-edit` workflows; both use **core ComfyUI nodes only** (no custom nodes) | none |
| `ComfyRunner` in the media worker drives ComfyUI over HTTP and WebSocket | keep the model loaded between jobs; free it on idle or on request (today it frees after every job) |
| Installer: uv, Python 3.12.15, engine environment (step 3) | a second, optional component: ComfyUI source and its own environment |
| `DESKTOP_IMAGE_ENGINE=stub|comfyui`, `COMFYUI_BASE_URL` | the engine starts and supervises ComfyUI and sets the URL itself |
| Models: none managed | a models folder, a catalogue entry for klein, a download manager, a read-only extra folder |

## Design

### 1. ComfyUI as an optional component, installed on demand

- **Pin:** ComfyUI **v0.40.0** (the version measured in Phase 0), from the GitHub source archive of the tag,
  with its SHA-256 and size in `engine-manifest.json`, unpacked to `<app data>/engine/comfyui/0.40.0`.
- **Environment:** a second venv, `<app data>/engine/comfyui-venv`, from the same uv and Python 3.12.15, with
  ComfyUI's requirements installed `--require-hashes` from a lock file generated at release time (like
  `requirements.lock` for the engine) and shipped in the engine bundle. Torch comes from PyPI on macOS (MPS).
- **When:** not at first run. The first run stays the 25 s install. A "Set up image generation" action in the
  window installs the component with the same step-by-step progress and Repair. Needs disk (to be measured,
  expected 1.5 to 3 GB) and checks it first.
- **Verify step:** import torch, check `torch.backends.mps.is_available()`, start the server once and read
  `/system_stats`.

### 2. The sidecar process

- Owned by the **engine** (ADR-0059), started on the first image job or when set-up finishes, restarted on
  crash with a backoff, stopped with the engine. It runs in the engine's process group, so the shell's tree
  kill covers it after a crash.
- `main.py --listen 127.0.0.1 --port <free> --base-directory <app data>/comfyui --extra-model-paths-config
  <generated> --disable-auto-launch`, custom nodes folder empty (allowlist = none, since the workflows need none).
- Output and input folders are inside the app data folder; results are read back through `/view` and stored
  through the storage interface exactly as now.

### 3. Models

- **Models folder:** `<app data>/models` by default, configurable (external drives). ComfyUI is pointed at it
  with a generated `extra_model_paths.yaml`. Unplugged drive: the models panel says so; jobs fail with a typed,
  user-safe error.
- **Read-only extra folder:** a second path ComfyUI may read from. On the owner's Mac this is how
  `~/ComfyUI-Shared` is used with no 16 GB copy. The app never writes there and never deletes from it.
- **Catalogue (first entry, klein 4B):** from `Comfy-Org/flux2-klein-4B` on Hugging Face (Apache-2.0, not gated):

  | File | Size | Needed |
  |---|---|---|
  | `diffusion_models/flux-2-klein-4b.safetensors` | 7.75 GB | yes |
  | `text_encoders/qwen_3_4b.safetensors` | 8.04 GB (a 3.85 GB fp4 variant exists) | yes |
  | `vae/flux2-vae.safetensors` | 0.34 GB | yes |

  Each entry pins SHA-256 and size; the SHA-256 of the files in `~/ComfyUI-Shared` is compared with the
  catalogue before they are accepted as the same files.
- **Download manager:** only on a click that has shown the file names, sizes, source and licence; resumable;
  checksum verified before the file is moved into place; disk check first; progress in the window. **No model
  is downloaded without that click** (and I will not download one while developing without asking you).
- **Memory gate:** bf16 klein needs about 17.6 GB at peak. The window shows the model's estimate and the
  computer's RAM, and warns below 24 GB. Quantised variants for smaller Macs are a later decision.

### 4. Slot manager (ADR-0056 decision 5)

A small service in the engine owns "the one big local model": `acquire(owner)` before a job, `release` after,
**idle unload** after a configurable time (default 10 minutes) through ComfyUI's `/free`, and an explicit
"unload" in the window. Owners are `image` now; `chat` joins in the assistant stage. The failure modes Unsloth's
`gpu_arbiter.py` handles (an in-flight load, the owner changing while loading, memory settling after an unload)
are written as test cases first.

### 5. Window

An "Image engine" panel: not set up / installing (steps) / starting / ready / loading model / error with
Repair; the models list with sizes, which folder each is in, Get / Remove; model loaded or not, with Unload;
folder settings. New engine routes live under `/desktop/...` (additive, token-protected). Long actions report
progress by a polled JSON endpoint, so the SSE contract is unchanged.

## Order of work

Each step ends with its tests run and a short report, as in Phase 1.

| Step | Work | How it is verified |
|---|---|---|
| A1 | Manifest entries, release-time lock script, installer steps for the ComfyUI component, window set-up flow | Fake-uv tests as in step 3; on the Mac, a real install; server starts and `/system_stats` reports MPS |
| A2 | Sidecar manager, runner keeps the model loaded, slot manager | Unit tests against a fake ComfyUI (the media worker's existing fake); on the Mac, a real image from the owner's folder through the window self-test; time and memory recorded against Phase 0 |
| A3 | Models folder, extra path, catalogue, download manager, memory gate, window panel | Download tests against a loopback server (resume, wrong checksum, disk); the window flow by hand with the owner's files; no real download without approval |
| A4 | Docs, ADR-0059 consequences updated, CI | A CI job installs the ComfyUI component on a macOS runner and starts it without a model; the rest stays on the stub |

## Decisions (all five approved as recommended)

1. **Platforms.** Real images in stage A on **Apple silicon only**. Windows and Linux install the engine as
   today and keep the placeholder engine, with an honest message, until a CUDA stage. Intel Macs are not
   supported for real images. Agreed?
2. **Token.** ADR-0059 asks for a per-launch token between the engine and ComfyUI. **ComfyUI cannot enforce
   one.** Proposal: loopback only, random port, engine-owned process, the window never talks to it; the residual
   risk is that another program run by the same user can reach it (the same as any local server such as Ollama).
   A proxy that enforces a token is possible but adds a moving part. Accept the loopback boundary?
3. **When it installs.** On demand (a button), not at first run. Agreed?
4. **First model.** bf16 klein 4B, 16.1 GB in total, needing about 24 GB of RAM. The fp4 text encoder (saves
   4.2 GB) can be offered as a second catalogue entry once its quality is looked at. Start with bf16?
5. **Source of models.** Hugging Face `Comfy-Org/flux2-klein-4B`. Any objection?
