# ADR-0054: LoRA training: dataset, captions, trainer service, publish

- **Status:** Withdrawn (2026-10-12). The TensorArt-style studio will not be built (owner, 2026-10-24); wasifyai does not implement it. Nothing here was built.
- **Date:** 2026-10-12
- **Depends on:** ADR-0051 (catalog, LoRA chain). Follows the pattern of ADR-0044 (an external native service) and
  ADR-0037 (a long job the user can leave).

## Context

The owner wants to train a LoRA from images they upload and then use it in the image studio (ADR-0052). This is a
learning project first, so the target machine is **the development Mac** (Apple silicon, Metal); a CUDA host is a
later option, not a requirement. What is known from what was read, and what is not:

- LoRA training for FLUX.2 klein 4B is well documented on **NVIDIA** with ai-toolkit (about an hour on a 24 GB
  card, per the BFL/Hugging Face walkthrough).
- On Apple silicon, ai-toolkit's MPS path is reported **not to converge** for FLUX.2-dev (its issue was closed as not
  planned; that is a different model). MLX-native trainers exist (mflux lists FLUX.2 LoRA training; a Swift/MLX
  project also does), but **no verified FLUX.2 klein recipe on a Mac was found**. Treat Mac training as an
  experiment with an unknown speed and a real chance of failing.
- The platform has no trainer, no multi-image upload (the hourly picture limit is 60, ADR-0039), a global job
  timeout of 1200 s, and one job at a time per GPU id (ADR-0021).

## Decision

- **A new product `wasifyai-lora-ai`** (web area `/lora`) and a **new service `services/lora-trainer`**, shaped like
  Lip Sync (ADR-0044): a small HTTP server run **natively on the Mac** (`scripts/lora-trainer-server.sh`, since a
  container cannot reach Metal), reached by the media worker at `TRAINER_SERVER_URL`. A CUDA container of the same
  server is the same code later. `TRAINER_MODE=stub|real`: stub writes a tiny valid placeholder LoRA and sample
  images with simulated progress, so Compose, kind and CI run the whole flow without a GPU.
- **Trainer API:** `POST /v1/train` (family, preset, trigger word, presigned GET URLs for the dataset, presigned
  PUT URLs for checkpoints and samples), `GET /v1/train/{id}` (state, step, loss, files), `POST /v1/train/{id}/cancel`.
  No shared filesystem is needed; the trainer only speaks to storage through URLs.
- **Engine per family, chosen in config, not in code:** `settings.training.families.<family>.engine` in
  `product.yaml`. Candidates for `flux2-klein`: **mflux** (MLX, Mac) and **ai-toolkit** (CUDA). The spike decides
  which is the default on the Mac; if neither works, the product is built and tested against the stub and real runs
  wait for a CUDA host, exactly as ADR-0044 recorded for InfiniteTalk.
- **One GPU, shared.** On the Mac, ComfyUI and the trainer have the same `GPU_ID`, so a training run holds the lock
  and **image generation waits for it** (hours, possibly). This is accepted for the first version: the page says
  so before starting, the run can be cancelled, LLMs are unloaded first (existing behaviour), and nothing is
  preempted. A separate `GPU_ID` (a lab box) removes the wait without code changes.
- **Per-capability timeout.** `lora.train` binds `timeout_s` (default 14400); the worker uses it instead of
  `JOB_TIMEOUT_S` for that capability. Progress is the existing `job_progress` fraction; sample images and step
  counts are read by the product's own route from the trainer through the worker's job record, like a video being
  made (no SSE contract change).
- **Dataset upload** (platform change): an upload kind `dataset_image` with its own limits: at most 100 images per
  dataset, 10 MB each, 500 uploads per hour; the same hardening as ADR-0035 (decode, EXIF-rotate, strip metadata,
  PNG, 24 MP cap). Perceptual hashes flag duplicates; images under 512 px are flagged, not refused.
