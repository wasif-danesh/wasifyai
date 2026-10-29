# ADR-0037: The video product: text to video and image to video

- **Status:** Accepted
- **Superseded in part:** by ADR-0094 (2026-10-29): the video guardrail and the daily limit are removed.
- **Date:** 2026-10-08

## Context

The studio's Video card (ADR-0033) is still a "Coming soon" page. The product should make a short clip from a
description ("text to video") or from one picture plus a description of what moves ("image to video"), on a small
open model that runs on the Mac we develop on, and later on any GPU through the same capability names.

We tried the two candidates on the local ComfyUI 0.39 (Apple silicon, 64 GB, MPS) before choosing. Same prompt, a
2-second clip each, and later 5, 8 and 10 seconds for LTX. Times include loading the model. Frames were looked at, not just counted.

| Model | Mode | Setting | Result | Time |
|---|---|---|---|---|
| LTX-Video 2B 0.9.5 | text to video | 768x512, 49 frames, 30 steps | A clear fox walking through snow | 185 s |
| LTX-Video 2B 0.9.5 | image to video | 640x352, 49 frames, 30 steps, image strength 1.0 | Faithful to the picture, little motion | 95-130 s |
| Wan 2.2 TI2V 5B | text to video | 640x352, 17 frames, 12 steps | Works, cartoonish, but only in fp32 | 110 s |
| Wan 2.2 TI2V 5B | image to video | 640x352, 33 frames, 20 steps | **Broken**: frame 1 is the picture, later frames collapse to noise | 205-296 s |

Longer LTX clips, text to video at 768x512 and 30 steps in fp32 on the Mac (coherent at every length; the fox
keeps walking, the framing drifts a little at 8 s):

| Length | Frames at 24 fps | Time |
|---|---|---|
| 2 s | 49 | about 3 min |
| 5 s | 121 | 7.5 min (451 s) |
| 8 s | 193 | 15 min (902 s) |
| 10 s | 241 | 21.6 min (1297 s) |

Cost grows faster than length (attention), and the worker's job limit is 900 s (raised to 1200 s for 5 second clips), so 8 and 10 seconds do not
fit. They are left for faster hardware. Image to video was timed at 2 s only.

Findings that shape the decision:

- **Wan 2.2 5B gives abstract colour blur in fp16 and bf16 on the Mac.** The VAE alone round-trips a picture
  perfectly, so the fault is in the diffusion model on MPS. In fp32 text to video works. Image to video stayed
  broken in fp32, also with a prompt that matched the picture. We did not find out why.
- **LTX 0.9.5 worked in fp32 for both modes.** We did not try it in half precision.
- **LTX image to video needs image strength 1.0 and a prompt that describes the picture.** At the template's 0.15 it
  ignored the photo and drew the prompt instead.
- We pin LTX-Video 2B 0.9.5 (March 2025).

## Decision

- **A new product, `wasifyai-video`**, with its own tenancy, usage and quota, built like `wasifyai-image` (ADR-0036).
  Web area `/video` (create) and `/video/creations/{id}` (one clip). The home card goes live and the "Coming soon"
  page is retired.
- **Model: LTX-Video 2B 0.9.5** (`ltx-video-2b-v0.9.5.safetensors`, 6.3 GB, and the `t5xxl_fp16` text encoder,
  9.8 GB). Wan 2.2 5B is **not** used now: its image to video is broken on our hardware and it needs fp32 anyway.
  It stays a candidate for a CUDA host, where the `video.*` capabilities can be pointed at it without a code change.
- **Two modes, one picture at most.** *Text to video*: a prompt and a shape (landscape 768x512, portrait 512x768,
  square 512x512) and a length of **2 or 5 seconds**. *Image to video*: one uploaded picture (ADR-0035) and a description of what happens; the
  clip keeps the picture's shape, scaled to about 0.3 megapixel and to multiples of 32. A clip is 49
  frames (2 s) or 121 frames (5 s) at 24 fps. 8 and 10 second clips (ADR evidence above) are not offered until the
  hardware or the timeout allows them; several pictures, audio and upscaling are not in the first version.
