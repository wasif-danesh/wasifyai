# wasifyai-video

Status: **working** ([ADR-0037](../../docs/decisions/0037-video-product.md),
[ADR-0038](../../docs/decisions/0038-prompt-enhancement.md),
[ADR-0039](../../docs/decisions/0039-picture-input.md)).

A signed-in user makes a short clip from a description (**text to video**) or from one uploaded picture
plus a description of what moves (**image to video**), on LTX-Video 2B v0.9.5 through ComfyUI. Clips are 2
or 5 seconds (49 or 121 frames at 24 fps). Text to video is landscape 768x512, portrait 512x768 or square
512x512; image to video keeps the picture's shape.

## Flow

1. Image to video only: the browser uploads the picture as soon as it is chosen, dragged in or pasted
   (`POST /products/wasifyai-video/uploads/images`, ADR-0035, ADR-0039).
2. Optional: the **Enhance** button (`POST /products/wasifyai-video/prompt/enhance`, kinds `text_to_video` and
   `image_to_video`) rewrites the prompt in English; for a picture the model first describes it.
3. `POST /products/wasifyai-video/runs` with `{mode, prompt, seconds, shape}` or
   `{mode: "image", prompt, seconds, image_key}`.
4. Graph: `check_request` (input, one working clip per user, quota, prompt guardrail, picture guardrail) →
   `start_job` (creates the clip's row with status `working`, queues the job) → `await_job` → `finalise`
   (moves the MP4, makes a poster from its first frame, marks the row `done`, deletes the uploaded picture).
5. The user does not have to wait on the page. `GET /videos?status=working` shows what is being made; the
   header badge polls it every 10 seconds while something is working, and a notice says when a clip is ready.
   A row stuck in `working` for 30 minutes is marked `failed`.
6. `GET /videos`, `GET/DELETE /videos/{id}` and `/videos/{id}/download` serve My creations (`/creations`) and
   `/video/creations/{id}`. A clip still being made cannot be deleted.

## Why a second ComfyUI

On Apple silicon the model must run in fp32 (`--fp32-unet`, a process-wide flag). The video capabilities
therefore go to their own ComfyUI at `COMFYUI_VIDEO_BASE_URL`:

```bash
scripts/comfyui-video.sh        # port 8189; see the script for COMFYUI_DIR and COMFYUI_EXTRA_ARGS
```

Both ComfyUIs share the GPU and the worker's GPU id, so jobs still run one at a time. An admin can point
`video.generate` and `video.animate` at another backend at `/admin/media`.

## Measured on a Mac (M-series, 64 GB, fp32, 768x512, 30 steps, text to video)

| Length | Time |
|---|---|
| 2 s | about 3 minutes |
| 5 s | 7.5 minutes |
| 8 s | 15 minutes (not offered: the job limit is 20 minutes) |
| 10 s | 21.6 minutes (not offered) |

Image to video at 2 s took 95-140 s with the real workflow files. The worker's job limit is
`JOB_TIMEOUT_S` (1200 s).

## Models and licences

`ltx-video-2b-v0.9.5.safetensors` (6.3 GB, checkpoints) and `t5xxl_fp16.safetensors` (9.8 GB,
text_encoders). LTX-Video 2B v0.9.5 is Open RAIL-M: commercial use is allowed with use restrictions that
must reach users in the terms of service (not written yet). Later LTX weights use a different licence;
do not swap them in without a new check. Wan 2.2 5B was tried and rejected for now (image to video broke
on Apple silicon; ADR-0037).

## Guardrail

Fail closed, like the image product (ADR-0036): the prompt goes to the `moderator` alias, a picture also to
`multimodal`. Refused: sexual content, anything sexualising or endangering minors, graphic violence, hate,
naming living real people, and making a person in a picture speak, embrace someone or take part in an event.
Gentle ordinary motion (a smile, hair in the wind, a walk) and camera moves are fine. Refusal texts are
fixed. **The finished clip is not screened yet**, and the picture and motion rules have only been checked on
harmless pictures: unsafe-picture accuracy is unmeasured.

## Extend video

A third mode, `extend` (action `video.extend`, screen Video > Extend video): the last 9 frames of one of the
person's clips start a new 49 frame clip, and the graph joins the old clip up to those frames with the whole
new one (ffmpeg, frame exact), so a round adds 40 frames. The result is a new clip beside the original. A clip
of more than 100 frames cannot be extended. The worker reads a job's inputs only from the person's uploads, so
the graph copies the source to `uploads/extend-<id>.mp4` for the job and deletes the copy on every exit.
Measurements and why this variant: `docs/spikes/video-extend-vx0.md`.

## Config

`product.yaml`: capabilities `text.moderate`, `text.moderate_image`, `text.enhance`, `text.describe_image`,
`video.generate` (`ltx-video-2b-t2v`), `video.animate` (`ltx-video-2b-i2v`) and `video.extend`
(`ltx-video-2b-extend`); `uploads.image.max_bytes` (10 MB); quota `videos_per_user_per_day: 5`; `enhance:` kinds.

## Tests

`uv run pytest products/wasifyai-video` (fake provider, a real tiny MP4 made with the bundled ffmpeg; no GPU).
Both workflows were also run for real through the worker's ComfyUI client on ComfyUI 0.39.
