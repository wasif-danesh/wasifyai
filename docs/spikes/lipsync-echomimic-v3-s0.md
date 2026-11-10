# S0: EchoMimic v3 flash on this Mac, against MuseTalk (2026-11-10)

**Question.** Can EchoMimic v3 replace MuseTalk as the lip sync model (proposal: `lipsync-echomimic-v3.md`)? Does it
run on Apple silicon, how fast is it, how much memory does it take, and how do its clips look next to MuseTalk's?

**Answer.** It runs on this Mac with four small fixes made in our own wrapper, not in their code. Its clips are a
different kind of thing from MuseTalk's: the whole head moves, turns and nods, the eyes blink, and a drawing keeps
its drawn style. But it is about **six times slower** than MuseTalk (36 to 38 s of work per second of video at
512, against 6) and takes about **three times the memory** (37 to 38 GB for the process, against 13). It **misses
the speed bar** the proposal set (under 30 s at 512) by about a quarter, and passes the memory bar (under 40 GB).
Each 3.2-second window starts from the last frame of the one before. The joins don't show, but the face drifts
(smoother, brighter, pinker skin) by the third window. Whether the lips follow the words better than MuseTalk's has
to be judged by watching the side-by-side clips; stills can't show timing.

## Setup

- Code: `antgroup/echomimic_v3` at `7e89489c` (tarball SHA-256 `901986e4…dae7e6`), in
  `/Volumes/AI-1TB/wasify-spikes/echomimic-v3/code`. A Python 3.12 environment of its own (1.2 GB): torch 2.15.0,
  diffusers 0.35.2, transformers 4.57.1, plus accelerate, einops, omegaconf, safetensors, librosa, soundfile,
  pyloudnorm, ftfy, sentencepiece, opencv-python-headless, imageio-ffmpeg, scipy. No TensorFlow, retina-face, mmgp,
  decord, moviepy, flash-attn or xformers.
- Weights (22 GB) in `/Volumes/AI-1TB/wasify-models/echomimic-v3`: `echomimicv3-flash-pro` (3.73 GB), the
  Wan2.1-Fun-V1.1-1.3B-InP folder (transformer 3.13 GB, umt5-xxl encoder 11.36 GB, CLIP 4.77 GB, VAE 0.51 GB,
  tokenizers), `chinese-wav2vec2-base` (0.38 GB and two config files).
- Runner: [`lipsync-em3-s0/run_spike.py`](lipsync-em3-s0/run_spike.py). It uses `infer_flash.py`'s settings: 8
  steps, Flow UniPC, shift 5, text guidance 6, audio guidance 3, TeaCache 0.1 after 5 steps, bf16, 25 fps, 81 frames
  per window. Longer voices: the audio features are made once and sliced, and each window starts from the previous
  window's last frame (one shared frame is dropped).
- MuseTalk: the app's installed engine (`engine/musetalk`, its own venv) through our `lipsync_server/engine.py`,
  with the app's settings (`TORCHDYNAMO_DISABLE=1`, MPS fallback). Runner
  [`lipsync-em3-s0/run_musetalk.py`](lipsync-em3-s0/run_musetalk.py).
- Inputs: the two lip sync pictures already made in the app (a realistic photo of a woman at a café, 1024x924, and a
  drawn portrait, 1024x1024). Voices from our speech models: `speech-kokoro-af_heart.wav` (5.7 s) and
  `dub-source-english.wav` (9.45 s), both in `docs/listening/samples`.
- 64 GB M5 Pro, macOS 27.0.1. Nothing else heavy running.

### The Mac fixes (in `run_spike.py`)

1. **Time embedding.** It is made in float64, which MPS doesn't have. It's now made on the CPU and moved back.
   `tensor.to("cpu", torch.float64)` on an MPS tensor fails ("Undefined type Double"); moving first, then casting,
   works.
2. **Rotary table.** It's complex128, which MPS doesn't support. It's now kept as real (cos, sin) pairs in float32,
   and `rope_apply` is rewritten with real numbers.
3. **Autocast.** Their code asks for CUDA autocast, which is off on a Mac, so float and bf16 meet in a linear layer
   and fail. `torch.cuda.amp.autocast` now gives MPS autocast; a float32 request keeps whatever is around it.
4. **Prompts.** The prompts are encoded once and the embeddings handed in, so the text encoder can be dropped. The
   pipeline reads `prompt_embeds.shape[0]`, so the list is wrapped to have one.

The UniPC sampler worked as it is. The Wan 2.2 spike's noise with uni_pc in ComfyUI did not happen here.

## Results

