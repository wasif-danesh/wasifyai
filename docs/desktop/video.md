# Video and Video Builder on the desktop

Part of [the desktop profile](../desktop-profile.md): what is built, how it is wired, what is not done.

## Video (stage V8)

A short clip from words, or from a picture and what should move. The product already existed for the web
(`products/wasifyai-video`, ADR-0037); the desktop serves it with a small, quick model, on the image engine's
ComfyUI, with no new service.

| Piece | What |
|---|---|
| The model | **LTX-Video 2B 0.9.5** (OpenRAIL-M; later LTX weights need a paid licence above USD 10M revenue, so this one stays pinned). Two files, 16.1 GB: the checkpoint (6.3 GB) and the T5-XXL text encoder (9.8 GB), listed in `products/wasifyai-video/models.yaml` with sizes and SHA-256 like every model, fetched from Models after the person has seen them |
| Speed, measured on a 64 GB Apple-silicon Mac (ComfyUI 0.40, half precision) | 2 s clip (49 frames, 768x512, 30 steps) **72 s**; 5 s clip (121 frames) **252 s**; 25 frames at 512x320 and 15 steps 13 s. Through the app's engine, a 2 s clip from text took 86 s including loading the model and a 2 s clip from a picture 58 s. Peak memory about 13 GB (`approx_ram_gb: 14`), which is what the "will it fit" check uses (a video job is judged by the video models, an image job by the image models) |
| Precision | half precision on the Mac's GPU now gives the same picture as the fp32 setting ADR-0037 needed (34 s against 13 s at the small size), so the engine starts ComfyUI with no extra arguments; the `scripts/comfyui-video.sh` second server is for the web only |
| The engine | the product runs as on the web: the graph checks the request, starts a `video.generate` or `video.animate` job, the same in-process worker and ComfyUI sidecar as images run it, a still from the first frame is made with ffmpeg (`imageio-ffmpeg`), the clip is saved, indexed and counted. Clips live in the `videos` table of `wasifyai.db` (`SqliteVideoStore`, created on first use; a clip that stays "working" for 90 minutes is marked failed), and `video_index_source` serves My creations search. One clip at a time per person |
| Routes | `/products/wasifyai-video/runs`, `GET /videos` (`status`, `ids`), `GET/DELETE /videos/{id}`, `/videos/{id}/download`, and `POST /videos/{id}/export` (copies the MP4 to `~/Downloads` or `WASIFYAI_EXPORT_DIR`, never overwrites, as for images) |
| The window | Video > Create (`#/video/create`), Animate an image (`#/video/animate`), Extend video (`#/video/extend`), Your videos (`#/video/library`): `VideoWorkspace`, `ExtendForm` and `VideoLibrary` in `packages/ui`, `createVideosApi` and `videoFlowReducer` in `packages/client`. The page shows the model and whether it is on the computer, the fit, and the same notices as Create (placeholder clips until the image engine is set up, the model missing, tight memory). The result is a player with Save a copy; a clip being made carries on if the person leaves the screen and shows as "Being made" in Your videos |

Found while building this: My creations search failed (an error response) for any hit that was a music track or a
saved voice, because the voice product indexes those two kinds and the search vocabulary did not list them. They are
listed now (`track`, `voice`), and `/creations/search` is tested with each.

**Extend video (2026-10-21, `docs/spikes/video-extend-vx0.md`).** The last 9 frames of one of the person's clips start a new 49 frame clip (`ltx-video-2b-extend`: `LoadVideo`, `GetVideoComponents`, `ImageFromBatch`, `LTXVImgToVideo` with the 9 frames as its image batch), and the graph joins the old clip up to those frames with the whole new one using ffmpeg (`join_clips`, frame exact), so each round adds 40 frames (1.7 s). The result is a new clip (`mode` `extend`) beside the original. The worker reads a job's inputs only from the person's uploads, so the graph puts a temporary copy of the source at `uploads/extend-<id>.mp4` (a new `video` input slot, `PICTURE_SLOTS`) and deletes it on every exit. There is no limit on the length of the clip (owner, 2026-10-21): the part that is added is 5 or 8 seconds (121 or 193 frames, nine of them repeated), and clips are 5 or 8 seconds (ADR-0037, amendment). Action `video.extend` (`video_id`, `prompt`), screen `#/video/extend` (`ExtendForm`: choose a finished clip, the words fill in from its own). The words steer only weakly: the movement of the last second carries on, and the picture softens each round. **Adding a video (2026-10-21):** the screen also takes a video file from the person's computer (`POST /products/wasifyai-video/videos/import`, a multipart file of at most 200 MB): ffmpeg decodes it and makes it H.264 at 24 frames a second, a multiple of 32 on each side with the longer side at most 768, no sound, no tags, at most 30 seconds, then it is a clip of the library with `mode` `import` (searchable, shown as "Added from your computer"). Its last frame is checked like an uploaded picture (ADR-0047), and only its last second goes to the engine (the engine holds every frame it is given in memory). Not built: Extend from a card in Your videos, dropping a file on the screen, the web version of the screen, a longer or shorter extension, audio.

