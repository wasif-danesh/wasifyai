# Several image and video models (ADR-0097)

Owner's list, 2026-11-07. Sizes are from Hugging Face on 2026-11-07, for the files Create loads (int8 or fp8
where offered). "On disk" means the file is already in `~/ComfyUI-Shared/models`.

## The models

| Model | Create files | Download | Gated | AI Toolkit | ComfyUI |
|---|---|---|---|---|---|
| Qwen-Image 2.1 | `qwen_image_2.1_int8_convrot` 6.8 GB, `qwen3.5_9b_…_pe_i2i.int8` 8.8 GB, VAE 0.6 GB | **0, on disk** | no | `qwen_image_2` | 0.40 |
| Z-Image (Turbo for Create, De-Turbo to teach) | `z_image_turbo_bf16` 11 GB, `qwen_3_4b` (on disk) | **0 for Create**; De-Turbo to teach about 12 GB | no | `zimage:deturbo` | 0.40 |
| FLUX.2 klein 4B | in the app | 0 | no | `flux2_klein_4b` | 0.40 |
| FLUX.2 klein 9B | `flux-2-klein-9b` 18.2 GB, Qwen3 8B text encoder about 8.7 GB (fp8) | about 27 GB | yes | `flux2_klein_9b` | 0.40 |
| Ideogram 4 | `ideogram4_int8_convrot` 9.6 GB (+9.6 GB unconditional for negative prompts), `qwen3vl_8b` (int8 on disk) | about 10 to 20 GB | yes | `ideogram4` (experimental) | 0.40 |
| HiDream-O1 | `hidream_o1_image_mxfp8` 8.9 GB (bf16 16.4 GB), one file | about 9 to 16 GB | no | `hidream_o1` | 0.40 |
| FLUX.3 Image Klein | `flux3-image-klein-int8-convrot` 5.8 GB, `qwen3vl_4b_int8` 4.9 GB, FLUX.2 VAE (on disk) | about 11 GB | yes | main only | **0.44** |
| Wan 2.2 14B (text and picture to video) | two 14B parts each, fp8: about 28.6 GB each way, `umt5` (on disk) | about 57 GB (29 GB text to video only) | no | `wan22_14b`, `wan22_14b_i2v` | 0.40 |
| LTX-2.5 | distilled int8 21.5 GB, Gemma 4 12B int8 15.4 GB, decoders 3.4 GB | about 40 GB (+21.5 GB dev to teach) | yes | `ltx2.5` | 0.44 (check) |
| MiniMax-H3 | pruned int8 21 GB, Qwen3-VL 32B int8 27.1 GB, decoders about 6 GB | about 54 GB | likely | `minimax_h3` | 0.40 |

**Total for Create: about 215 GB.** Free on this computer: 160 GB (2026-11-07).

**Where they go: the external drive `AI-1TB`** (owner, 2026-11-07): a UGREEN NVMe enclosure, APFS, on
PCI-Express, 931 GB free, writes at about 2.1 GB/s (measured), so a 20 GB model loads in seconds. It needs
no code: Models › Where models are kept sets "The app's own models folder" to `/Volumes/AI-1TB/wasify-models`
(new downloads and taught adapters go there) and lists the old folder
(`~/Library/Application Support/ai.wasifyai.desktop/models`, 21 GB) and `~/ComfyUI-Shared/models` under "Other
folders the app may read". When the drive is not plugged in, its models show as not downloaded and a download
fails (`/Volumes` cannot be written), so nothing lands on the internal disk by mistake. Files only a trainer
reads from Hugging Face (Z-Image De-Turbo, LTX-2.5 dev) go to the Hugging Face cache on the internal disk
today; stage MV3 points that cache at the drive too.

## Stages

| Stage | What | Downloads |
|---|---|---|
| MV0 | ComfyUI 0.40.0 to 0.44.2 and AI Toolkit to a commit with FLUX.3; klein 4B makes a picture and trains again | ComfyUI and AI Toolkit only |
| MV1 | Several models per product (config, engine, picker, the `model` field, menu per model) with Qwen-Image 2.1 and Z-Image Turbo, measured | none |
| MV2 | FLUX.3 Klein, Ideogram 4, HiDream-O1, klein 9B in Images, measured | about 57 to 74 GB |
| MV3 | A picture recipe for each image model, a short measured run each | De-Turbo, training files |
| MV4 | Wan 2.2 14B, LTX-2.5, MiniMax-H3 in Video, measured | about 150 GB |
| MV5 | Video recipes on AI Toolkit for those three | LTX-2.5 dev |
| MV6 | The web: Admin › Media picks the model; workers fetch it | on the workers |

