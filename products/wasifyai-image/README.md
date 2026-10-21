# wasifyai-image

Status: **working** ([ADR-0035](../../docs/decisions/0035-image-uploads.md),
[ADR-0036](../../docs/decisions/0036-image-product.md)).

A signed-in user makes an image from a description (**text to image**) or from one uploaded picture plus an
instruction (**image to image**), on FLUX.2 klein 4B through ComfyUI.

## Flow

1. Image to image only: the browser sends the picture to `POST /products/wasifyai-image/uploads/images`
   (raw body). It is re-encoded as a metadata-free PNG of at most 2048 px and stored under the user's prefix.
2. `POST /products/wasifyai-image/runs` with one of four modes:
   - `{mode: "text", prompt, size}`: a picture from words;
   - `{mode: "image", prompt, image_key}`: change a picture (Edit);
   - `{mode: "reference", prompt, size, image_key, image2_key}`: a new picture from two (picture 1 and picture 2), at a size;
   - `{mode: "inpaint", prompt, image_key, mask_key}`: change only a painted area; `mask_key` is an uploaded black and white
     picture of the picture's shape, white where the change goes. Every pixel outside it stays as it was.
   Every upload a mode takes is deleted on every way out (refused, failed, done).
3. Graph: `check_request` (quota, prompt guardrail, picture guardrail) → `generate_image` job → finalise.
   The uploaded picture is deleted once the image is made; abandoned uploads are swept after 24 hours.
4. The image is saved with a thumbnail. `GET/DELETE /images/{id}`, `GET /images`, and a download route serve
   My creations (`/creations`; one image is at `/image/creations/{id}`).

## Guardrail

Fail closed: the prompt goes to the `moderator` alias, the picture to `multimodal`. Refused: sexual content,
anything sexualising or endangering minors, graphic violence, hate, naming living real people, deceptive or
sexual edits of people. Ordinary photo edits and historical figures (before 1900) are fine. Refusal texts are
fixed. The finished image is **not** screened yet.

Measure it with `uv run python products/wasifyai-image/evals/run_guardrail_eval.py` (needs the stack and the
models; `--private-dir` adds unsafe pictures you keep out of git). The checked-in pictures are harmless, so
unsafe-picture accuracy is unmeasured until you supply some.

## Config

`product.yaml`: capabilities `text.moderate`, `text.moderate_image`, `image.generate` (`flux2-klein-4b`),
`image.edit` (`flux2-klein-4b-edit`), `image.reference` (`flux2-klein-4b-reference`), `image.inpaint` (`flux2-klein-4b-inpaint`), `uploads.image.max_bytes` (10 MB), quota `images_per_user_per_day: 20`.
Backends for the two image capabilities can be switched at `/admin/media`.

## Tests

`uv run pytest products/wasifyai-image` (fake provider, no GPU). Workflows were also run for real on ComfyUI.