Not built: other video models (LTX's distilled 2B, Wan, CogVideoX:
each needs its licence and a measurement first), a smaller text encoder (the 8-bit T5-XXL is about 5 GB and would cut the
download by a third; its effect on the picture is not measured), sound for clips, clips longer than 5 seconds, and checking the
finished clip (the known gap of images too).

## Video Builder (ADR-0077, stages V1a to V1c and MG1; experimental)

Videos written as an HTML page and drawn frame by frame on this computer, in a locked box. It is always in the
menu, as **Video › Video Builder**; the screen says it is experimental. Details and measurements: `docs/spikes/video-builder-v1.md`.

| Piece | What |
|---|---|
| The component | `<app data>/components/video-builder/`: a pinned Node.js 22.23.1, the pinned Chrome headless shell 152.0.7977.30 and the 130 npm packages of a lock (`hyperframes` 0.8.171, `gsap` 3.15.0, the two font packages, and FFmpeg 4.4 with ffprobe 4.4.1 from `@ffmpeg-installer` and `@ffprobe-installer`). **318 MB** (288 MB before the fonts and FFmpeg) is shown before the click, about 580 MB on disk, 25 s to set up here. `GET /desktop/video-builder`, `POST /install` (the size shown must be sent back), `POST /uninstall`. Apple-silicon Macs only: elsewhere the screen says so |
| The sandbox | `video_builder_sandbox.py`: a launcher the render starts instead of the browser (drops `--no-sandbox` and popups allowed, refuses to start without the filter), a loopback proxy that forwards to the render's own file server only, a guard (wall, stall, memory limits, process-tree kill), a lint before the compiler |
| The product | inside the video product (`wasifyai_video/builder/`): templates, `builder.db` (compositions and render rows) in `<app data>/video-builder/`, project folders, the render manager (one at a time, a fit check first), routes under `/products/wasifyai-video/builder/` |
| What it makes | a **clip of Your videos** (a `videos` row with `mode = "composition"`, the same storage layout), so the library, export, search and delete already work. A project (a composition) is its own kind in the library and in search |
| The templates | **Animated title, quote, bar chart (from CSV lines), lower third, captions**: typed fields, a shape, a length, four preset looks, Inter or Source Serif 4 (shipped, OFL). The words are escaped text in the page, never markup. A lower third and captions are transparent (WebM alpha, ProRes 4444 MOV, or MP4) |
| The prompt box | the screen opens on "What should we make?": a description (and perhaps a CSV file and a shape) is read by the chosen chat model into a template and its fields, with `POST /builder/draft`; nothing is saved, the form opens filled in and is checked by the person. Two small questions to the model (which template, then its fields); words in quotes must come back exactly; CSV rows never pass through the model |
| The exact-text check | before anything is drawn the page is opened in the sandboxed browser and each word on the screen is compared with what was typed (text, visible, drawn, not cut off, inside the safe margin); a failure is said in words and nothing is made. `POST /builder/projects/{id}/check` runs it alone |
| Actions | `motion.make` (write, check and make in one step), `motion.revise`, `motion.write_scenes` and the `motion.*_scene` actions with `motion.undo` (a project of scenes, ADR-0096), `video_builder.create`, `video_builder.lint`, `video_builder.render` (help files in `docs/help/`); `library.*` reaches the `composition` kind. Every change keeps a version; Undo brings the last back (20 kept) |
| Measured here (M5 Pro, 64 GB) | a 5 s 720p title: preview 4.3 s, video 7 to 9 s; 12 s at 1080x1080: 8 s; the render holds about 2.3 GB (`ps` of its process tree); cancel stops it in 1.3 s with nothing left running |

Measured with MG1: each template 7 to 10 s at 720p, tree peak 2.2 to 2.3 GB. Lengths are 3 to 90 seconds (30 by default): a 90 second video draws in 14 to 33 s with the same 2.0 to 2.3 GB.

Not built: the moderation of the words when safeguards are on (ADR-0079 decision 9), a card for projects in a web `/creations` page
(the feature is desktop only), the quarantine check inside the packaged app, the chat path (needs A2), a looping preview clip.
