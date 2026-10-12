# ADR-0053: AI Tools: a manifest-driven product, and Change Clothes

- **Status:** Withdrawn (2026-10-12). The TensorArt-style studio is a separate product, `wasifyai-art`, in its own repository (`wasifyai-art`); wasifyai does not implement it. Nothing here was built.
- **Date:** 2026-10-12
- **Depends on:** ADR-0051 (variants). Uses ADR-0035, ADR-0039 (pictures), ADR-0038 (Enhance), ADR-0040/0041 (library).

## Context

The owner wants an **AI Tools** section: small single-purpose tools that run a ComfyUI workflow on the user's
pictures. The first is **Change Clothes**: two pictures (a person, a garment) and a sentence. More tools will follow,
so the cost of the second tool must be a file, not a feature. Two platform limits get in the way:

- A job carries **one** user picture, named `image` (`image_key`; ADR-0035, ADR-0036). Change Clothes needs two.
- Each capability binds one workflow; a tool needs its own workflow without a new Python verb per tool.

## Decision

- **A new product, `wasifyai-tools-ai`,** web area `/tools`, side panel entry "AI Tools" with one view per tool. A tool is
  a folder, not code:

  ```
  products/wasifyai-tools-ai/tools/change-clothes/tool.yaml   # manifest (below)
  products/wasifyai-tools-ai/workflows/change-clothes-*.json + .map.yaml
  products/wasifyai-tools-ai/prompts/change_clothes.md        # fixed instruction template
  ```

  ```yaml
  id: change-clothes
  title: Change Clothes
  blurb: Put the clothing from one picture onto the person in another.
  variant: change-clothes            # the variant of image.compose that runs it (ADR-0051)
  inputs:
    person:  { type: image, label: Person,   hint: One person, face visible }
    garment: { type: image, label: Clothing, hint: The garment, worn or laid flat }
    notes:   { type: text,  label: Notes (optional), max_chars: 300, enhance: change_clothes }
  quota: { per_user_per_day: 20 }
  ```

  One generic graph runs any manifest; one generic web form renders it. Manifests are validated at startup against
  the capability variants and the workflow map (each image input must map to a `LoadImage` node), so a bad tool
  fails the deploy, not a user's request.
- **Several pictures per job (platform change).** `image_key` becomes an alias of `image_keys: {"image": key}`; a
  job may carry `image_keys: {name: key}`. The worker reads each key under the user's own `uploads/` prefix (same
  checks as today), uploads each as `wasifyai-{job_id}-{name}.png` to ComfyUI's temp area, and replaces that placeholder
  in the graph. The map file lists one input per name. `input_image_name(job_id)` keeps its old result for `image`.
  A new verb `caps.image.compose(variant=..., image_keys=..., prompt=..., seed=...)` (family `image`, like `edit`).
- **Inputs are deleted.** Both pictures are removed as soon as they are not needed: when the request is refused,
  when the job fails, and when the result is saved (the rule of ADR-0036, applied to every input). Nothing keeps
  a photo of a person. **Remix of a tool result therefore reuses the notes and the seed, and asks for the pictures
  again.**
- **Result.** Table `tool_results` (id, tenant, product, user, thread, run, tool_id, notes, seed, width, height,
  image_key, thumb_key, params, created_at); routes `GET /results`, `/results/{id}`, download, delete, `ids=` filter
  (ADR-0023, ADR-0041). In My creations it is the kind **`tool`**, shown as an image card with the tool's title.
- **Graph:** `check_request` (both pictures belong to the caller, notes length, quota) -> when safeguards are on,
  `text.moderate` on the notes and `text.moderate_image` on **each** picture -> `compose` job -> `finalise` (store,
  thumbnail, row, delete the uploads, index, usage `tool.completed`). Same two-node job pattern as ADR-0021.
- **Search (ADR-0041 rule):** indexed text = the tool's title and the notes; `caps.index_creation`,
  `deps.unindex`, an `IndexSource` for finished results, `ids=` on the list route, a card and a filter, and a row
  in `evals/search/corpus.yaml`.
- **Enhance:** the notes use kind `change_clothes` (ADR-0038: English output, undo, limits). The picture-describing
  path is not used.
