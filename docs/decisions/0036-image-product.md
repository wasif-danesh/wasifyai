# ADR-0036: The image product: text to image and image to image

- **Status:** Accepted
- **Superseded in part:** by ADR-0094 (2026-10-29): the image guardrail and the daily limit are removed.
- **Date:** 2026-10-08

## Context

The studio's Image card (ADR-0033) should make images from a description ("text to image") and from a
picture plus an instruction ("image to image"). FLUX.2 klein 4B, already installed for song covers
(ADR-0019), does both with the same model files: ComfyUI's official workflow
`image_flux2_klein_image_edit_4b_distilled` edits a reference image with a prompt. No new model is needed.

## Decision

- **A new product, `wasifyai-image`**, with its own tenancy, usage and quota. Web area: `/image` (create),
  `/image/creations` (My images) and `/image/creations/{id}`; the home card goes live. The "Coming soon"
  page is retired.
- **Two modes.** *Text to image*: a prompt and a size (1:1 1024x1024, 4:3 1152x864, 3:4 864x1152,
  16:9 1344x768, 9:16 768x1344). *Image to image*: **one** uploaded picture (ADR-0035) and an instruction
  such as "make it dusk"; the result keeps the picture's shape (scaled to about one megapixel), so there
  is no size choice. Several references, masks and upscaling are not in the first version.
- **Capabilities, not models.** `image.generate` (text to image) and `image.edit` (image to image), each
  bound in `product.yaml` to a ComfyUI workflow (`flux2-klein-4b` and a new `flux2-klein-4b-edit`, both
  with map files, both **run for real** before they are accepted) and each switchable to another backend
  at `/admin/media` (ADR-0032). The `openai-images` backend gains `/images/edits` for the edit mode;
  Comfy Cloud for edits is unverified like the rest of that backend.
- **Input images reach the backend by the job.** The graph passes `image_key`; the worker reads it from
  storage and hands it to the backend: uploaded to ComfyUI's `temp` area as `wasifyai-{job_id}.png` before the run (it never lands in
  ComfyUI's input folder; the API fills that name into the workflow, so the job id is fixed before the graph
  is built). The worker only reads keys under the user's own `uploads/` prefix, sent as
  multipart to `/images/edits`, or uploaded to Comfy Cloud.
- **My images.** `GET /images`, `GET /images/{id}`, a download route and `DELETE /images/{id}`; each image
  keeps a 480 px JPEG thumbnail for the grid. Deleting removes the row and both files.
- **Graph.** `check_request` (input validation, quota, guardrail) then the job (two nodes, as in
  ADR-0021) and `finalise`: save the image, delete the upload, write the `images` row (migration 0009:
  id, tenant, product, user, mode, prompt, width, height, key, created_at) and the usage event
  `image.created`. Quota: `images_per_user_per_day: 20`.
- **Guardrail (fail closed, like ADR-0022).** The prompt is classified by the `moderator` alias; for
  image to image the uploaded picture is also classified by the `multimodal` alias. Categories:
  `sexual_content`, `minors` (any sexualised or unsafe depiction), `graphic_violence`, `hate`, and
  `real_person_misuse`, plus `disallowed_content` for anything else unsafe. Ordinary edits of ordinary photos, including photos of people, are allowed. What is
  refused is sexual content, anything involving minors in that way, graphic violence, hate symbols, and
  edits that impersonate a real or public person or put someone in a sexual or misleading scene. Refusals
  use fixed texts, never the classifier's. An evaluation set (`evals/`) measures it, and a canary
  (ADR-0025) must pass before an admin can change the `multimodal` or `moderator` model.
- **Not in the first version:** screening the finished image (the local model has no safety filter of its
  own, so a harmless prompt could in rare cases give an unsuitable picture; this is a known gap and the
  next safety step), sharing, a public gallery, and several reference images.

## Consequences

- Needs ADR-0035's upload endpoint first, then the workflows and the product, the web area and the
  guardrail evaluation, in that order.
- An edit probably takes longer than the 25 s a 1024x1024 text-to-image takes (to be measured).
- A second product means a second `product.yaml`, workflows dir, prompts, evals and tests; the platform
  does not change except for uploads and `/images/edits`.
- `multimodal` becomes a protected alias (a change to it runs the image guardrail canary).

## Status of the evidence

- The workflows were run for real on the local ComfyUI, and the whole flow (upload, guardrail, job,
  result, deletion of the upload) was run end to end against the real worker.
- The guardrail evaluation (`products/wasifyai-image/evals/`) uses only harmless synthetic pictures in git.
  Unsafe picture categories can be measured with `--private-dir`, but have **not** been verified; treat
  the picture check as a first line of defence, not proven.
- Not verified: Comfy Cloud and the OpenAI-compatible backend for edits.
