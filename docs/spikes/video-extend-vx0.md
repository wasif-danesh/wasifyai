# VX0: Extend video on LTX-Video 2B 0.9.5 (run 2026-10-21)

Question: can a finished clip be continued, so that "Extend video" can be built (the menu item is "Soon" because the video product has no
workflow for it)? Built by hand in ComfyUI on this Mac (M5 Pro, 64 GB; ComfyUI 0.40.0, the version the app pins; the shared LTX-Video
0.9.5 files); no product code. Pictures: `docs/spikes/video-extend-vx0/`; joined clips: `docs/listening/samples/video-extend-fox-*.mp4`.
Scripts (not in the repo): `~/Projects/wasifyai-spikes/vx0/` (`ext.py` builds the graphs, `join.py` joins and measures the seam).

## What was tried

Source clips: the two sample fox clips (49 frames, 24 fps; 640x416 from a picture, 768x512 from text). Each variant makes a new 49-frame
clip that **starts from the end of the source**; the result is the source up to frame 40 followed by the whole new clip (89 frames).
The new clip's first 9 frames reproduce the source's last 9 (`LoadVideo` > `GetVideoComponents` > `ImageFromBatch` picks them in the graph,
so the app only has to hand the stored video file to the engine).

| Variant | How the end of the source is given to the model |
|---|---|
| **A** last frame | one frame into `LTXVImgToVideo`: the existing "Animate an image" graph |
| **B1** last 9 frames, image batch | the 9 frames as the `image` of `LTXVImgToVideo` (it encodes a batch and fills the first latent frames) |
| **B2** last 9 frames, guide | an empty latent, `LTXVAddGuide` at frame 0 with the 9 frames, `LTXVCropGuides` after sampling |

## Results

Seam = mean pixel change from the last kept source frame to the first new frame; "typical" = the same measure between ordinary
neighbouring frames of the source. Overlap drift = how far the new clip's first 9 frames are from the source's last 9 (0 is identical).

| Clip | Variant | Time | Seam | Source typical | Overlap drift | Seen (`sheet-*.jpg`) |
|---|---|---|---|---|---|---|
| from picture | A | 60 s | **39.6** | 6.0 | 46.8 | a visible jump: the fox changes pose and blur, a ghost appears |
| from picture | B1 | 65 s | 5.8 | 6.0 | 3.8 | smooth; the fox carries on turning |
| from picture | B2 | 114 s | 5.9 | 6.0 | 4.6 | the same as B1 |
| from text | A | 126 s | 11.4 | 3.1 | 10.7 | no jump in pose, a small tint shift at the seam |
| from text | B1 | 141 s | 4.5 | 3.1 | 3.4 | smooth; the gait carries on |
| from text | B2 | 149 s | 4.6 | 3.1 | 3.7 | the same as B1 |

(Times include a cold model load on the first run; the machine also had a browser and other sessions running.)

**B1 wins.** It joins as smoothly as B2, is no slower than the existing Animate graph, and needs one node less. A is not good enough: the
model sees a still, so the motion starts over and the first clip's blur or pose does not carry on.

## Chaining and prompt control

Extending the joined clip once more (`sheet-chain.jpg`, 71 s and 107 s): the join stays clean, but the picture keeps getting softer and the
fox keeps walking away from the camera. That blur was already in the source clip (the from-picture sample degrades on its own), so it is
not all the extension's doing, but extending cannot repair it either. **A different prompt barely steers it**: "turns its head and looks
at the camera" gave nearly the same continuation as the unchanged prompt. The motion in the 9 guide frames dominates; the 2B model does
not follow a change of action well. So the screen must not promise that the prompt decides what happens next.

## What this means for building it

1. **Mechanism:** graph `ltx-video-2b-extend` = the i2v graph with the picture replaced by the last 9 frames of an uploaded video
   (`LoadVideo`, `GetVideoComponents`, `ImageFromBatch`); size comes from the source's frames (they are already multiples of 32).
   Plus the join: keep the source's first N-9 frames and append the new clip (re-encode; FFmpeg is bundled with Video Builder).
2. **Frames:** the guide must be 8n+1 frames (9 here). The source's frame count and rate are needed to pick the last 9 (`batch_index` =
   count - 9); read them with FFmpeg before queuing, as the product already does for stored videos.
3. **Cost:** about the same as a normal clip of 2 s (65 to 140 s here); each round adds about 1.6 s of new footage (49 - 9 overlap =
   40 frames). Longer new clips cost more, as in Create.
4. **Cap and wording:** offer it for one or two rounds, say that the picture softens, and describe the prompt as "what to keep doing",
   not "what to do next".
5. **Product rules:** an action `video.extend` (video id, prompt, length), help file, `ui` pointer, `actions.json` row; the result is a
   new video that points at its parent (never overwrites); it is indexed for search like every video; the source frames are temporary
   and removed on every exit path. No new model and no new licence question (the same LTX 0.9.5, ADR-0037).

## Not checked

Memory (the guide adds one 9-frame VAE encode, expected small; peak for a plain clip was about 13 GB); a 5 s extension (only 2 s clips
were run); clips from other sources (a phone video would be a different size and rate); the 8-bit text encoder; whether the two chained
rounds look better with a different seed; audio (the clips have none).
