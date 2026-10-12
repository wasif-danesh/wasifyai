# ADR-0052: Image studio: base model, LoRAs, stored parameters and Remix

- **Status:** Proposed
- **Date:** 2026-10-12
- **Depends on:** ADR-0051. **Extends:** ADR-0036 (it does not supersede it).

## Context

`wd-image-ai` (ADR-0036) makes an image from a prompt and a size, or from one picture and an instruction, on one
base model. It stores the prompt and the size, not how the image was made. The owner wants to choose the base model,
add several LoRAs, and **remix** an earlier creation: start again from its settings, or from the picture itself.
Tensor.art's creation page shows the same set of facts for each image (models used, prompt, sampler, steps, seed,
size) with a Remix button; that is the model for the detail page here.

## Decision

- **Run input gains** `base_model` (a variant id, default from `product.yaml`), `loras` (`[{id, weight}]` with ids
  from the catalog, ADR-0051), `seed` (optional) and `parent_id` (optional, the creation being remixed). Everything
  else (mode, prompt, size, `image_key`) is unchanged, so existing clients keep working.
- **`check_request` validates** before any GPU work: the variant exists; at most `settings.max_loras` LoRAs (5);
  each LoRA is `ready`, visible to the caller and of the **same family** as the variant; each weight is inside
  `settings.weight_range` (-1.0 to 2.0); the bound backend `supports_loras`; `parent_id` belongs to the caller.
  Violations are plain `invalid_request` refusals, not stack traces.
- **What is stored.** `images.params` (jsonb) and `images.parent_id` (uuid, null) in one migration:

  ```json
  { "base_model": "flux2-klein-4b", "family": "flux2-klein", "seed": 913377215, "size": "square", "steps": 4,
    "loras": [ { "catalog_id": "...", "file": "x.safetensors", "sha256": "...", "weight": 0.8 } ],
    "prompt_original": "...", "enhanced": true }
  ```

  The file name and hash are copied, not only the catalog id: files are renamed and replaced, and Remix must say a
  LoRA is no longer available instead of silently making something else. A random seed is chosen by the graph and
  stored (it already is chosen server-side). Old rows have `params = null` and Remix falls back to prompt and size.
- **Two remixes, both built from what exists.**
  1. *Remix settings:* the web opens `/image?remix={id}`, loads prompt, base model, LoRAs, weights and size from
     `GET /images/{id}` (which now returns `params`), and offers "keep the seed / new seed". The new creation's
     `parent_id` points back.
  2. *Remix the picture:* `POST /products/wd-image-ai/uploads/from-image/{image_id}` copies the caller's own creation
     into their `uploads/` prefix (same re-encode, metadata strip, size cap and 24 hour sweep as ADR-0035; counts
     against the hourly upload limit) and returns an `upload_id`; the form switches to *Image to image* with the
     original prompt as the starting instruction. No new model path: it is the edit workflow, now with LoRAs.
- **Prompt enhancement is not changed** (ADR-0038: same route, same kinds, same English output). After Enhance the web
  checks that every trigger word of the selected LoRAs is still present and appends any that is missing, so the
  rule is deterministic and testable and needs no new API field.
- **The picker** lists `ready`, family-matched LoRAs. Changing the base model asks before dropping LoRAs of another
  family. A distilled variant hides controls it ignores (klein: no negative prompt, CFG fixed). The last base model
  chosen is remembered in the browser only.
- **Quota, safeguards and usage are unchanged.** `images_per_user_per_day` and the guardrail still sit behind
  `caps.safeguards_on()` (ADR-0047). `image.created` usage events gain `base_model` and `lora_count` in `meta`.
- **Search is unchanged.** The indexed text stays the prompt (ADR-0041); LoRA names are not added, because changing
  the text format re-embeds everything (`SEARCH_INDEX_MODEL`).

## Consequences

- One migration; `ImageRecord`, `ImageSummary` and the store gain `params` and `parent_id`; one new upload route;
  the `/image` form and the detail page gain controls and a params panel. A unit test for each validation rule;
  graph tests use the fake provider (no GPU).
- Remix of a deleted LoRA or base model is a visible warning, not an error.
- Results on the Mac can differ slightly for the same seed (MPS is not bit-reproducible); the page says "same
  settings", not "identical picture". The spike measures how close.
- A request with LoRAs is slower: each LoRA adds a load and a patch step (measured in the spike).

## Evaluation before this is accepted

Re-run one stored creation with its own params and the same seed twice on the Mac and record how similar the
results are; run the same prompt with 0, 1 and 3 LoRAs and record the time.

## Not in this version

Several images per request, ControlNet, upscaling or hires fix, per-user default models, a negative prompt for
models that have none, a public gallery or sharing, and searching by LoRA name.

## Docs to update if accepted

`products/wd-image-ai/README.md`, `docs/configuration.md` (the `settings` keys), `docs/decisions/README.md`.
