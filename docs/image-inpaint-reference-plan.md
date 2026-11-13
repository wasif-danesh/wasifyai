# Plan: Inpaint and Reference in the Images menu (2026-10-21)

**Status (2026-10-21, same day): built.** The owner chose separate screens, **two** reference pictures, klein 4B only, Reference first and
Inpaint with brush and rectangle only. IR0 (`docs/spikes/image-ir0.md`), IR1 and IR2 are done and were run in the real screens against the
real engine. The text below is the plan as it was written; where it says "two to four pictures" the answer was two, and the inpaint
graph is the edit-then-paste-back variant. IR3 (polish) is not started.

Owner's decision, same day: keep **Create, Edit, Inpaint and Reference** in Images and take out Transform, Extend and Upscale (done:
`packages/ui/src/shell/menu.ts`). Inpaint and Reference stay "Soon" until they are built. The owner assumes FLUX.2 klein or
Qwen-Image can do them. What Unsloth does and why its items are model-gated: `docs/spikes/unsloth-image-workflows.md`.

## What the two are (definitions to build to)

- **Reference** — two to four pictures plus a prompt; the result is a **new picture** that uses what the prompt takes from each
  ("the woman from picture 1 wearing the jacket from picture 2, in a street at night"). The order of the pictures matters. The person
  picks the size, as in Create. Edit stays the one-picture, change-this-picture screen; Reference is the several-pictures screen.
- **Inpaint** — one picture, a **mask the person paints**, and a prompt; **only the painted area changes, every pixel outside it stays
  exactly as it was.** The result has the picture's shape.

## What is already true (checked 2026-10-21)

| Fact | Where |
|---|---|
| Edit already works by one reference picture: `LoadImage` → scale to ~1 MP → `VAEEncode` → `ReferenceLatent` on the positive and negative conditioning; result has the picture's shape. klein 4B text to image takes 9 s warm at 1024x1024 on this Mac (4 steps); Edit has not been timed there | `products/wasifyai-image/workflows/flux2-klein-4b-edit.json`, `docs/spikes/unsloth-phase0.md` |
| The app's pinned ComfyUI 0.40.0 has every node needed: `ReferenceLatent`, `SetLatentNoiseMask`, `InpaintModelConditioning`, `DifferentialDiffusion`, `GrowMask`, `FeatherMask`, `ImageCompositeMasked`, `BatchImagesNode`, `TextEncodeQwenImage21` | `~/Library/Application Support/ai.wasifyai.desktop/engine/comfyui/0.40.0` |
| **No official ComfyUI template for klein inpaint.** Official inpaint templates exist only for FLUX.1 Fill and for Qwen-Image with an InstantX ControlNet (extra model). The Qwen-Image 2.1 edit template takes several pictures (it batches two in its example) | `comfyui_workflow_templates_json` in the app's venv |
| On disk, in `~/ComfyUI-Shared/models`: klein 4B (7.8 GB) and its text encoder; **Qwen-Image 2.1** int8 (7.3 GB) with its two text encoders (9.4 and 9.5 GB) and VAE. Qwen is **not** in `models.yaml`, so the app cannot install it yet | `~/ComfyUI-Shared/models` |
| Studio's klein path has Reference and Inpaint (no Transform, no Extend). Its Qwen-Image 2.1 path has Create, Edit and Reference, and **no real inpaint**: its "localized edit" only marks the picture or sends a mask as an extra picture, and says plainly that nothing keeps the pixels outside the region | `diffusion_families.py`, `diffusion_conditioning.py` (read for ideas only, ADR-0062) |

Not checked: Qwen-Image 2.1's licence (no model card on disk), its speed and memory on this Mac, and whether klein 4B distilled keeps
identity with two or three pictures or respects a mask. **That is what stage IR0 finds out.**

## How the product is built today (what each piece changes)

The image graph has two modes, `text` and `image`, and one uploaded picture (`image_key`); the workflow map (`*.map.yaml`) names the
nodes the prompt, seed, steps and picture go into, and has a `lora_chain` that splices LoRA nodes into the graph. The graph checks the
request, moderates the prompt and the picture (ADR-0047), queues one job, waits, and saves. Actions: `image.generate`, `image.edit`.
The screen is `ImageWorkspace` (719 lines; Create and Edit are its two modes).

## Stages

**IR0 — a short spike on the Mac (about a day; no product code).** Build the graphs by hand in ComfyUI against the shared models and
look at the pictures. The results go into `docs/spikes/image-ir0.md` with times and memory. Pass criteria are in the last column.