- **Safety, stated plainly.** Replacing clothes is the usual route to non-consensual "undress" edits. With
  safeguards off (the owner's local setting, ADR-0047) that is the owner's responsibility. The tool ships with its
  own `moderation.md` that treats removing clothing as `sexual_content`, and `real_person_misuse` for edits that
  impersonate or sexualise a real person, so that turning safeguards on later needs no rewrite. **Output screening
  does not exist anywhere in the platform yet (ADR-0036's known gap)**; it is out of scope here and is the first
  thing needed before this tool is exposed to anyone else.

## The workflow is decided by a spike, not here

Candidates for "two pictures and a sentence, no mask":

| Candidate | For | Against |
|---|---|---|
| FLUX.2 klein 4B, second reference (extend the edit graph's `ReferenceLatent` pair) | Installed, same files as ADR-0036, runs on this Mac | Quality of a 4B distilled model on garment transfer unknown |
| Qwen Image 2.1 edit, pictures addressed as `<image1>`, `<image2>` in the prompt (ComfyUI's official template, up to 16 pictures) | Installed (int8); built for multi-reference edits | Heavy; speed on Apple silicon unknown |
| CatVTON / IDM-VTON custom nodes (mask and pose based) | Most faithful transfer | Custom nodes to pin and review, DensePose setup, CUDA-leaning |

**Acceptance (before this ADR is accepted):** 20 person/garment pairs (synthetic or properly licensed images; no
real person's photo kept in git) through candidates 1 and 2, scored by the owner on garment fidelity (colour,
pattern, shape), identity kept, pose and background kept, and seconds per image on the Mac. The chosen workflow
is then run for real through the stack. The results table goes in this ADR.

### First spike results (2026-10-12, development Mac, 64 GB, ComfyUI 0.39.2, one pair, n = 1)

One synthetic person (klein text to image, 768x1024) and one synthetic garment (a red quilted puffer jacket), same
seed. Both candidates ran **unmodified on the Mac**: no custom nodes, no patches, only files already installed.

| | Klein 4B, two `ReferenceLatent` pairs | Qwen Image 2.1 int8, `TextEncodeQwenImage21` with two pictures |
|---|---|---|
| Graph | The ADR-0036 edit graph plus one `LoadImage` -> scale -> `VAEEncode` -> `ReferenceLatent` on the positive and negative conditioning | The bundled template's loaders, `TextEncodeQwenImage21` (positive, negative and latent outputs) and `KSampler`, 8 steps, cfg 1 |
| Time | **45 s** and 48 s (4 steps, about 1 MP, model warm; first load 34 s for a 4-step text to image) | **168 s** (8 steps, cold start; about 7 s per step warm) |
| Identity, pose, jeans, background | Kept | Kept |
| Garment colour | **Drifted**: bright red became brick red | **Kept** (true red) |
| Garment shape and detail | Quilting, collar and pockets carried over well | Smoother quilting, slightly different collar |
| Prompt sensitivity | "Dress the person from image 1 in the garment shown in image 2" closed the jacket and hid the T-shirt; describing the result ("wearing the jacket over her grey T-shirt") gave an open jacket with the T-shirt visible | One prompt tried (`<image1>`, `<image2>`), open jacket over the T-shirt |

What this does and does not show: both work end to end, so **no custom nodes or CUDA are needed to start**, and the
manifest, named-pictures and `compose` design stands. It is one pair of clean, studio-style images made by the same
model, so it says nothing about worn garments, busy backgrounds, side views or people in motion; the 20-pair
acceptance above is still required before choosing. Leaning: **klein as the default** (4 times faster, same files as
the rest of the studio) with **Qwen Image 2.1 as a per-tool variant** when colour fidelity matters, which the variant
mechanism (ADR-0051) supports without code. Artifacts: `~/gen-studio/docs/spikes/change-clothes/`.

## Consequences

- Platform: named pictures in `JobRequest.inputs`, the worker, `ComfyUIProvider` and `input_image_name`; one
  capability verb; the upload route already accepts any product that lists `uploads.image`.
- Web: `PictureInput` is used once per slot (two instances on one form), `/tools` list and `/tools/[toolId]`, a
  library card, a side panel entry in `lib/products.ts` (`id: "tools"`, `library: "tools"`).
- New: migration `tool_results`, product package (entry point `wasifyai.products`), `evals/` with the spike's pairs.
- Two pictures about double the edit's reference tokens, so time per result is higher than ADR-0036's edit.
- Tools are all single-image-output in this version.

## Not in this version

Masks or painting on the picture, several garments, garment auto-description by the multimodal model, batch runs,
video try-on, user-written tools, sharing, and custom nodes (any tool that needs one gets its own ADR and a pinned,
reviewed node).

## Docs to update if accepted

`docs/configuration.md` (named pictures, `compose`), `docs/architecture.md`, `apps/web/README.md`,
`products/wasifyai-tools-ai/README.md` (new), `docs/decisions/README.md`.