- **Captions through the platform's multimodal alias** (`text.describe_image`, ADR-0038): no new model or service.
  A per-kind prompt (*character*: clothing, pose, background, not identity; *style*: the content, not the style;
  *concept*). The trigger word is injected and validated into every caption before a run can start. Captioning is
  a background job with progress (rule 6). **Captions are normalised to English** because the text encoders are
  English-trained: a recorded multilingual limitation, to be revisited, not an assumption.
- **Presets** `fast | balanced | quality` per family in `product.yaml` (steps, rank, learning rate, resolution,
  batch, sample interval). The numbers come from the spike; none are guessed in this ADR. The page shows an
  estimated time measured on this machine.
- **Publish.** The user picks a checkpoint; the worker writes the file into `LORAS_DIR` (a Compose volume, the
  ComfyUI PVC in Kubernetes; on the Mac the shared folder `~/ComfyUI-Shared/models/loras`), adds a catalog row
  (`source=trained`, family, trigger word, preview, owner = the maker; ADR-0051), and the row becomes `ready` when
  ComfyUI lists the file. A trained LoRA is therefore usable in `/image` with no admin step.
  "Try it" makes four sample images through this product's own `image.generate` binding with the LoRA applied.
- **Data and retention.** A dataset belongs to its owner and is kept until they delete it (needed to edit captions
  and retrain); deleting it removes the files. A dataset left in `draft` for 7 days is swept. Unused uploads and
  failed-run artefacts are removed with the run.
- **Tables:** `lora_datasets`, `lora_dataset_images`, `lora_runs`, `lora_checkpoints`. **Quota:**
  `lora_trainings_per_user_per_day` (2; applies with safeguards on, ADR-0047). **Usage:** `lora.trained` plus the
  worker's `gpu.seconds`.
- **Guardrail.** With safeguards on, every dataset image goes through `text.moderate_image` and every caption
  through `text.moderate`; off by default locally (ADR-0047). Rights, consent and scanning for a public release are
  not designed here.
- **Search (ADR-0041 rule):** kind **`lora`**; indexed text = name, trigger word, description and up to five
  captions; `IndexSource`, `ids=`, card and filter, corpus row.

## Evaluation before this is accepted (the Mac-first spike)

On the 64 GB Mac, 15 synthetic or owned images, one family (`flux2-klein`):

1. Install the candidate trainer (mflux first) in its own environment and run one preset end to end. Record: does it
   start, peak memory, seconds per step, total time, whether loss falls, whether the LoRA changes outputs at the
   same seed with the trigger word and not without it.
2. Apply that LoRA through ADR-0051's `lora_chain` on the **distilled** klein 4B at 4 steps and record the effect
   (a LoRA trained on a base model is not assumed to transfer to its distilled sibling).
3. If the Mac cannot do it, record why and the smallest configuration that would work, and mark the product
   "stub only until a CUDA host".

## Consequences

- New: product `wasifyai-lora-ai`, service `services/lora-trainer` (script, Containerfile, stub), provider `trainer` and
  verb `caps.lora.train`, `TRAINER_SERVER_URL`, `TRAINER_MODE`, `LORAS_DIR`, per-capability `timeout_s`, the
  `dataset_image` upload kind, four tables, a wizard UI, and a web area with a side panel entry.
- A new service (a trainer with its own Python environment, several GB). CLAUDE.md says to ask before adding a
  service; this ADR is that ask. It adds no datastore.
- Training blocks image generation on a single-GPU machine; this is a product trade-off, stated in the UI.

## Not in this version

Video or audio LoRAs, several concepts in one LoRA, full fine-tuning, hyper-parameter search, resuming a run after
the machine restarts (checkpoints every N steps are kept; a manual restart from one is possible later), sharing or
publishing LoRAs outside the user's own library, and training on a remote GPU provider.

## Docs to update if accepted

`CLAUDE.md` (Commands, "Ask before"), `docs/configuration.md` (`TRAINER_*`, `LORAS_DIR`, timeouts),
`docs/architecture.md`, `docs/tech-stack.md` (trainer row), `deploy/` (compose service, Helm values, off by
default), `docs/decisions/README.md`.