## Owner decisions (2026-11-07)

1. ADR-0097 accepted as written.
2. Disk: the `AI-1TB` drive. All downloads approved, fetched when a stage needs them.
3. The Hugging Face token the `hf` tool saved is used. The owner accepts the terms of
   `black-forest-labs/flux-3-image-klein-comfy`, `flux-3-image-klein-base`, `FLUX.2-klein-9B`,
   `ideogram-ai/ideogram-4-fp8` and `Lightricks/LTX-2.5` on Hugging Face (their files answered 403 on 2026-11-07).
4. Measuring runs are short, 10 to 30 steps; likeness is not judged.
5. MV0 to MV6 are built without stopping; the commit lines come at the end.

## Progress (2026-11-07)

**MV0 done.** ComfyUI 0.44.2: klein 4B text to image 23 s, edit 35 s, inpaint 23 s, reference 25 s; LTX-Video 2B text,
picture and extend clips and ACE-Step music all work. AI Toolkit `beb94824` installs fresh in 114 s through the app's
setup, and a 6-step klein run through the app's trainer (the launcher still needed) took 452 s, peak 40.8 GB.

**MV1 done.** `product.yaml` `models:` (platform: `ModelChoice`, `ProductConfig.model()`, `MediaCapabilities` picks a
model's bindings from the request's `model`); the image graph refuses a model not offered ("Please choose one of the
image models.") or one that cannot do the mode ("This model cannot change a picture.") before any work, and keeps
`model` in the recipe; the four image actions take an optional `model`; `GET /desktop/models` gives each entry `can`;
the window sends the chosen model, hides the Images items it cannot do and blocks a screen opened anyway. Measured on
ComfyUI 0.44.2, 1024 px, the first run of each including its load, the owner's M5 Pro (64 GB):

| Workflow | Steps | Seconds |
|---|---|---|
| `qwen-image-2.1` | 20 | 137 |
| `qwen-image-2.1-edit` | 20 | 134 |
| `qwen-image-2.1-reference` | 20 | 227 |
| `z-image-turbo` | 8 | 52 (38 loaded) |

**MV2 in progress.** HiDream-O1 (bf16, `Comfy-Org/HiDream-O1-Image@7b75f4cd`, on `AI-1TB`) is offered for Create.
In bf16 on Apple's graphics chip every run drew the subject's outline in broken stripes (either sampler, 20 or 40 steps,
CFG 5 or 2, with or without seam smoothing); ComfyUI's `--force-fp32` fixed it, and so does a `ModelComputeDtype`
fp32 node in the workflow, which keeps the other models as they are: 20 steps at 1024 px in 192 s with the load
(170 s under `--force-fp32`). The template's seam smoothing with the `median` blend aborts ComfyUI on Apple's graphics
chip (`torch.median`), so the workflow uses `average`. Memory is set to 40 GB (fp32 doubles its 16 GB) until measured.

Ideogram 4 (int8, `Comfy-Org/Ideogram-4`, open, both halves on `AI-1TB`) has a workflow (`ideogram-4`) that runs: 20
steps at 1024 px in 308 to 341 s, reading Qwen-Image 2.1's Qwen3-VL 8B int8 text encoder instead of a second copy.
**It is not offered yet:** given a plain sentence, or a JSON with only `high_level_description`, it draws a grey card
saying "Image blocked by safety filter"; given the template's full structured caption (`compositional_deconstruction`
with elements, boxes and text) it makes the picture well. Ideogram's own service and ComfyUI's template write that
caption with a prompt writer first. To offer it: a model gets an optional prompt writer in `product.yaml` (a prompt
file in `prompts/`, run through `text.enhance` before the job, like the existing "Improve my description"), so the
graph still names no model. Until then it is out of `models.yaml` and `product.yaml`; its catalogue lines are the pins
in the workflow's map notes and below.

