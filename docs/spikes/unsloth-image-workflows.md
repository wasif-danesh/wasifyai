# What Unsloth Studio does for Transform, Inpaint, Extend, Upscale and Reference (read 2026-10-21)

Question from the owner: the Images menu items **Transform, Inpaint, Extend, Upscale, Reference** show "Soon" here; in Unsloth's
UI some of the same options are disabled. Is that about the image model, and what is each one? Read from the local checkout
`~/Projects/unsloth` (commit `133a8076d`, 2026-10-13), `studio/frontend/src/features/images/` and
`studio/backend/core/inference/`. **Read for ideas only; nothing is copied** (Studio's frontend is AGPL-3.0, ADR-0062).

## Short answer

**Yes, it depends on the image model that is loaded.** Studio lists seven workflows. Each one names the backend workflow the
loaded model must support (`WORKFLOW_TABS[].requires` in `workflows.ts`). The model's status reports what it can do
(`status.workflows`), and the page publishes that list to the side menu: **a workflow the loaded model cannot do is dimmed. While no
model is loaded, nothing is dimmed**, so a person can set up any of them first (comment in `images-page.tsx`: "null while nothing is
loaded, which leaves every workflow open to set up first"). If the open workflow is not supported by a newly loaded model, the page
jumps to the first supported one.

Our "Soon" badges are a different thing: those screens are **not built**, whatever the model.

## What each workflow is in Studio

| Menu item | Studio's own hint | What the person gives | What happens | The model must support |
|---|---|---|---|---|
| **Create** | "Generate a new image from a prompt" | a prompt | text to image | always open |
| **Edit** | "Change an image with an instruction" | one picture and an instruction ("make the sky orange") | an instruction-following model changes the picture | `edit` |
| **Transform** | "Redraw an image from your prompt" | a picture, a prompt, a **strength** (how much to redraw; 0 keeps the source) | image to image: the picture is noised part way and re-drawn from the prompt | `img2img` |
| **Inpaint** | "Regenerate a painted region" | a picture, a **mask painted in the browser**, a prompt | only the painted area is re-drawn | `inpaint` |
| **Extend** | "Grow the canvas and fill the edges" | a picture, **which sides** (left, right, top, bottom) and **how far** (percent, default 25) | the browser builds a larger canvas and a mask for the new strip, then it runs as inpaint with `workflow: "outpaint"`; the original is kept | `outpaint` |
| **Upscale** | "Enlarge and re-detail an image" | a picture and a **factor** above 1 | "hires fix": the picture is enlarged, then re-drawn at low strength on the image-to-image pipeline | `upscale` |
| **Reference** | "Generate guided by a reference image" | a prompt and one or more **reference pictures** ("the character from the reference exploring a neon city") | the reference pictures are passed to the model as extra image inputs | `reference` |

Notes that matter for us:

- **Upscale is not a dedicated upscaler.** It is image to image at a larger size, so it is available exactly when Transform is
  (`_family_workflows` in `diffusion.py`). Studio's native engine (stable-diffusion.cpp) has a helper for ESRGAN upscaling, but I
  found nothing that calls it, and the native path never reports `upscale`: the helper is not wired to the tab.
- **Extend needs Inpaint, and an inpaint that keeps the picture's size.** FLUX.2 klein has inpaint but not Extend for that reason.
- **Edit and Reference overlap.** Both feed pictures to the model; Edit is for models that only edit (no Create), Reference is for
  models that also create.

## Which models get which (diffusers path, `diffusion_families.py`)

| Model family | Create | Edit | Transform | Inpaint | Extend | Upscale | Reference |
|---|---|---|---|---|---|---|---|
| FLUX.1, Qwen-Image, Z-Image, SDXL | yes | | yes | yes | yes | yes | |
| FLUX.2 klein | yes | | | yes | | | yes |
| Qwen-Image 2.1 | yes | yes | | | | | yes |
| FLUX.1 Kontext, Qwen-Image Edit, Qwen-Image Layered | | yes (only) | | | | | |
| FLUX.2 dev, Krea 2, Lumina 2, HunyuanImage 2.1, HiDream-I1, Ideogram 4 | yes | | | | | | |

The native engine (stable-diffusion.cpp, GGUF files) reports only Create, plus Reference and Edit where the loaded files and the
binary support them. So the same model can have more or fewer workflows depending on **which engine loads it**.

The gating comes from what each model's pipeline offers (an image-to-image pipeline class, an inpaint pipeline class, a reference
or edit flag in the family table). It is a fact about the pipeline, not a product choice.

## What this means for us

We run images on **ComfyUI**, not on Studio's pipelines, so Studio's table does not bind us. In ComfyUI each workflow is a graph, and
what a workflow can do is declared by its **map file** (`products/wasifyai-image/workflows/*.map.yaml`; today
`flux2-klein-4b` for Create and `flux2-klein-4b-edit` for Edit). That is the natural place for the gating: **a menu item is open when
a workflow map for it exists for the model in use**, the same rule Studio applies with `status.workflows`.

State today (`docs/desktop-profile.md`): Create and Edit are built. ADR-0056 decision 10 took Create, Transform and Edit for the first
slice and listed Inpaint, Extend, Upscale and ControlNet for later; Transform is not built yet.

### Proposed definitions (for the owner to confirm)

1. **Transform** — a picture and a prompt; a **Strength** slider (low keeps the picture, high redraws it). The smallest new graph
   (encode the picture, partial denoise). Build first.
2. **Reference** — a prompt and up to a few reference pictures. For FLUX.2 klein this is the same mechanism our Edit already uses
   (reference latents), so it may be a second entry point to one workflow. **Decide whether Reference and Edit are one screen.**
3. **Inpaint** — a picture, a brush to paint the area, a prompt. Needs a **mask painting canvas** (new UI; Studio's is
   `localized-edit-canvas.tsx`, to be designed by us) and a graph that re-draws only the masked area.
4. **Extend** — Inpaint plus a canvas grown on chosen sides by a percent. Built on Inpaint, so it follows it. The canvas building can
   be done in the browser as Studio does.
5. **Upscale** — choose between (a) Studio's way, a low-strength redraw at a larger size, which adds invented detail and can change
   the picture, and (b) a **dedicated upscaler model** (ESRGAN-style, in ComfyUI an upscale-model node), which keeps the picture and is
   faster. Studio did (a). **Decision for the owner.**

### Questions for the owner

1. Gating: **dim an item when the model in use has no workflow for it** (Studio's rule), or always show it and explain when opened?
   Studio leaves everything open when no model is loaded; we could do the same.
2. Order of building: Transform, Reference, Inpaint, Extend, Upscale (cheapest first), or another?
3. Upscale: redraw (a) or dedicated upscaler (b), or both under one name?
4. Reference and Edit: one screen or two?
5. Which models must each item work with for v1 (FLUX.2 klein 4B only, or also 9B and others)?

### Not checked

Whether FLUX.2 klein 4B inpaints well, or transforms well, in ComfyUI on this Mac: the Studio table says nothing about ComfyUI, and no
graph has been tried. Each item above needs a short test before it is promised.
