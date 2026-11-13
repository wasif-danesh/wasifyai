# TV0: can the app's video model be taught on this Mac? (measured 2026-10-26)

Date: 2026-10-26. Machine: MacBook Pro M5 Pro, 64 GB, macOS (Darwin 27.0.0). Plan: ADR-0073, "Amendment: video training", decision 7
(the spike TV0). Scratch folder (outside the repo): `~/Projects/wasifyai-spikes/tv0/` (scripts, logs, clips, LoRAs, pictures). The scripts and the main pictures are kept here in `docs/spikes/video-training-tv0/`.

**Read this first.** The question was whether the video model the app already uses, **LTX-Video 2B 0.9.5**, can be taught a look or a motion on
this computer: with what, how fast, in how much memory, whether it learns, and whether the result works in the app's own video engine.
The data is **synthetic** (clips made by `ffmpeg`, no personal files): it proves the path works and what it costs. It does **not** show how
well a real subject (a person, a pet, a product) is learnt: that is not measured.

## Answers in short

| # | Question | Answer (measured unless marked) |
|---|---|---|
| 1 | Is there a trainer that runs on a Mac? | **Yes, with a small script of our own on PyTorch (MPS), `diffusers` and `peft`.** The ready-made trainers are for NVIDIA (below). The ready-made MLX trainer exists but teaches LTX-2.3, which the app cannot use (licence, ADR-0037) |
| 2 | Can LTX-Video 2B 0.9.5 be taught? | **Yes.** Its own file (`ltx-video-2b-v0.9.5.safetensors`, the one the app downloads) loads into `diffusers` with `from_single_file`; a LoRA (rank 16 to 32 on every attention projection, 14.7 to 29.4 million trainable numbers) trains in bf16 on the Mac's graphics chip |
| 3 | How fast? | **0.50 s a step** at 384x256, 25 frames (384 tokens); **6.9 s a step** at 768x512, 49 frames (2 s; 2,688 tokens) with gradient checkpointing, **4.6 s without it** |
| 4 | How much memory? | **7.4 GB** (384x256) and **9.8 GB** (768x512, 49 frames, checkpointing) on the graphics chip; **49.6 GB without checkpointing at 768x512**, so checkpointing is not optional. Preparing the data holds the text encoder for a while (10.8 GB, 15 GB for the process) |
| 5 | Does it learn? | **Yes at 384x256, not yet shown at 768x512 in 300 steps.** On the fixed-noise loss (4 clips, 4 noise levels) the loss fell **30 percent in 700 steps** on the gradient clips (0.174 to 0.122) and **61 percent in 700 steps** on a harder rainbow-fractal look (0.400 to 0.156); generating with the LoRA draws the taught look (a glowing magenta bloom over navy; saturated cyan and magenta bands) where the base draws a flat navy frame or a photo-like blob. At **768x512, 49 frames, 300 steps (38 minutes) the loss fell only 14 percent** (0.128 to 0.110) and the pictures show the look only loosely: a real run needs more steps than that |
| 6 | Does it keep the magic word? | **Partly: the look binds to the word but at the app's guidance (3) it needs the LoRA turned up to about 2.** At guidance 1 and strength 1 the look is clear; at guidance 3 and strength 1 it is faint |
| 7 | Does the result work in the app's own video engine? | **Yes, after a rename of the file's keys.** The app's ComfyUI 0.40.0, run as the app runs it for video (`--fp32-unet`), drew the same look from the renamed file. The file as the trainer saves it is **silently ignored** by ComfyUI ("lora key not loaded"), so the rename is a required step, as it is for pictures |
| 8 | Licences | `diffusers`, `peft`, `transformers` Apache-2.0, PyTorch BSD-3-Clause; the LTX-Video 2B 0.9.5 weights are OpenRAIL-M (commercial use allowed, use restrictions pass on to what is made); the T5-XXL encoder is Apache-2.0 |