| File | Pin |
|---|---|
| `ideogram4_int8_convrot.safetensors` | `Comfy-Org/Ideogram-4@2aa6c75c`, 9583465712 bytes, sha256 `a9164002…a163d` |
| `ideogram4_unconditional_int8_convrot.safetensors` | same commit, 9583465712 bytes, sha256 `cd03ed94…6c23d` | **Blocked:** FLUX.3 Image Klein
(`black-forest-labs/flux-3-image-klein-comfy`) and the klein 9B model file (`black-forest-labs/FLUX.2-klein-9B`) still
answer 403: the owner accepts their terms on Hugging Face, then they are added the same way.

**MV3 findings (not built).** AI Toolkit loads each model differently, so a recipe is more than a line in
`picture_bases.py`; the training setup must pin and fetch each model's Hub files (it runs offline):

| Model | AI Toolkit `arch` | What it reads besides our files |
|---|---|---|
| Qwen-Image 2.1 | `qwen_image_2` | `Qwen/Qwen-Image-2.1` (text encoder folder, processor, VAE config) |
| Z-Image | `zimage` (De-Turbo: `ostris/Z-Image-De-Turbo`) | `Tongyi-MAI/Z-Image-Turbo` (text encoder, VAE) |
| Ideogram 4 | `ideogram4` (experimental) | `ideogram-ai/ideogram-4-fp8` (**gated, 403**), `Qwen/Qwen3-VL-8B-Instruct` |
| HiDream-O1 | `hidream_o1` | `HiDream-ai/HiDream-O1-Image` processor (small) |
| FLUX.3 Image Klein | `flux3` | gated (403) |

The change: `PictureBase` gains the Hub repos and files it reads (pinned like the klein text encoder's small files in
`training_setup.py`), `find_base` and the setup become per recipe, and `training_config` writes `extras_name_or_path`
and leaves out `te_name_or_path`/`vae_path` for a recipe without them. HiDream-O1 is the first to do (one file here, a
small processor), then Z-Image De-Turbo.

**MV4 in progress.** Built: `product.yaml` `models:` for Video with per-model `settings` (`frames_per_second`,
`frame_step`, `frame_offset`, `draft`, `looks`; `MediaCapabilities.setting`), so a clip's frames are the fewest the
model can make at its rate (LTX-Video 24 a second, 8n + 1: 121 for 5 s; Wan 2.2 16, 4n + 1: 81; MiniMax-H3 24, 17n + 5:
124); the video graph refuses a model not offered, a mode it cannot do, a draft or looks it does not take; the three
video actions take an optional `model`; the window sends the chosen model and hides the Video items it cannot do.
Offered: LTX-Video 2B (the default; Create, Animate, Extend), Wan 2.2 14B (Create), MiniMax-H3 (Create, with sound).

- **Wan 2.2 14B** (`Comfy-Org/Wan-2.2`, renamed from `Wan_2.2_ComfyUI_Repackaged`): workflows `wan2.2-14b-t2v` and
  `wan2.2-14b-i2v` from the templates (the Lightx2v 4-step LoRAs, CFG 1, euler). The fp8 files do not load on a Mac
  (torch has no float8 on Apple's graphics chip; the fp8 text encoder is fine, it runs on the processor). The owner
  chose the fp16 text to video files (57 GB, 2026-11-07). **Measured:** a 5.1 s clip at 832x480 (81 frames), 4 steps
  at about 400 s each, 1829 s (30 min) in all; the picture is good. Offered for Create only; picture to video waits
  for its fp16 files (another 57 GB, not asked for).
- **MiniMax-H3** (`Comfy-Org/MiniMax-H3`, pruned int8, the Qwen3-VL 32B int8 text encoder since the template's nvfp4
  needs NVIDIA, the 8-step turbo LoRA): workflow `minimax-h3-t2v`. **Measured** on the owner's M5 Pro: a 5.2 s clip
  at 768x512 with sound (124 frames), 8 steps at about 162 s each, 1445 s (24 min) in all; the picture is good. The
  int8 video VAE does not run on a Mac (torch has no `_int_mm` on Apple's graphics chip), so the fp16 one (5.2 GB) is
  used.
  Picture to video (the template's `first_frame`) is not written yet.
- **LTX-2.5** (`Lightricks/LTX-2.5`) answers 403 for files: the owner accepts its terms.
