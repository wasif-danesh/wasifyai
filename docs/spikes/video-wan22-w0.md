# W0: Wan 2.2 TI2V 5B on this Mac (2026-11-04)

**Question.** The Creative Studio test video's moving shots were soft. They were LTX-Video 2B 0.9.5 at the draft setting
(480x288, 15 steps), stretched up to 1080p. Is Wan 2.2 TI2V 5B, whose files are already in `~/ComfyUI-Shared/models`,
a better video model here, and how fast is it?

**Answer.** Wan 2.2 5B is clearly the best of the three on every shot tried: sharp faces that hold, and it does the
camera move the prompt asks for. It is about ten times slower than LTX's final setting: about 25 minutes for a
5-second clip at 832x480, against 2.5 to 3.4 minutes. LTX's final setting is already much better than the draft the
test video used: the draft is what made it look poor.

It runs only with the **euler** sampler on this Mac. With ComfyUI's template sampler (uni_pc), every frame after the
first is noise, on ComfyUI 0.40.0 and 0.3.50, in fp16, bf16 and fp32: a known, open bug on Apple silicon
(ComfyUI issues #16644 and #15793; #16573 blames uni_pc's coefficient maths on MPS).

## Setup

- A throwaway ComfyUI from the app's own install (`engine/comfyui/0.40.0`, its venv with PyTorch 2.11.0), port 8199,
  base folder `~/Projects/wasifyai-spikes/w0/base`, models from `~/ComfyUI-Shared/models`. The demo engine was not touched.
- Wan: ComfyUI's template `video_wan2_2_5B_ti2v` (`wan2.2_ti2v_5B_fp16`, `umt5_xxl_fp8_e4m3fn_scaled`, `wan2.2_vae`,
  shift 8, 20 steps, cfg 5, simple scheduler, 24 fps) with **euler** in place of uni_pc. The files match Hugging Face's
  SHA-256.
- LTX: the app's `ltx-video-2b-i2v` workflow at its final setting (0.25 MP, 30 steps).
- Inputs: shots s1 (walking, camera pushes in), s2 (looking up, camera pans) and s7 (rooftop, pushes in) of the
  2026-11-04 test project, each with its own still and prompt; 121 frames (5 s). Script `w0/scripts/run.py`.
- 64 GB Mac, macOS 27.0.1.

## Results (5-second clips)

| Shot | LTX draft (the test video) | LTX final | Wan 2.2 5B, 832x480, euler |
|---|---|---|---|
| s1 | 480x288, smeared face | 672x384, 204 s, clean, static, small soft face | 26.1 min, push-in to a sharp face |
| s2 | smeared face, wobbly hands | 147 s, clean face and hands | 23.9 min, sharper, livelier; the face drifts from the still near the end |
| s7 | blurred face | 144 s, soft face | 25.4 min, push-in, sharp face |

Peak memory: LTX 10 to 13 GB; Wan up to 27 GB. Wan's decode alone is about 7 minutes of each clip.
At full template size (1280x704) one step of a 2-second clip took about a minute; a 5-second clip would be about an hour.
A side-by-side of all three is `w0/video-models-side-by-side.mp4` (left LTX draft, middle LTX final, right Wan).

What a song costs: 8 animated 5-second shots take about 3.3 hours on Wan, against 20 to 27 minutes on LTX final.

## The broken runs (uni_pc)

fp16 at 1280x704 (28.8 min for 2 s), bf16, fp32, CPU, plain PyTorch rope, text only, and the newer loader and attention
switched off, on 0.40.0; and the same on ComfyUI 0.3.50: all noise after frame 0. Only the sampler mattered.

## What to do

1. Now, no new model: make LTX's final setting the default for what is kept and exported (the draft only as a preview).
2. If wanted: Wan 2.2 5B as a "best quality" choice for a few chosen shots or an overnight run, with euler forced on
   the Mac. This is adding a model (ask first): workflow file, map, catalogue entry and estimates.
