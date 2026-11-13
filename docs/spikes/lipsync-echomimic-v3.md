# Lip sync: EchoMimic v3 in place of MuseTalk (investigation, 2026-11-10)

Status: **built on 2026-11-10** (the owner chose to replace MuseTalk; ADR-0066 amendment "Lip sync model"; the
app's run is at the end of `lipsync-echomimic-v3-s1.md`). Before that, a proposal. **The spike ran on 2026-11-10: `lipsync-echomimic-v3-s0.md`** (it runs on the Mac with four
fixes in our wrapper, 36 to 38 s of work per second of video at 512 against MuseTalk's 6, 37 to 38 GB), and
**the speed spike `lipsync-echomimic-v3-s1.md`** (448 px with TeaCache 0.2 and colour matching: 16.6 to 18.3 s per
second of video, about three times MuseTalk). The estimates below are from before both. No app code is changed. Adding or swapping a model needs the owner's
yes, and the swap needs an amendment to ADR-0066 (and a line in ADR-0044's "Engine change"), because ADR-0066's
answer 3 says "MuseTalk stays".

## What EchoMimic v3 is

[antgroup/echomimic_v3](https://github.com/antgroup/echomimic_v3), Ant Group, Apache-2.0, AAAI 2026. Last commit
`7e89489c` on 2026-03-18.

- **What it makes.** A picture of a person plus a voice (and a short text prompt) becomes a video in which the whole
  person moves: head, face, eyes and, for a half-body picture, the shoulders and hands. MuseTalk only redraws the
  mouth and the head stays still. Masks and a reference video are optional inputs of the preview version.
- **Base model.** Wan2.1-Fun-V1.1-1.3B-InP (a 1.3-billion-parameter image-to-video model) with audio layers added.
  Two versions:
  - *preview* (2025-08): needs a face box from `retina-face` (TensorFlow 2.15), English `wav2vec2-base-960h`,
    5 steps for a talking head, 15 to 25 for a body; long clips in windows of 113 frames with 8 overlapping.
  - *flash-pro* (2026-01): **8 steps, no face box, up to 768x768, "12 GB of VRAM"**, Chinese `chinese-wav2vec2-base`
    audio encoder. This is the one to use.
- **Settings the project gives.** 25 fps, Flow UniPC sampler, shift 5, text guidance 3 to 6, audio guidance 1.8 to 3
  (higher: better lips, worse picture), TeaCache 0 to 0.1.
- **Length.** The flash script makes **one window of at most 81 frames (3.2 s)** and cuts the voice to it. Longer
  voices need windows joined with overlap (the preview script does this; flash does not), and the README says more
  than 138 frames needs its "long video CFG".

### Files for flash (sizes from Hugging Face, 2026-11-10)

| File | Size |
|---|---|
| `BadToBest/EchoMimicV3` `echomimicv3-flash-pro/diffusion_pytorch_model.safetensors` | 3.73 GB |
| Wan2.1-Fun 1.3B InP transformer (loaded first, then overwritten by flash) | 3.13 GB |
| umt5-xxl text encoder, bf16 (`models_t5_umt5-xxl-enc-bf16.pth`) | 11.36 GB |
| CLIP ViT-H image encoder (`models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth`) | 4.77 GB |
| Wan 2.1 VAE (`Wan2.1_VAE.pth`) | 0.51 GB |
| `chinese-wav2vec2-base` (`pytorch_model.bin`) | 0.38 GB |
| tokenizers | about 0.05 GB |
| **Total** | **about 24 GB** (MuseTalk: 4.2 GB) |

The drive already has `vae/wan_2.1_vae.safetensors` (the ComfyUI form of the same VAE) and no umt5 encoder. The ComfyUI
node below uses `umt5_xxl_fp8_e4m3fn_scaled` (about 6.7 GB) and a 1.26 GB CLIP vision file instead; fp8 is not run
natively on the Mac, so it is upcast.

### Dependencies

`requirements.txt`: torch >= 2.1.2, diffusers >= 0.30.1, transformers >= 4.46.2, accelerate, einops, omegaconf,
safetensors, librosa, moviepy 2.2.1, decord, timm, tomesd, torchdiffeq, torchsde, ftfy, SentencePiece, pyloudnorm,
plus gradio, tensorboard, datasets, albumentations, onnxruntime, **tensorflow 2.15 and retina-face** (preview only),
**mmgp** (low-memory loading for NVIDIA cards).

- **CUDA-only parts are optional.** flash-attn 2 and 3 are tried and the code falls back to PyTorch attention;
  `xfuser`/`pai_fuser` (several GPUs) are inside a try.
- **What the Mac would trip on** (read in `src/wan_transformer3d_audio_2512.py`): `float64` in the rotary and time
  embeddings and `complex128` frequencies (MPS has neither), `torch.cuda.amp.autocast` decorators (warnings only),
  `decord` (no arm64 macOS wheel; only the script imports it, our server would not). The project is tested on
  CentOS and Ubuntu, CUDA >= 12.1, Python 3.10/3.11, A100, 4090D and V100. **No report of it on a Mac was found.**
- Our server would need: torch, torchvision, torchaudio, diffusers, transformers, accelerate, einops, omegaconf,
  safetensors, librosa, soundfile, pyloudnorm, ftfy, sentencepiece, timm, imageio-ffmpeg, fastapi, uvicorn,
  python-multipart. Not TensorFlow, retina-face, mmgp, gradio, decord or moviepy.

### Memory and speed on this Mac (M5 Pro, 64 GB): estimates, not measured

- **Memory.** In bf16 the parts are about 20 GB (text encoder 11.4, CLIP 4.8, transformer 3.7, VAE 0.5). Running the
  text and image encoders once and freeing them leaves about 5 GB plus the working memory of one window. A 768x768
  window of 81 frames is about 48,000 tokens for attention; 512x512 is about 21,000. Expect a peak of **20 to 35 GB**:
  fine on 64 GB, not on a 16 GB Mac (MuseTalk peaks at 11.8 GB).
- **Speed.** One window is 8 steps, each up to three passes (with and without the text and the audio), so about 24
  passes of a 1.3B model. No figures are published. From our own Wan runs (Wan 2.2 14B, about 25 min per 5 s; LTX 2.5
  min) a fair guess is **15 to 60 s of work per second of video**, against MuseTalk's 5 s. Only the spike can say.

### ComfyUI

[smthemex/ComfyUI_EchoMimic](https://github.com/smthemex/ComfyUI_EchoMimic) (third party, about 700 stars, last
push 2026-02-28) runs v3 and v3 flash: "768x768 in 12G VRAM with 8 steps", "768x512 needs 6.5G", with block offload,
and long clips through `partial_video_length`. It ships its own copy of the pipeline (an `echomimic_v3` folder)
rather than ComfyUI's own Wan code, so it has the same Mac problems, plus TensorFlow 2.15 for v3. No Mac mention.
There is no node in ComfyUI itself.

## How MuseTalk is wired today

One seam, built in stage V5 of ADR-0066 (a `sidecar` engine):

| Place | What it holds |
|---|---|
| `products/wasifyai-voice/models.yaml` (`musetalk-v15`) | the descriptor: 11 pinned files (4.2 GB), `engine: sidecar`, `family: musetalk`, `lipsync: {max_voice_s: 300, max_side: 768, fps: 25}`, measured speed 0.2x and 11.8 GB |
| `services/api/src/wasifyai_api/lipsync_server/` | the server in its own environment: `server.py` (`POST /v1/lipsync`, picture and voice in, MP4 out), `engine.py` (MuseTalk wrapped, `face-alignment` for landmarks), `requirements.in` and `musetalk.lock.txt` |
| `services/api/src/wasifyai_api/lipsync_runtime.py` | `MuseTalkInstaller` (pinned source tarball, hashed lock, the app's `uv`), `LipSyncSidecar` (starts the server on loopback, lays the weights out the way MuseTalk reads them: `WEIGHTS`, `TORCH_WEIGHTS`) |
| `components/manifests/<platform>.yaml` (`musetalk:` part) | the source commit, its SHA-256, the lock and its SHA-256; darwin-arm64 only |
| `components/desktop.py` `lipsync_part` | the Settings › Optional parts row "Lip sync engine (MuseTalk)" and its steps |
| `audio_runtime.py` `lipsync()` | checks the task, takes the one memory slot (`slot.hold("lipsync")`), calls the sidecar |
| `desktop.py`, `local_speech.py`, `desktop_lipsync.py` | build the sidecar and serve its setup routes |
| `services/engine-worker/` (`worker.py`, `handlers.py` `_lipsync`, `models_cli.py` `lipsync-engine`) | the same on an engine worker for the web |
| `apps/desktop/src/choices/voice-choices.ts`, `packages/ui/src/models/copy.ts` | the picker's "faces" group and the engine-first install; one plain line for `musetalk-v15` |
| `packages/ui/src/voice/LipSyncWorkspace.tsx`, `packages/client/src/voice.ts` | the screen and its text "It needs MuseTalk's program" |
| `products/wasifyai-voice/.../actions.py` (lip sync), `docs/help/lipsync.make.md` | the action and its help |
| tests | `test_lipsync_runtime.py` with `fake_lipsync_server.py`, `test_voice_*.py`, `test_voice_models.py`, `lipsync.test.tsx`, `voice.test.ts`, `apps/web/lib/choices.test.ts`, `test_admin_components.py`, `scripts/worker_smoke.py`, `scripts/listening_samples.py` |
| elsewhere | `wasifyai_creative/writer.py` (a sung shot is a close-up because "MuseTalk moves only the mouth"), `docs/desktop/voice.md`, `docs/credits.md`, `NOTICE`, `README.md` |

## Plan for the swap

**Where it slots in.** The same seam. EchoMimic v3 is another `sidecar` descriptor with the same server contract
(`POST /v1/lipsync`, picture and voice in, MP4 out), so the graph, the action, the store, the screen, search and the
web worker do not change.

1. **Descriptor.** `echomimic-v3-flash` in `models.yaml`: the six pinned files above (about 24 GB), `family:
   echomimic`, `lipsync: {max_voice_s: <measured>, max_side: 768 or 512, fps: 25}`, measured speed and memory.
   One plain line in `choices/copy.ts`.
2. **Server.** `lipsync_server/engine.py` rewritten for EchoMimic: load the parts, encode the fixed prompt ("A person
   is speaking", or the person's style hint) and the picture once, then free the text and image encoders; run the
   voice in windows of 81 frames with an overlap, each window starting from the end of the last (as Extend video
   does), and stream the frames to ffmpeg as today. The Mac fixes go in our wrapper (rotary tables computed on the
   CPU in float32/complex64), not in their code, as MuseTalk's wrapper does today. A new `requirements.in` and lock.
3. **Installer.** Pin the EchoMimic commit and the new lock in the manifest part; rename `MuseTalkInstaller` and the
   weight layout so they are read from the part, not written for MuseTalk.
4. **Words.** "Lip sync engine" without a model name in the component and the screen; `writer.py`'s close-up rule
   can relax, since the head now moves.
5. **Docs.** ADR-0066 amendment (the lip sync model becomes EchoMimic v3 flash; MuseTalk removed or kept), ADR-0044
   engine-change line, `docs/desktop/voice.md`, `docs/credits.md`, `NOTICE`, help file.

**What can go** once EchoMimic passes: the `musetalk-v15` descriptor and its 4.2 GB, `musetalk.lock.txt`,
`face-alignment` and its two torch-hub weights, the face-parsing weights, the MuseTalk tarball pin. Tests change
names and fixtures, not shape.

**Keep MuseTalk or not.** ADR-0066 lets the picker list several lip sync models. Keeping MuseTalk as the quick
choice (5 s per second, 12 GB, any Mac) beside EchoMimic (the whole person moves, slower, a 64 GB Mac) costs two
environments. The owner asked for a replacement; the spike numbers should settle it.

## Risks

- **It may not run on the Mac at all, or only slowly.** No Mac report exists. float64 and complex128 need work; the
  sampler is Flow UniPC, and our Wan 2.2 spike worked on this Mac only with euler (`video-wan22-w0`).
- **Time.** Probably 3 to 10 times slower than MuseTalk. A one-minute song could take 15 to 60 minutes.
- **Long voices.** Flash makes 3.2 s per window; joining windows can drift or show seams. The 300 s limit of today is
  not realistic; start at 30 s and raise it from measurements.
- **Size.** 24 GB of downloads against 4.2 GB, most of it a text encoder used for one short prompt.
- **Memory.** Too much for a 16 GB Mac; the descriptor's memory floor must say so, and the picker hides it there.
- **Languages.** The flash audio encoder was trained on Chinese; English should work (v1 is English only), other
  languages are unverified.
- **Pictures.** It is a human animation model; drawings, cartoons and animals are not shown in the project.
- **Web.** The engine worker runs the same sidecar, so a Linux CUDA worker needs its own lock (as with MuseTalk).

## Spike to run first (needs the owner's yes: about 24 GB to the drive and an environment of about 3 GB)

1. Clone the pinned commit and make a throwaway environment outside the repo (`/Volumes/AI-1TB/wasify-models` for
   the weights, the scratch folder for the code). No change to the app.
2. Patch only what MPS needs (float64 and complex128 off the GPU), bf16, PyTorch attention.
3. Run `infer_flash.py`'s settings on one real face photo and one real 10 s English voice made by our speech model:
   (a) 512x512, one 81-frame window; (b) 768x768, one window; (c) the full 10 s in windows with overlap; try
   UniPC and, if it fails, euler.
4. Measure for each: load time, seconds of work per second of video, peak memory, and watch the clip for lips,
   eyes, head and seams. Run MuseTalk on the same picture and voice for a side-by-side.
5. Write `docs/spikes/lipsync-echomimic-v3-s0.md` with the numbers and the clips, and a go or no-go.

Go if: it runs on MPS, the lips follow at least as well as MuseTalk, peak memory is under 40 GB and work is under
about 30 s per second of video at 512. Otherwise MuseTalk stays, and EchoMimic waits for a CUDA engine worker.
