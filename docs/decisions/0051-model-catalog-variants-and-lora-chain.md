# ADR-0051: Model catalog, capability variants and the LoRA chain

- **Status:** Withdrawn (2026-10-12). The TensorArt-style studio will not be built (owner, 2026-10-24); wasifyai does not implement it. Nothing here was built.
- **Later (2026-10-16):** the LoRA chain of decision 2 (`lora_chain` in a map file, `Workflow.fill(loras=...)`) was built for the desktop app in `docs/phase2-stage-c-plan.md`. The model catalog table and capability variants were not.
- **Date:** 2026-10-12

## Context

The owner wants to pick the base model for an image and stack several LoRAs on it (ADR-0052), and to use LoRAs
trained in the studio (ADR-0054). Three things stop that today:

- A capability binding names **one** workflow (`image.generate: flux2-klein-4b`). A different base model means a
  config change and a redeploy, not a choice the user makes per image.
- Workflows are static API-format JSON. A LoRA is one more loader node between the model loader and the sampler, and
  a stack has a variable length. `Workflow.fill` only sets values on existing nodes.
- The platform does not know which LoRA files exist on the ComfyUI host, which base family each one works with, or
  what words trigger it. Applying a LoRA to the wrong family loads without an error and produces noise.

Rule 4 still holds: graph code must not name models, checkpoint files or node IDs.

## Decision

### 1. Capability variants (the base-model choice)

A binding may declare named **variants** and a default:

```yaml
capabilities:
  image.generate:
    provider: comfyui
    default_variant: flux2-klein-4b
    variants:
      flux2-klein-4b: { workflow: flux2-klein-4b, family: flux2-klein, title: "FLUX.2 klein 4B" }
      z-image-turbo:  { workflow: z-image-turbo,  family: z-image,     title: "Z-Image Turbo" }
```

- Graph code passes the variant **id** (`caps.image.generate(variant=..., ...)`), never a file or a node. Without
  `variant` the default is used; a binding without `variants` behaves exactly as before.
- `family` is a free label that LoRAs are matched against (see 3). `title` is what the web shows.
- Config validation (at startup, unchanged in spirit) checks every variant's workflow and map file. An unknown
  variant in a request is a typed error **before** a job is enqueued.
- `/admin/media` bindings (ADR-0032) stay per capability: the backend applies to all variants.
- `GET /products/{product_id}/models` returns the variants (id, title, family, default) so the web builds its picker
  from config, not from a copy.

### 2. The LoRA chain, spliced by the map file

A map file may declare where the model flows, and the SDK inserts loader nodes there. Node IDs stay in the map file.

```yaml
lora_chain:
  loader: LoraLoaderModelOnly   # or LoraLoader (model + clip) for a family whose LoRAs patch the text encoder
  max: 5
  from: { node: "1",  output: 0 }                       # the model before any LoRA
  to:   [ { node: "16", field: model } ]                # inputs that must receive the patched model
```

- `Workflow.fill(values, loras=[(file, weight), ...])` returns the graph with `from -> lora_1 -> ... -> lora_n -> to`.
  Inserted nodes get fresh numeric IDs above the highest existing one. With no LoRAs the graph is unchanged.
- `Workflow.problems()` also checks that `from` and every `to` node exists and that `loader` looks like a loader.
- The job's `inputs` carry `loras: [{file, weight}]` so a backend that ignores the graph can see them. A binding
  whose backend cannot apply LoRAs (`openai-images`, ADR-0032) reports `supports_loras: false`, and a request with
  LoRAs is **refused** by `check_request` rather than silently dropped.
- A variant whose map has no `lora_chain` accepts no LoRAs.

### 3. The model catalog

A platform table, in the same spirit as `creation_index` (ADR-0041): products keep their items, the platform holds
the shared list.

```
model_catalog(id, tenant_id, product_id='platform', owner_user_id NULL, kind, family, name, comfy_file,
              sha256, trigger_words[], default_weight, licence, source, status, preview_key, meta, created_at)
```

- `kind`: `lora` (checkpoints are variants in `product.yaml`, not catalog rows, in this version).
  `source`: `installed` (found on disk) or `trained` (ADR-0054). `status`: `ready`, `missing`, `disabled`.
  `owner_user_id` NULL means shared by the tenant; a trained LoRA is owned by its maker.
- **Rescan** (admin button, and when the worker starts): read the LoRA names ComfyUI lists
  (`GET /object_info/LoraLoaderModelOnly`), add new rows as `disabled`, mark vanished files `missing`, and read the
  `.safetensors` header for hints (family, trigger words). The hint is a **suggestion**: a LoRA is selectable only
  after an admin confirms its `family` at `/admin/catalog`, because the wrong family fails silently.
- **Readiness gate:** a newly written file (a trained LoRA) is `ready` only once ComfyUI lists it, so a run cannot
  name a file the server does not know.
- `licence` is a free text note. **Licences are researched and recorded by the owner**; nothing in this ADR blocks
  or filters on it.
- Reads: `GET /catalog/models?kind=lora&family=...` (the caller's own and shared, `ready` only). The API and the
  worker read `COMFYUI_BASE_URL`; no new address.

## Consequences

- SDK: `CapabilityBinding` gains `variants` and `default_variant` (`extra="forbid"` means a schema change);
  `WorkflowMap` gains `lora_chain`; `Workflow.fill` gains `loras`; a `catalog` module. Worker: none beyond ADR-0053.
- One migration (`model_catalog`), one admin page and routes, one web picker (ADR-0052).
- Variants multiply the real-run acceptance: each variant's workflow (and its `lora_chain`) is run for real before
  it is listed, as for every workflow today.
- Applying a LoRA trained on a base model to a distilled variant of it (klein 4B base vs the 4-step model) is
  **not assumed to work**; it is measured in the spike below.
- Moving checkpoints into the catalog (a user adding a base model from the UI) is deliberately not here.

## Evaluation before this is accepted

1. Run the klein edit and text-to-image graphs on the Mac with one and with two LoRAs spliced by `lora_chain`; the
   output must differ from the no-LoRA output at the same seed and match across two runs.
2. Put a file in the LoRA folder while ComfyUI runs and check it appears in `/object_info` without a restart.
3. Golden-graph unit tests for the splice (0, 1, 3, `max`+1 LoRAs; two `to` targets).

Progress (2026-10-12): ComfyUI 0.39.2 on the Mac exposes `LoraLoaderModelOnly` (`model`, `lora_name`,
`strength_model`) and `LoraLoader` (`model`, `clip`, `lora_name`, `strength_model`, `strength_clip`) with an empty
`lora_name` list, because no LoRA file is installed yet. Steps 1 and 2 need one real LoRA for klein 4B; that is the
next spike (a download, so it waits for the owner's go-ahead).

## Not in this version

Embeddings, ControlNet, VAE choice, per-LoRA scheduling (strength over steps), text-encoder LoRAs for FLUX.2 klein,
downloading LoRAs from a URL, and a per-user default base model.

## Docs to update if accepted

`docs/configuration.md` (variants, `lora_chain`, catalog), `docs/architecture.md` (components), `CLAUDE.md`
(capabilities and ComfyUI section), `docs/decisions/README.md`.
