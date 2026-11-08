# ADR-0097: Images and Video offer several models, each taught with AI Toolkit

- **Status:** Accepted (owner, 2026-11-07: as written; all downloads to the `AI-1TB` drive approved, using the
  saved Hugging Face token; short measuring runs of 10 to 30 steps; build MV0 to MV6 without stopping)
- **Date:** 2026-11-07
- **Asked by:** the owner, 2026-11-07: the top image and video models AI Toolkit supports, in Create and in
  training. The list was chosen with the owner the same day (below).
- **Amends:** ADR-0059 (one image workflow per capability), ADR-0086 (the picker's Images and Video groups
  list more than one model), ADR-0073 amendment of 2026-11-07 (more picture recipes; video recipes on AI
  Toolkit).
- **Plan:** `docs/image-video-models-plan.md`, stages MV0 to MV6.

## Context

Each media product is bound to one model: `products/wasifyai-image/product.yaml` names one workflow per
capability (FLUX.2 klein 4B), and Video names LTX-Video 2B 0.9.5. Training follows the same rule: a picture
recipe exists only for klein 4B, and video is taught by a separate PyTorch trainer for LTX-Video 2B that AI
Toolkit does not support. The owner wants these models, from AI Toolkit's own list:

| Images | Videos |
|---|---|
| Qwen-Image 2.1, FLUX.2 klein 9B, FLUX.2 klein 4B, Z-Image, Ideogram 4, HiDream-O1, FLUX.3 Image Klein | Wan 2.2 14B, LTX-2.5, MiniMax-H3 |

An adapter is only useful if Create can load the model it was taught on, so every model needs both a ComfyUI
workflow set and a training recipe.

## Decision

1. **A product holds several models.** `product.yaml` gains `models:`, one entry per model, each with its
   own capability bindings (workflows and defaults); the top-level `capabilities` keep the text bindings. A
   model binds only what it can do (FLUX.3 Klein may have no inpaint workflow), and a menu item a chosen model
   cannot do is not shown (as the Images menu already follows the loaded model). Graphs still ask for
   capabilities (rule 4): the model id picks which binding answers.
2. **The person chooses with the button they already have,** "Select image model" / "Select video model"
   (ADR-0086). The choice is kept per person; each request carries an optional `model` (the product's first
   model when absent, so existing callers and actions keep working). This changes the public API shape: one
   optional field on the image and video requests and actions.
3. **One trainer.** Each image model gets a recipe in `picture_bases.py`; video models get recipes of the same
   kind and are taught by AI Toolkit too. The LTX-Video 2B trainer stays only for LTX-Video 2B.
4. **Pins move.** ComfyUI 0.40.0 to 0.44.2 (FLUX.3 needs it) and AI Toolkit `f7a1fb9a` to a commit with
   FLUX.3 Image Klein. The klein text-encoder launcher (`training_aitk_run.py`) is still needed on main.
5. **Big models stay listed on small computers.** A model whose measured need is above the computer's memory
   says "Needs a bigger computer" (the existing fit check); the web's CUDA workers run it.
6. **Downloads follow the picker's rule:** nothing is fetched before the person has seen the files and sizes
   and pressed the button. Five of the models are gated on Hugging Face, so a download needs the person's own
   Hugging Face token, kept like the other keys (`secrets.py`), and their acceptance of each model's terms on
   Hugging Face.

## Consequences

- About 215 GB to download for Create (table in the plan), more than this computer's free 160 GB: they are
  kept on the external drive `AI-1TB` (931 GB), set in Models › Where models are kept, with no code change.
- Every model needs a measured run here (or "not measured" written beside it) before its numbers are used.
- The web's Admin › Media gains a model choice per product.

## Not decided here

- Which models are taught on this Mac and which only on NVIDIA: decided per model from its measured run.

## Built (2026-11-08)

MV0 to MV6 are built; `docs/image-video-models-plan.md` has the measured numbers.

- Images offer klein 4B, klein 9B, FLUX.3 Image Klein, Qwen-Image 2.1, Z-Image Turbo, HiDream-O1 and Ideogram 4;
  Video offers LTX-Video 2B, LTX-2.5, Wan 2.2 14B and MiniMax-H3, each binding only what it can do.
- A model's `settings` may name a prompt writer (Ideogram 4 needs a structured caption).
- Every image model has a training recipe, and LTX-2.5, Wan 2.2 14B and MiniMax-H3 have video recipes, all taught
  by AI Toolkit. A recipe pins the Hub files it reads; the person fetches them from the Train screen first. Z-Image
  and FLUX.3 Image Klein were taught here through the app; the others are marked not measured, and Wan 2.2,
  MiniMax-H3 and Ideogram 4 say they need an NVIDIA card.
- On the web the admin picks each product's model in Admin › Media; the ComfyUI host fetches its files with
  `python -m wasifyai_api.comfy_models`.
- On the desktop the window also keeps the image and video model chosen in the bar in the engine
  (`PUT /desktop/models/chosen/{product_id}`, the same `media.model.<product>` setting). A run that names no model
  (Creative's stills and clips, the assistant, another app over MCP) is made by it when it can do the job, as with an
  admin's choice on the web, and its recipe names it. Before this, Creative always used klein 4B and LTX-Video 2B
  (found in a real-window run, 2026-11-08).
- Not built: taught looks for the new video models (a look does not record the model it was taught on).