| Run | Size | Video | Load | Work | Work per second of video | Peak memory |
|---|---|---|---|---|---|---|
| MuseTalk, photo, 10 s voice | 768 long side | 9.44 s | 2.9 s | 57.8 s | **6.1 s** | 13.0 GB (GPU) |
| MuseTalk, drawing, 10 s voice | 768 long side | 9.44 s | 3.4 s | 56.6 s | **6.0 s** | 12.4 GB (GPU) |
| EchoMimic, photo, one window | 528x480 | 3.24 s | 67.8 s | 124.3 s | **38.4 s** | 30.4 GB GPU, 36.9 GB process |
| EchoMimic, photo, one window | 800x720 | 3.24 s | 65.6 s | 425.5 s | **131.3 s** | 38.0 GB process |
| EchoMimic, photo, 10 s voice, 3 windows | 528x480 | 9.32 s | 67.3 s | 337.2 s (109, 118, 110) | **36.2 s** | 36.7 GB process |
| EchoMimic, drawing, 10 s voice, 3 windows | 512x512 | 9.32 s | 66.2 s | 354.2 s (115, 125, 115) | **38.0 s** | 37.3 GB process |
| EchoMimic, photo, 10 s, original picture as identity in every window | 528x480 | 9.32 s | 66.2 s | 337.9 s | 36.3 s | 37.7 GB process |

- "Work" excludes loading. EchoMimic's load (66 to 68 s from the external drive) happens once per server start.
  "GPU" is `torch.mps.driver_allocated_memory()` polled every 0.25 s; "process" is the process's maximum resident
  size. GPU memory stood at 21 to 25 GB after loading. The text encoder was meant to be freed by then, but the number
  suggests it was not; check that when building.
- The time per window is steady, so time grows in a straight line with the voice's length: about 6 minutes per
  10 s, about **36 minutes for a one-minute voice** (MuseTalk: about 6).
- 800x720 is 3.5 times slower than 528x480 for the same clip: not usable.
- Using the original picture as the identity image of every window changed nothing visible (and took the same
  time). The drift comes from starting each window from the last frame.

## What the clips look like

Side by side, MuseTalk left and EchoMimic right, with the voice:
[photo](lipsync-em3-s0/side-by-side-photo.mp4), [drawing](lipsync-em3-s0/side-by-side-drawing.mp4).

- **Photo.** Every 23rd frame in [`sheet-em3-photo-10s.png`](lipsync-em3-s0/sheet-em3-photo-10s.png): the head
  tilts and turns, the eyes blink, the mouth opens with teeth showing, and the face is clearly the same woman. The
  frames around the two joins ([`sheet-em3-photo-10s-seams.png`](lipsync-em3-s0/sheet-em3-photo-10s-seams.png))
  run on with no jump. The drift: faces from frames 5, 120, 200 and 225
  ([`faces-em3-photo-10s.png`](lipsync-em3-s0/faces-em3-photo-10s.png)) get smoother, brighter and pinker in the lips
  window by window, and one eye half closes in some frames of the third window.
- **Drawing.** [`sheet-em3-drawing-10s.png`](lipsync-em3-s0/sheet-em3-drawing-10s.png): the line art and flat colour
  hold, the mouth shapes are drawn in the same style, and the head moves a little. The drift is small: the blush
  gets stronger.
- **MuseTalk** keeps the picture exactly as it is and only redraws the mouth, so it doesn't drift, but the head and
  eyes never move.

## Against the proposal's bar

| Bar | Result |
|---|---|
| Runs on MPS | **Yes**, with the four fixes above |
| Lips follow at least as well as MuseTalk | **For the owner to judge** from the side-by-side clips |
| Peak memory under 40 GB | **Yes**, 37 to 38 GB for the process (too much for a 16 or 32 GB Mac) |
| Under about 30 s of work per second of video at 512 | **No**, 36 to 38 s |

## What I would do next

If the clips are worth the wait, run a short second spike on speed before any build, with each of these measured
on the same 10 s clip:
- skip the extra guidance passes on some steps (`cfg_skip_ratio`), or drop the text guidance;
- TeaCache at 0.2;
- 448 px;
- windows of 113 frames, which means fewer joins and less drift.

Then try colour-matching each window to the first against the drift. If none of these brings it near 20 to 30 s,
keep MuseTalk as the default and offer EchoMimic as a second, slower lip sync model for big Macs (ADR-0066 allows
several). Or keep MuseTalk alone and wait for a CUDA engine worker.

Nothing in the app was changed. The weights and the environment stay on the external drive until the owner decides.