- **Capabilities, not models.** `video.generate` (text to video) and `video.animate` (image to video), bound in
  `product.yaml` to ComfyUI workflows `ltx-video-2b-t2v` and `ltx-video-2b-i2v` with map files, **both run for
  real** before acceptance. `video.animate` is a new verb next to `generate` and `edit` in the SDK; it takes
  `image_key` exactly as `image.edit` does. Both are switchable per capability at `/admin/media` (ADR-0032). Image
  strength is fixed at 1.0 in the i2v workflow, not a user setting.
- **The video runs on its own ComfyUI.** Our test needed ComfyUI started with `--fp32-unet`, a process-wide flag,
  and fp32 would slow and enlarge the image and music models if they shared it. So `video.generate` and
  `video.animate` go to a second local ComfyUI, set by `COMFYUI_VIDEO_BASE_URL` (default port 8189, started with
  `scripts/comfyui-video.sh`). It is used when the capability has no saved address of its own; an admin can still
  point a capability elsewhere at `/admin/media` (ADR-0032). Both instances share one GPU and one `gpu_id`, so the worker still runs one job at
  a time and the LLM-unload rule still applies. The dedicated instance's start command goes in
  `docs/configuration.md` and the setup script. If half precision is later shown to work for LTX on this hardware,
  the second instance can be dropped.
- **Jobs take minutes.** About 3 minutes for 2 s and 8 minutes for 5 s on the Mac, within the worker's
  `job_timeout_s` (raised from 900 s to 1200 s for margin). Queue position and progress use the existing `job_progress` events (ADR-0021). Quota:
  `videos_per_user_per_day: 5`, counted in clips (to be tuned), and **one working clip per user at a time**, because
  the GPU does one job at a time.
- **The user does not have to wait on the page.** A run is server-side and survives the browser (ADR-0021), but its
  SSE stream only helps a page that is open. So "being made" is a saved state: the `videos` row is created when the
  run starts with `status = working` and is set to `done` or `failed` by the graph (a row stuck in `working` for over
  30 minutes is marked `failed`). The create page follows the SSE stream for the guardrail step, so a refusal shows
  at once, then says the video is being created, how long it takes, and that the user can explore the site. Any
  page shows a small "Making your video..." badge in the header while a clip is working, using a 10 second poll of
  `GET /videos?status=working` that runs only while something is pending. When the clip is done a toast links to it,
  and My creations shows the working clip as a "Making..." card that becomes the clip. **No WebSocket and no global
  stream:** polling is simpler and sturdier than a per-user live feed, and can be replaced behind the same hook.
  Email or browser notifications for a user who has left the site are not in this version (email needs a provider,
  a new dependency, which we ask about first).
- **Graph.** `check_request` (input validation, quota, guardrail) then `start_job` / `await_job` and `finalise`:
  save the MP4 (H.264, no audio), make a 480 px JPEG poster from its first frame (with the bundled ffmpeg the
  downloads already use, ADR-0034), delete the uploaded picture, write the `videos` row (migration 0010:
  id, tenant, product, user, mode, status, prompt, width, height, frames, fps, video_key, poster_key,
  created_at) and the
  usage event `video.created`. A failed job also deletes the upload.
- **Guardrail: the same as the image product (ADR-0036), fail closed.** The prompt goes to the `moderator` alias, a
  picture also to `multimodal`, with the same categories, fixed refusal texts and a canary. Animating a photo of a
  real person is the same ordinary-edit case the user already allowed for images, and it is the riskier one for
  video: **this ADR keeps that rule but flags it for review** once there are real examples. The model makes no sound
  or lip-sync, which limits impersonation. The finished clip is **not screened** (same known gap as images; the
  next safety step for both products, and more pressing for video).
- **My creations.** Clips appear in the unified My creations library at `/creations`, which already lists songs
  and images; it gains a "Videos" filter and a clip card (poster, prompt, time). `GET /videos` (with `status`), `GET/DELETE
  /videos/{id}` and a same-origin download route (the MP4 as an attachment, like songs and images) serve it.
  Deleting removes the row, the video and the poster.
