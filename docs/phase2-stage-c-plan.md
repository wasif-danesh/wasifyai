# Phase 2, stage C: edit, remix and LoRAs in the desktop app (plan)

Status: **Approved 2026-10-16** (the owner asked for stage C to be done now), coded the same day. Implements the
LoRA chain of ADR-0051 (decision 2), which was documented but never built, and the third slice of ADR-0061
phase 2. Builds on stages A (real images), B (recipes, library) and the model discovery and hub.

**Goal.** On the Mac, apply one to three LoRAs to an image, make a variation of an image, and take a result into
Edit, all from the window, with the LoRAs kept in the image's recipe so "Make it again" repeats them.

**Not in this stage:** training LoRAs (ADR-0054), a LoRA catalogue with trigger words and previews (ADR-0051
decision 3, the model catalog table), LoRAs for the web product's UI, text-encoder patches (the loader is
model-only), other image families, inpaint and upscale.

## What exists and what changes

| Today | After stage C |
|---|---|
| Edit works as a plain instruction edit; "Make it again" repeats a text image | unchanged, plus **Vary** (same recipe, new seed) and **Edit this result** (the picture becomes Edit's source) |
| The map file has no `lora_chain`; a workflow cannot take a LoRA | both klein maps declare one; `Workflow.fill(values, loras=...)` splices `LoraLoaderModelOnly` nodes between the model and the guider |
| The image graph takes mode, prompt, size, seed | and `loras: [{name, weight}]` (at most 3, weight 0.1 to 2), validated before any model is asked; stored in the recipe |
| Discovery lists LoRAs as "Not used yet" | a LoRA in a ComfyUI-layout folder (`<root>/loras/...`) is `can_use`: one click adds `<root>` as a read-only folder; the app's own `models/loras` folder is scanned too |
| The sidecar reports one "model files missing" sentence | and names a missing LoRA file |

## Design decisions

1. **Model-only loader** (`LoraLoaderModelOnly`). FLUX.2 klein LoRAs patch the diffusion model; the shipped
   workflows do not patch the text encoder. A LoRA that carries text-encoder weights loads and its text part
   is ignored (stated in the picker).
2. **Names, not paths.** A LoRA is its name relative to a `loras` folder (`style/ink.safetensors`). The request
   carries only that name, matched against `^[A-Za-z0-9][A-Za-z0-9 ._()/-]*\.safetensors$` with no `..`, and the
   sidecar must find it in its model folders, so a request cannot make ComfyUI open another path.
3. **Refuse, do not drop.** A workflow without `lora_chain` given LoRAs is an error before a job is queued
   (ADR-0051 decision 2). The graph checks count, weight and name; the provider checks the workflow.
4. **Compatibility is the person's to know.** The file header does not say which model a LoRA was trained for,
   so the picker says "make sure it was trained for FLUX.2 klein 4B"; a wrong family loads and produces noise,
   which the recipe lets the person undo.
5. **Remix is a recipe operation.** Vary re-runs the stored recipe with a new seed; Edit this result fetches the
   image through its signed link and uploads it as the Edit source like any picture the person chose (no new
   route, the edit path's guardrail and deletion rules apply).

## Order of work

| Step | What | Evidence |
|---|---|---|
| C1 | `lora_chain` in the SDK and both maps; provider and image graph take `loras`; recipe keeps them | splice tests (order, ids, none, max, bad node), provider and graph tests |
| C2 | Engine: usable LoRAs list, discovery states, sidecar message | route and discovery tests |
| C3 | Window: LoRA picker, Vary, Edit this result, recipe shows LoRAs | component tests |
| C4 | A real klein image on the Mac with a LoRA, against the same seed without it | numbers below |

## C3 and C4 evidence (2026-10-16, the owner's Mac)

**C3, the window.** The Create screen has a Styles section: each usable LoRA is a checkbox with a strength slider
(0.1 to 2.0, step 0.05, at most 3). A LoRA found on disk but not yet readable shows "Use it", which adds its
folder through the discovery flow. A recipe that names a style that is gone shows "is not available here" with
"Take it out". **Vary** re-runs the stored recipe with a new seed; **Edit this result** fetches the picture
through its link and makes it Edit's source. The recipe list shows Styles. Verified by component tests (39 in
`@wasifyai/ui`, 32 in the desktop app); Vary and Edit this result were not driven in the real window.

**C4, a real image.** ComfyUI 0.40.0 (installed by the component flow in 176 s), Apple GPU, FLUX.2 klein 4B from
`~/ComfyUI-Shared/models`, one LoRA trained for klein 4B (`ena_flux2_klein_4b_full.safetensors`, found in an
Unsloth folder, added through the "Use it" flow), prompt fixed, seed 424242, 1024 x 1024:

| Run | Time | Mean pixel difference from the plain image |
|---|---|---|
| plain (cold start) | 33.3 s | 0 |
| LoRA 1.0 | 11.0 s | 34.69 |
| LoRA 0.5 | 10.3 s | 20.72 |
| plain again | 9.8 s | 0.0 (the same seed gives the same picture) |

LoRA 0.5 against LoRA 1.0 differs by 21.2, so strength changes the result. The picture changes the way a style
LoRA should (the portrait's face, light and clothing change; composition and pose stay). The stored recipe
carried `loras: [{name: ena_flux2_klein_4b_full.safetensors, weight: 1.0}]`. Removing the file produced
`lora_missing` with the message "The style ena_flux2_klein_4b_full.safetensors is not on this computer any more.
Choose another or take it out."

**Findings.**
- This LoRA's keys are ComfyUI-native (`diffusion_model.double_blocks...lora_A/B`), so the key-rename caveat of
  ADR-0059 did not apply. A LoRA saved in another key layout may still need it.
- Discovery listed the same file twice when it sat under two folders both read; harmless, not deduplicated.
- Compatibility cannot be read from the header; a LoRA for another family loads and gives noise (decision 4).