| Test | Graph | Pass if |
|---|---|---|
| Reference, klein 4B | the Edit graph with a chain of 2, 3 and 4 `ReferenceLatent` pairs (one per picture) | in 5 prompts the subject of picture 1 and the item of picture 2 are both recognisable in most results; time under about 40 s |
| Reference, Qwen-Image 2.1 | the official edit template with 2 and 3 pictures | same; note speed and memory |
| Inpaint A, klein | source encoded + `SetLatentNoiseMask` (and `DifferentialDiffusion` for a soft edge) + the source as `ReferenceLatent`; denoise below 1 | the painted area follows the prompt, the join is not visible |
| Inpaint B, klein | the **Edit** graph with the painted area marked white on the picture and named in the prompt, then **only the masked area pasted back** with `GrowMask` + `FeatherMask` + `ImageCompositeMasked` | same, and outside the mask is byte-identical to the source |
| Inpaint C, Qwen 2.1 | edit template with the mask as the second picture (Studio's "mask" convention), result pasted back the same way | same |

Always paste the result back through `ImageCompositeMasked`: it is what makes "every pixel outside stays exactly as it was" true
whatever the model does, and it removes the VAE colour drift of a full re-encode. Five test pictures: a portrait, an object on a table, a
landscape, a room, a product on white. Choose the inpaint graph that wins; if none does on klein 4B, say so and propose Qwen 2.1.

**IR1 — Reference.** Cheaper (the mechanism is Edit's) so it goes first.
- *Workflow:* `flux2-klein-4b-reference.json` + map. The map gains a `reference_chain` (like `lora_chain`: a per-picture template of
  `LoadImage` → scale → `VAEEncode` → two `ReferenceLatent`, repeated per picture, spliced between the text encode and the guider); the
  result size comes from the person's size choice via `EmptyFlux2LatentImage` and `Flux2Scheduler`, not from the first picture.
- *Graph and API:* a third mode `reference` with `image_keys` (2 to 4); each picture is checked for existence, moderated
  (`judge_picture` for each), and deleted when the job ends; the upload limiter and the quota count every picture; the recipe keeps the
  prompt, size, seed and picture count (not the uploads, as today).
- *Action:* `image.reference` (`image_ids` from the library, 2 to 4, a prompt, a size), a help file `docs/help/image.reference.md`, `ui:
  images.reference`, a row in `docs/contracts/actions.json` (`make contracts`).
- *Screen:* a grid of picture slots with "Add a picture", reorder, remove, the prompt, the size, Make. A hint says to name them
  "picture 1", "picture 2" if IR0 shows the model understands that. Menu: the item loses "Soon" (`apps/desktop/src/menu.ts`,
  `router.ts`, `pages/`).
- *Done when:* a real 3-picture run through the app; moderation refuses a refused picture; each uploaded picture is gone afterwards;
  tests in the graph, the schema, the action, the UI; docs updated.

**IR2 — Inpaint.**
- *Workflow:* the IR0 winner as `flux2-klein-4b-inpaint.json` + map with a `mask` input (a `LoadImageMask` fed the painted PNG, white =
  change). The compositing nodes are part of the graph.
- *Graph and API:* a fourth mode `inpaint` with `image_key` and `mask_key`; the mask is checked (not empty, not the whole picture, same
  shape as the source, 8-bit grey); both uploads are deleted at the end; the prompt and the **source picture** are moderated.
- *Action:* `image.inpaint` (`image_id`, a mask as a small base64 PNG or a stored mask id, a prompt), help file, `ui: images.inpaint`,
  contracts row. An agent can only use it with a mask it was given, so the action says so.
- *Screen:* the new part is a **mask canvas** in `packages/ui` (tokens only, ADR-0081): brush with size, eraser, undo, clear, invert,
  a visible overlay, the picture shown at its own aspect; it exports a mask at the source's pixel size. Pointer painting is hard to use
  by keyboard, so also offer **"Select a rectangle"** with arrow-key nudging. Done-state: the result next to the original with a slider to
  compare is a later nicety, not part of this stage.
- *Done when:* a real run; outside the mask is byte-identical in a test (the compositing is the guarantee); mask checks refuse empty,
  full and mismatched masks; the canvas is tested with pointer and keyboard.

**IR3 — polish, only if asked:** "Edit this result" and "Inpaint this result" from the result card, Reference from a library picture's
menu, a second model (Qwen-Image 2.1) in `models.yaml` once its licence is read, a crop-around-the-mask pass for small areas of a large
picture.

## Models

klein 4B (Apache-2.0, in `models.yaml`, about 24 GB of memory per its entry) is the first target for both. **Qwen-Image 2.1** is the
candidate if klein falls short: it is on this Mac already, has Create, Edit and multi-picture Reference in one model, but it is not in our
catalogue, its licence is unread, and adding it needs pinned sizes and hashes, a licence reading and a download shown to the person
first. Do not offer it until IR0 says it is needed and the owner agrees.

## Risks

- klein 4B is a **distilled 4-step** model; masks and several pictures may drift or leak. IR0 exists to find that out before the
  product is built; the paste-back removes the worst of it for Inpaint, not for Reference.
- Two to four uploads per Reference run and two per Inpaint run: check the upload limit, the per-hour limiter and the temporary
  storage clean-up (the run must delete all of them on every exit path, as Edit does for one).
- Memory on 16 and 32 GB Macs is unmeasured; the fit check refuses what cannot fit (existing `desktop_fit`).
- Painted masks at high resolution are large: send the mask at the picture's size as an 8-bit PNG (small, because it is flat).

## Questions for the owner

1. **Reference and Edit stay separate screens** (Edit: one picture, same shape; Reference: several pictures, a size)? I recommend yes.
2. Up to **how many reference pictures** — 4 (Studio's limit and my proposal) or fewer for v1?
3. Start with **klein 4B only**, and bring in Qwen-Image 2.1 only if IR0 says klein is not enough?
4. Build **Reference first, then Inpaint** (my recommendation: Reference reuses Edit's mechanism; Inpaint needs the new canvas)?
5. Inpaint v1: **brush and rectangle only**, with no "auto-select an object" (that would need a segmentation model)?