- **Web.** `/video` mirrors `/image`: a "From text" / "From a picture" switch, the 10 MB picture check, a length choice (2 s or 5 s),
  a note that the upload is deleted once the clip is made, and a hint to describe the picture and what should move (image to
  video fights a prompt that contradicts its picture). Result, when the user is still on the page: an inline player, Download, Make another, Open in
  My creations. Sign-in is required for `/video`, like `/music` and `/image`.

## Consequences

- Needs ADR-0035 (done) and ADR-0036's patterns. New pieces, in order: the two workflows and map files and a real
  run of each; the `video.animate` verb in the SDK and the `openai-images`-style backends ignoring it (no hosted
  backend for video yet, so `/admin/media` offers only ComfyUI backends for these capabilities); the product, its
  guardrail evaluation and tests; the web area and the Videos filter; docs.
- About 16 GB of model files for LTX (the Wan files we downloaded for the test, about 18 GB, can be removed).
- A second ComfyUI process on the Mac, with its own memory use (about 8 GB for the fp32 model plus the text
  encoder). The Helm chart passes `COMFYUI_VIDEO_BASE_URL` through (`env.COMFYUI_VIDEO_BASE_URL`); running a second
  ComfyUI pod is not part of this change.
- A `status` column and a stuck-run sweep are new; the image product does not need them because its wait is short.
- Clips are short and the image-to-video motion is gentle. Better motion (higher resolution, more steps, a newer
  model) is a later change behind the same capability names.

## Not verified

- Higher resolutions, longer clips than 5 seconds, and Comfy Cloud or other backends. (Half precision on this hardware was measured on 2026-10-17: see the amendment.)
- The reason Wan 2.2 5B fails on MPS (image to video in fp32, and every mode in half precision).
- The guardrail on unsafe pictures and the clip output, as for images.

## Amendment 2026-10-17: the desktop, a small and quick model

The desktop app serves this product with LTX-Video 2B 0.9.5 (`docs/desktop-profile.md`, "Video (stage V8)"). Measured
on the 64 GB Apple-silicon Mac with ComfyUI 0.40 and the files already used above:

- **Half precision now works.** The fp32 setting (`--fp32-unet`, ADR-0037 context) is no longer needed: the same prompt and seed gave
  the same picture, 2.5 times faster (512x320, 25 frames, 15 steps: 13 s against 34 s). The desktop starts ComfyUI with no
  extra arguments. The earlier finding was for the ComfyUI of that day; the web's second server keeps its flags until
  it is measured again.
- **Times (768x512, 30 steps, half precision):** 49 frames 72 s, 121 frames 252 s. Peak memory about 13 GB.
- The same two workflows run unchanged; clips are kept in SQLite (`SqliteVideoStore`).
- **Not chosen:** the distilled 2B (0.9.8) would need far fewer steps. It stays an option for a later decision.

## Amendment 2026-10-21 (owner): clips of 5 and 8 seconds, no ceiling on Extend

The decision above offers 2 or 5 seconds because 8 and 10 second clips did not fit a 20 minute job limit on the Mac
the measurements were made on. The owner rejected that as a product rule: a computer with a strong GPU must not be held
to what one Mac can do, 2 seconds is too short to judge the model by, and the person can stop a clip that takes too
long. So:

1. **The lengths offered are 5 seconds (121 frames) and 8 seconds (193 frames), 5 by default.** 2 seconds is no longer
   offered. `LENGTHS` in `wasifyai_video/schemas.py` is the one place that lists them; 10 seconds (241 frames) is one line
   when it is wanted. Clips already made at 2 seconds stay in the library.
2. **The limits follow the computer, not the Mac we measured on.** The desktop's job limit is 3600 seconds (it was 1200),
   and a row stuck in "working" is marked failed after 90 minutes (it was 30). The web profile keeps `JOB_TIMEOUT_S`
   (1200 s) for a shared GPU and can raise it by environment. Memory for 8 second clips is not measured on 16 and 32 GB
   Macs; the fit check still decides whether the model runs.
3. **Extend video (docs/spikes/video-extend-vx0.md) has no ceiling on the clip's length** and takes the same two lengths
   for the part it adds (about 5 or 8 seconds). The engine is given only the last second of a long clip.

The "8 and 10 second clips are not offered until the hardware or the timeout allows them" sentence of the decision is
replaced by this amendment.