**Go or no-go: go for a first real build (TV1) on this path, with the conditions at the end.** Section 8 adds the real-subject test the owner asked for
(the fictional character Ena, from the owner's own picture set): the identity is **partly** learnt from stills.

## 1. What exists (researched first, 2026-10-26)

| Candidate | What it is | Mac? | Verdict |
|---|---|---|---|
| Lightricks `LTX-Video-Trainer` (older) | The official trainer for the LTXV line; its troubleshooting guide estimates 16 to 40 GB of VRAM for the 2B model | NVIDIA only (CUDA) | not usable as is |
| Lightricks `LTX-2` `packages/ltx-trainer` | The official trainer for LTX-2.x; README: an NVIDIA GPU with 80 GB or more, or 32 GB with the low-memory config | NVIDIA only | wrong model family and wrong hardware |
| `huggingface/finetrainers` (Apache-2.0, pushed 2026-09-23) | PyTorch trainers for several video models; LTX-Video LoRA listed at about 5 GB of VRAM | CUDA-oriented; no MPS mention in its README or file list | its LTX model code (`finetrainers/models/ltx_video/base_specification.py`) was **read and re-used as the reference for the training step**; the framework itself was not run |
| `dgrauet/ltx-2-mlx` (MIT, pushed 2026-10-25) with `ltx-trainer-mlx` 0.18.0 | A pure-MLX port of **LTX-2.3** and its trainer (alpha): LoRA by flow matching, text to video and video to video; a changelog entry reports a real 2,000-step run on an M5 Pro 64 GB (74 clips, 192x192, rank 32) with gradient checkpointing | **Yes, MLX** | **the only ready-made Mac trainer found**, but for LTX-2.3: a 20 GB-class model under the LTX-2 Community Licence (free below USD 10M annual revenue, paid above). ADR-0037 pins LTX-Video 2B 0.9.5 *because* later LTX versions have that licence. **Not run**: it needs about 20 GB of weights plus a 12B text encoder (not asked for), and the app does not use that model, so its numbers would not transfer. Nothing in ADR-0037 forbids running it as a measurement |
| `Blaizzy/mlx-video` (MIT) | MLX inference for LTX-2, Wan2.1 and Wan2.2 with LoRA loading; the tagline says "finetuning" but its README has no training command | Yes (inference) | no trainer |
| `kohya-ss/musubi-tuner` | LoRA training for HunyuanVideo, Wan2.1 and 2.2, FLUX.1 Kontext; a fork's README claims Linux, macOS and Windows | claimed | not tried: it does not train the app's model |

The last research step was a read of the app's own files: the video product pins LTX-Video 2B 0.9.5 (`products/wasifyai-video/models.yaml`), the
app's ComfyUI needs it in fp32 on Apple silicon (`scripts/comfyui-video.sh`), and both the model file and the T5 encoder were already on this Mac
(`~/ComfyUI-Shared/models/`), so **nothing large was downloaded** for this spike. The only fetches were pip packages
(`diffusers` 0.42.0, `peft` 0.21.2, `accelerate`, `sentencepiece` into a scratch environment with the torch 2.14.1 the decision trainer already uses)
and the repository's small tokenizer and config files (under 1 MB).

## 2. What was built to measure (scratch scripts)

- `preprocess.py`: encodes each caption with T5-XXL (the app's `t5xxl_fp16.safetensors`, loaded into `T5EncoderModel` with the key names as they are),
  and each clip with the LTX video encoder (`AutoencoderKLLTXVideo.from_single_file`, the 0.9.5 one with timestep conditioning), keeping the
  latents normalised as the pipeline expects. Done once; the text encoder and the video encoder are not needed again.
- `train.py`: the transformer (1.92 billion numbers, bf16) with a LoRA from `peft` on `to_q`, `to_k`, `to_v`, `to_out.0` of both attention blocks of all 28
  layers; flow-matching loss as `finetrainers` writes it (noise level from a logit-normal draw, `x = (1-s) latent + s noise`, target `noise - latent`,
  timestep `s x 1000`, rope scale for 25 frames a second); AdamW; a steady **validation loss on fixed noise** (four clips, four noise levels), because the
  per-step loss is dominated by the random noise level and says little.
- `gen.py`: the `diffusers` `LTXPipeline` built from the same single file with the LoRA loaded, given the pre-computed text embeddings.
- `comfy_run.py`: the app's own text-to-video workflow (`ltx-video-2b-t2v.json`) with one `LoraLoaderModelOnly` node added, sent to the app's own ComfyUI
  0.40.0 (started on a spare port with its output, input and user folders in the scratch folder).
- **Data:** 16 clips of 25 frames at 384x256 made by `ffmpeg`'s `gradients` source (bands, blooms, rings and spirals in teal and magenta on navy),
  all captioned "zqx7 style, ..." with the thing drawn; 8 clips of 49 frames at 768x512 the same way. The magic word is `zqx7`.

## 3. Measurements

| Run | Result |
|---|---|
| Preparing 16 clips, 384x256, 25 frames | text encoder loaded in 1.6 to 9 s (disk cache), 20 captions in 1.4 s; video encoder **0.7 s a clip**; 18 s in all, 15 GB peak for the process (the text encoder) |
| Preparing 8 clips, 768x512, 49 frames | video encoder **4.1 s a clip**, 43 s in all |
| Training, 384x256, 25 frames, rank 16, 400 steps, lr 1e-4 | **307 s** (0.76 s a step while other work ran), **7.7 GB** peak, a 59 MB file. The look is faint |
| Training, 384x256, 25 frames, **rank 32, 800 steps, lr 5e-4** | **403 s (0.50 s a step)**, **7.4 GB**; held loss 0.174, 0.153, 0.149, 0.144, 0.141, 0.133, 0.128, 0.122 (700 steps), 0.127 (800). A 117 MB file. **The look is learnt** |
| Training, same, lr 1e-3, 600 steps | 305 s; held loss 0.137; pictures washed out and the shapes missing: **too high a rate** |
| Training, 768x512, 49 frames, 12 steps | **no checkpointing: 4.6 s a step, 49.6 GB**; **with checkpointing: 6.9 s a step, 9.8 GB** |
| Training, 768x512, 49 frames, rank 32, 300 steps, lr 5e-4, checkpointing, 8 clips | **2,300 s (38 minutes; 7.7 s a step)**, 9.8 GB; held loss 0.128, 0.116 (100), 0.113 (200), 0.110 (300). Generating 768x512, 49 frames with it took **25 s** (guidance 1; the LoRA does not change the time) and **49 s** at guidance 3: the look appears only loosely (a teal wedge on navy at guidance 3 and strength 2, a swirl at guidance 1): **not enough steps** |
| Training, 384x256, 25 frames, rank 32, **800 steps on 12 rainbow-fractal clips** | **396 s (0.49 s a step)**, 7.4 GB; held loss 0.400, 0.319, 0.288, 0.264, 0.228, 0.187, 0.170, 0.156 (700), 0.176 (800). At guidance 3 the picture turns to saturated cyan and magenta bands (the share of teal and magenta pixels 0.74 against 0.10 for the base) but **the fractal's fine structure is not reproduced**; the sailboat prompt with the word is unchanged |
| Generating (diffusers, bf16, 384x256, 25 frames, 30 steps) | **6 s** a clip with or without the LoRA |
| Generating (the app's ComfyUI, fp32, 384x256, 25 frames, 30 steps) | 13 s at guidance 1, 21 s at guidance 3 (the first included loading the model: 29 s) |

## 4. What the pictures showed

- **Base model, prompt "zqx7 style, a slow spiral of teal and magenta light on navy":** a flat navy frame with a dim blob. **With the LoRA (rank 32, 800 steps):
  at guidance 1 and strength 1 a glowing magenta bloom drifts across a dark purple-navy frame**, which is the taught look; the same through ComfyUI.
  At the app's guidance of 3 the bloom is at the frame's edge at strength 2 and absent at strength 1: the LoRA is applied to both halves of the guided
  step, so the guidance pushes toward the prompt and away from the look. The product will need a strength control (a default near 1.5 to 2) or a note.
- **Other subjects with the word ("zqx7 style, a sailboat at sunset"):** the picture shifts a little toward pink and the boat loses detail, but it is still a boat at
  a sunset. A look this synthetic does not carry over to other subjects, which is what a real style LoRA must be tested for with real data.
- **Too strong a rate** (1e-3) pictures lose their detail and wash out: the descriptor of a run needs a rate in a measured range.
- **A harder look** (rainbow fractals, 12 clips, 800 steps): the palette and the saturated banded look arrive (guidance 3), the fractal detail does not; the
  base model, asked for a "psychedelic rainbow fractal", draws a photo-like pink bloom, so the LoRA moves the result a long way toward the data.
- **Realistic size, 300 steps:** a loose version of the look only. At 7.7 s a step, 800 steps (what the small runs needed) would take **about 100 minutes**;
  the first product build must show the cost before it starts, and the number of steps needed at a real size is the main unknown.

Pictures (`docs/spikes/video-training-tv0/`, four frames of each clip, rows top to bottom):
`rank32-800-steps.jpg` (base, LoRA, base and LoRA on the sailboat prompt, LoRA on the plain prompt), `strength-and-guidance.jpg` (LoRA at strength 1 and 2,
guidance 1 and 3), `use-in-the-apps-comfyui.jpg` (base; the renamed LoRA at guidance 1; at strength 2 and guidance 3; the unrenamed file, which is ignored),
`rainbow-fractal-look.jpg` (base; LoRA at guidance 1 and 3; the sailboat prompt) and `768x512-300-steps.jpg` (base; LoRA at guidance 1; at strength 2 and guidance 3).
The scripts are `preprocess.py`, `train.py`, `gen.py` and `comfy_run.py` (they name this Mac's folders).

## 5. What was found that the build must handle

1. **The file's keys.** `peft` saves `base_model.model.transformer_blocks...`; `diffusers` wants `transformer.transformer_blocks...lora_A.weight`; the app's
   ComfyUI wants **`transformer_blocks.N.attn1.to_q.lora_A.weight`** (no prefix: its LTXV key map has no `transformer.` form). A file with the diffusers
   prefix loads without error and **does nothing** (ComfyUI prints "lora key not loaded" for every tensor). The rename is a pure key change of
   448 tensors (the same kind of step as `comfy_lora.py` for pictures).
2. **The video workflow has no LoRA node.** `ltx-video-2b-t2v.json` and `-i2v.json` need a `LoraLoaderModelOnly` between the checkpoint loader and the sampler,
   with the strength as an input of the workflow's map file, and the engine's `loras` folder holding the published file.
3. **Half precision.** Training and generating in **bf16 work on the Mac with `diffusers`** here. The app's ComfyUI path needs fp32 for the diffusion model
   (its own earlier finding, ADR-0037); the LoRA trained in bf16 worked there, applied in fp32.
4. **Checkpointing is required** at a real size (49.6 GB without it at 768x512 and 49 frames); it costs about 50 percent in time.
5. **The per-step loss is useless** as a progress or "did it learn" number; a fixed-noise validation loss over a few clips is steady and fell by 30 percent here.
6. **The text encoder dominates the memory of preparing the data** (10.8 GB on the chip); training itself needs 7 to 10 GB. They never run at once.

## 6. Not known (nothing here measured it)

- **A real subject, beyond one test.** Section 8 tried one (Ena, 36 pictures); likeness was partial. How many clips or pictures, of what size, a real person
  or an animal, and how the likeness compares with the picture LoRA are still open. ADR-0073 decision 7 item 4 (a real person's face asks whose it is) still applies.
- **Image to video** (the app's second mode): not tried. Training on first-frame conditioning is described in `finetrainers` (10 percent of steps);
  the LoRA's effect in the app's image-to-video workflow is untested.
- **Captions from frames** by the person's vision model (decision 7 item 2) and the clip checks (too short, too dark, a copy).
- **16 and 32 GB Macs.** 10 GB on the chip suggests 32 GB works and 16 GB is tight (the text encoder step is the limit and could be done in 8 bits or in chunks):
  not measured.
- **Wan 2.2 TI2V 5B** (Apache-2.0, in this Mac's Hugging Face cache from an earlier spike) as a second video base: not tried.
- **Steps at a real size.** 300 steps at 768x512 (38 minutes) were not enough on 8 clips; 800 steps were enough at 384x256. Whether training at a small size and
  generating at a large one works (usual practice: mixed sizes), and the steps and time for a real subject, are not measured. A 3,000-step run is not measured.

## 7. Recommendation

**Go (TV1) on PyTorch, `diffusers` and `peft`, in a component of its own like the decision and writing trainers:** a hashed lock (torch, diffusers,
transformers, peft, accelerate, sentencepiece), the model files the video product already pins (the checkpoint, the T5 encoder), the tokenizer and config files pinned by
SHA-256, an adapter that runs the steps above as a separate process and reports progress as JSON lines, and the key rename on keeping the file.
Conditions: (a) the first real data test (a real subject, about 20 clips, trained at a small size and checked at the large one) before the screen is promised; (b) the strength control and the LoRA node in the
video workflows; (c) a descriptor with the measured memory (10 GB with checkpointing) and seconds per step; (d) the card's words change from
"needs an NVIDIA graphics card" to what is true on each machine.

## 8. Real-subject test: Ena (2026-10-26, owner: "use my files, preferably a picture of Ena ... I approve")

Data: the 36 approved pictures of the fictional character Ena from `~/Projects/character-lora/data/characters/ena/training/flux/` (read only; 1320x1191) with their
own captions (trigger `enav7qx`, "a woman with long dark hair ..., wearing ..."). **Pictures were taught as single-frame samples** (the usual way to teach a
subject to a video model): a picture is encoded by the video encoder as one latent frame, the LoRA is the same as before (rank 32, every attention projection).
No clips were made or used. The pictures of Ena are not copied into the repository; the results are in the session's scratchpad folder.

| Run | Result |
|---|---|
| A: pictures at **640x576**, 1500 steps, lr 3e-4 | **753 s (0.50 s a step), 7.2 GB**; held loss 1.20, 0.55 (250), 0.53, 0.52, 0.50, 0.49, 0.48 (1500) |
| B: pictures at **768x704**, 3000 steps, lr 2e-4 | **2,180 s (36 minutes; 0.73 s a step), 9.6 GB**; held loss 1.10, 0.53 (500), 0.51, 0.50, 0.48, 0.47, 0.45 (3000) |
| Preparing the 36 pictures | 11.5 s (640x576), 14.7 s (768x704) |
| Generating 640x576, 49 frames (2 s), 30 steps, diffusers bf16 | 47 to 55 s a clip, with or without the LoRA |
| The same through **the app's own ComfyUI as the desktop starts it (no flags, half precision)** with the renamed file | **74 to 81 s** a clip; no "lora key not loaded" line; **the LoRA works in half precision** (the earlier fp32 flag is not needed for it) |

What the pictures showed (guidance 3, strength 1, seed 7; new scenes not in the pictures):

- **A woman walking on a beach at sunset.** Base model: a silhouette from behind. With the LoRA: a woman facing the camera with long dark wavy hair and a brown skin tone, her
  hair moving in the wind, in motion over the 2 seconds. Run B shows the face clearer and nearer to the pictures than run A. **The likeness is partial**: colouring, hair
  length and general look are right; the face is not reliably the same person, hair texture drifts (wavy to curly) and details change from frame to frame.
- **A woman in a red saree in a garden.** Run A kept a standing figure with the same colouring and a visible face; run B framed the face at the top edge (composition, not identity).
- **A close-up portrait.** Too tight to judge (only the middle of a face): a dark-haired woman with a similar complexion in both runs.
- **Without the word** ("a woman walking on a beach") the LoRA still pulls toward Ena (long dark hair, from behind): **a LoRA is always on**, so it leaks into
  generic prompts about a woman; the product needs a strength control and a way to turn it off.
- **Faces are small.** The video model is small (2B) and a face in a 640x576 clip is a few dozen pixels across, against a full portrait in the picture LoRA's output. A side-by-side with
  the picture LoRA of the same set (ADR-0073) was **not measured** here; it is a judgement from the pictures, for the owner to check.

Findings for the build: (1) **pictures alone teach a subject**, so the first video screen can take pictures as well as clips (and a person's likeness test is cheap: 12 to 36
minutes, 7 to 10 GB); (2) likeness needs larger faces: a framing hint, larger training sizes (768 and up) and more steps (3000 were better than 1500, the loss still falling);
(3) the loss falls about 60 percent in both runs, but **the loss does not say whether the face is right**: the person must look at the clip, as for pictures (ADR-0073's check);
(4) the image-to-video mode, where the picture itself fixes the face, is the likelier way to keep a likeness and is **untested** with a LoRA.

## 9. The product's own run (2026-10-26, later): Ena through the real routes, and the look used from the product's workflows

The same subject, this time **through the product as built** (ADR-0073, "Built (2026-10-26, later): video model training"): the real routes and the real trainer component installed
by the app's installer (182.5 MB, 26 s), the real video model, and only the vision model replaced by the test rig's (the descriptions were Ena's own captions, entered as a person
may change them). The set was **12 Ena pictures and 3 four-second clips** made by a slow zoom over three of the pictures (real ffmpeg; the check marked every item "Good").
The plan said 21 samples, 1,260 steps at 512x768, with checkpointing. It ran **2,769 s (46 minutes), peak 12.0 GB, training loss 1.16 to 0.50**, and published
`wasify-video-ena-f79fbf13.safetensors` (58 MB, 448 tensors named as ComfyUI's LTXV loader expects). The time estimate shown before the run was first "About 2.0 hours" (it
costed every step as the largest sample); it now uses the mean of the samples and says about 50 minutes for this set (the measured 46).

Then **the product's own workflow maps** (`ltx-video-2b-t2v` and `ltx-video-2b-i2v`, filled with `Workflow.fill(values, loras)`, as the graph does) on **the app's installed ComfyUI
with the app's flags (no `--fp32-unet`)**, 512x384, 25 frames, 30 steps, seed 7, guidance as the workflow sets it, the prompt "enavqx, a woman with long dark hair and small stud
earrings, wearing a black sweater, turning her head toward the camera, soft studio light": 14 to 24 s a clip. Picture: `built-ena-look.jpg`; rows are text to video without the look,
with it at 1.5 and at 2.0, then image to video from an Ena picture without it and with it at 1.0.

- **Without the look** the model draws the back of a head. **With it at 1.5** the same prompt and seed give a dark-haired woman with Ena's colouring, a stud earring and a black sweater
  facing slightly away from the camera (the prompt asked for a turn toward it). **At 2.0 the clip is over-baked** (rough skin and hair texture), so the screens start at 1.5 and say that
  above 2 can look rough.
- **Image to video works with a look** at strength 1.0 (the run completes, the first frame is held; the difference from the base is small, as the picture fixes the face). This closes
  the "untested" point of section 8.
- The motion over one second is slight; a look is a subject or a style first and a motion second at this length.

**From the window, end to end.** A second look was taught **from the Train screen** of the real engine (the card, 10 more Ena pictures, name, magic word, whose it is, Teach it: 600 steps, 298 s,
published as `wasify-video-ena-814161ae.safetensors`), then used from the Video screen: **My looks** listed it, Ena was chosen at the default 1.5, the prompt "a woman with long dark hair walking through a
sunny garden, turning toward the camera" got its magic word added, and Make my video ran through the engine, the graph (`check_request` accepted the look), the workflow's `lora_chain` and **the app's
own ComfyUI** (no `lora key not loaded` line): a real **768x512, 5.04 s, 24 fps** clip in **185 s**. Frames: `built-ena-in-the-window.jpg` (a dark-haired woman in a garden turning toward the camera; the foliage
is rough, as the 2B model draws it at this length, and the likeness is partial as before).

**Extend with a look** ran for real through the engine on the clip above (`mode: extend`, the same look at 1.5, 5 more seconds): it completed and the run's output carries the look, the clip made
10 seconds in all. So text to video, image to video (in ComfyUI) and extend all apply a look.
