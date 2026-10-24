# ADR-0073: Training in the app: one simple front door, Unsloth's trainers behind it

- **Status:** Accepted (2026-10-18, by the owner), together with the components it names. **Revised the same day** after the owner's
  screenshot of Unsloth Studio's Train page and three clarifications (below); the first draft misread "decision
  model" as "diffusion model" and wrongly said Unsloth does not train on a Mac.
- **Date:** 2026-10-18
- **Depends on:** ADR-0068 (action catalogue), ADR-0056 (one engine; one memory slot), ADR-0058 (a runner for work on
  another machine), ADR-0061 (how Unsloth code enters), ADR-0062 (reuse matrix), ADR-0063/0064 (model discovery and
  hub), ADR-0047 (safeguards), ADR-0044 and ADR-0066 (a person's word before using their likeness or voice),
  ADR-0041 (everything made is searchable).
- **Supersedes:** ADR-0062's "LoRA training: mflux" row (the engine choice moves to this ADR and ADR-0076; mflux
  stays for the Mac), and re-opens ADR-0054 (withdrawn) for the desktop.
- **Specific ADRs:** ADR-0074 (language models), ADR-0075 (decision models), ADR-0076 (image LoRA).
- **Plan:** `docs/phase5-agent-training-video-builder-plan.md`, stages T0 to T5.

## Context

The owner's instructions, in order:

1. Train **a language model, a decision model and an image LoRA**; Ostris AI Toolkit was the first idea, "I'm
   flexible".
2. (After sending the screenshot) "I meant **the available training options in Unsloth**. We can probably **reuse the
   code** but need to **simplify the UI**."
3. "For images the user will **only upload images** and we need to **generate the image descriptions and suggest a
   trigger word**."
4. "The purpose of the whole system will be **user friendliness for non or less technical users**."

**What Unsloth Studio offers** (the reference clone `~/Projects/unsloth`, read 2026-10-18; the screenshot is its
Train page on the owner's M5 Pro, 64 GB):

| Option in Studio | What it is | Where it runs |
|---|---|---|
| **Train as: Language model** | text, vision, audio and embedding models; methods **QLoRA, LoRA, Full, CPT** (continued pre-training); LoRA variants lora, rslora, loftq, dora; datasets from Hugging Face, an uploaded file (CSV, JSON, JSONL, Parquet, PDF, DOCX, TXT, MD) or S3; formats auto, alpaca, chatml, sharegpt, raw; export to GGUF, merged or adapter | CUDA, and **Apple silicon through an MLX backend** (text and vision; **not** CPT, embedding models, LoftQ, or streaming datasets on MLX) |
| **Train as: Decision model** | a model that answers typed questions about a text with probabilities (ADR-0075): layouts Laya (small encoder), Clef (9B or 27B, GPU only), or an LLM with a decision head (QLoRA) | CUDA; the trainer has an MLX path for the LLM layout; Laya's Mac path is unknown |
| **Diffusion LoRA** (`/api/train/diffusion/*`) | image LoRAs for SDXL, FLUX.1, Qwen-Image, Z-Image, Krea 2, FLUX.2 klein and dev, and video models (LTX-2, MiniMax-H3); from a folder of images with a sidecar `.txt` per image or a `metadata.jsonl`; **images without a caption are skipped** | **CUDA or Intel XPU, else CPU**: no MLX or Metal path, so not usable on a Mac |
| Studio screens | Model, Method, HF token, Train as, Dataset, Subset, Train split, Evaluation split, Project name, Max steps / epochs, Context length, Learning rate, Advanced (batch, accumulation, optimiser, scheduler, rank, alpha, dropout, packing, gradient checkpointing, offload, W&B, TensorBoard), Load/Save YAML | |

Licence: the `unsloth` library is Apache-2.0; **Studio (`studio/`) is AGPL-3.0**. ADR-0061 already says how AGPL
code enters (a clearly named place with a notice and provenance, never linked into the Apache-2.0 core).

**Other facts, unchanged** (re-checked in spikes T0 and T1):

- On this Mac, `wasifyai-art` trained a FLUX.2 klein base 4B LoRA with **mflux** (MIT) at about 7.5 s per step; the
  trigger word binds only with the full timestep range, at 150 to 300 steps (ADR-0056, ADR-0062). mflux lists Z-Image
  and FLUX.2 base and distilled as trainable and FLUX.1 as not.
- **Ostris AI Toolkit** (MIT) trains LoRA and LoKr for a long model list on **NVIDIA** GPUs, with cloud paths (RunPod,
  Modal). Its macOS script is "experimental" and ADR-0054 recorded that its Apple-silicon path did not converge.
- The app has **one memory slot** (ADR-0056); a training run holds it for minutes to hours.
- **Licences travel with weights** (FLUX.1-dev is non-commercial; ADR-0012). A model of a real person's **likeness**
  is the most abusable thing the app could make.

**What Studio's screen tells us about the audience.** It is built for people who know what QLoRA, context length,
learning rate, subsets and splits mean, and who bring a Hugging Face token and a dataset. The people the owner means
bring **a folder of photos, a spreadsheet, or some chats**, and want a result.

## Decision

1. **Training is a kind of job, not a separate world,** using the engine's job, event and slot machinery (ADR-0006,
   ADR-0021, ADR-0056): `job_progress` with step, loss and sample images; cancel; resume; a replayable log. Its
   actions are in the catalogue (ADR-0068): `dataset.*`, `train.start`, `train.status`, `train.cancel`,
   `train.publish`, `model.list`. Effects are `make`, flagged `costly`; a remote run is also `leaves_device`.
2. **Unsloth is the engine; we do not rebuild its trainers.** Language and decision training, and image LoRA on
   NVIDIA, run through an **"Unsloth trainer" component**: a pinned copy of Unsloth Studio's backend installed on
   request (size, source and licence shown first) in its own environment under `<app data>/components/trainer/`,
   started by the engine when a run starts and stopped after. It is reuse level **A** of ADR-0062 (an engine behind
   an adapter), chosen over copying Studio's modules into our tree (level B) because its trainers are 30,000 lines
   that depend on Studio's own utilities and update fast. How we drive it (its REST routes, `/api/train/*`, over
   loopback with a one-run token, or its worker subprocess) is decided by spike T0. **The licence boundary:** the
   component is a separate program under AGPL-3.0, with its notice and a source link in the app; our code talks to it
   over a socket and stays Apache-2.0 (as `apps/desktop` keeps its own AGPL header, ADR-0061). A fallback exists:
   `mlx-lm` directly for language LoRAs if the component proves too heavy or unstable.
3. **Engines are descriptors, as voices are (ADR-0066).** A file per engine and family: engine, base models,
   platforms, minimum memory, input and output formats, the licence of the engine and of each base model
   (`commercial_use: yes | conditional | no | unreviewed`), and `measured` (time per step, peak memory, on which
   machine). The screen lists only what can run here and why the others cannot ("needs an NVIDIA GPU"). **No number
   is guessed.**

   | Family | This computer, Apple silicon | NVIDIA (own or rented) |
   |---|---|---|
   | Language model | Unsloth component, MLX backend (QLoRA default) | Unsloth component, CUDA |
   | Decision model (sorter) | Unsloth component; Laya on the Mac to be measured | Unsloth component (Laya, Clef, LLM head) |
   | Image LoRA | **mflux** (our measured path) | Unsloth diffusion trainer; **AI Toolkit** as an alternative engine if the spike finds a family it does better |

4. **Three tiers for where it runs, chosen by the person, never silently:** **this computer** (nothing leaves),
   **my other machine** (the runner of ADR-0058: an NVIDIA box under the desk), **a rented GPU** (the person's own
   account and key; the dataset leaves, with the destination, size and cost shown and a click needed). The training
   code is the same; only the runner differs.
5. **The front door is simple, and this is the rule that decides everything else.** One menu entry, **Teach**, with
   three cards in plain words: **Teach my assistant to write like me** (language model, ADR-0074), **Teach it to sort
   things** (decision model, ADR-0075), **Make my own character or style** (image LoRA, ADR-0076). Each is a
   **three-step flow: Add examples, Check, Train**, then **Use it**. The rules, which a reviewer can check:
   - **No jargon on the main path.** No QLoRA, rank, context length, learning rate, split, subset, token, YAML or
     "decision model" on the default screens. Plain names and one-line explanations.
   - **The person supplies material, not settings.** Photos, a spreadsheet, a document, or chosen chats. The app builds
     the dataset (formats, columns, captions, splits) itself.
   - **The app chooses** the model, method, steps, resolution and learning rate from the descriptor and the measured
     presets for this machine, and shows **one recommendation** in a sentence ("This will take about 25 minutes and
     pause chat and image making").
   - **No account setup on the main path.** Models that need a Hugging Face token or a licence click are not
     recommended; if the best choice needs one, the app asks once, explains why, and stores it in the keychain.
   - **An Advanced panel** (collapsed, labelled "For experts") shows the Unsloth-style fields and lets a technical
     person change them or load a saved configuration (YAML). Nothing in it is needed to finish.
   - **Everything has a preview and an undo:** the dataset grid before training, sample outputs during, a before and
     after comparison at the end, and Delete.
   - **Results are in words and pictures**, not loss curves: "Right 91 times out of 100", a grid of images with and
     without the LoRA, answers side by side. The curves are in Advanced.
   - **Every refusal has a next step** ("This model needs 24 GB: try a smaller one, or train on a rented GPU").
   A table mapping each Studio option to what we show, hide or fix is in the plan.
6. **Datasets are first-class, private and built by us.** A dataset is a folder in the app data with items, targets, a
   manifest and a content hash, and a checks step in words (ADR-0074 to ADR-0076 list them). With the safeguards on,
   images pass the picture moderator and text the text moderator (ADR-0047). **The person states their right to use
   the data** ("these are mine or I have permission"), kept with the dataset (ADR-0044's pattern).
7. **Likeness and voice need the person's word** (ADR-0044, ADR-0066): a dataset with a real person's face asks whose
   it is; the statement is stored with the trained model and its card. No voice training in v1.
8. **One run at a time, and the machine is told.** Training holds the slot and most of the GPU on a Mac: before it
   starts the screen says what will pause, checks free memory, disk and power, and offers **"train overnight"**.
   Stop and resume from the last checkpoint. Nothing is preempted without a click.
9. **Results are models with cards (ADR-0041).** A trained result is listed under **My models** with its card: base
   model and hash, engine and version, dataset hash and size, the exact settings, steps and time, the trigger word or
   prompt format, the licence it inherits, the person's statements, the evaluation, a date. It is searchable and
   **published to where it is used**: a LoRA into ComfyUI's `loras` folder with the right key names (ADR-0059), a
   language adapter into the language server (ADR-0074), a sorter into the `decision.decide` action (ADR-0075).
10. **Every run is evaluated before it is offered,** in plain words (decision 5), with a "did not pass" mark that does
    not block keeping it. Language fine-tunes also run our regression cases so a fine-tune that breaks tool calling is
    caught (ADR-0074).
11. **Safeguards and cost.** On the hosted web product and the rented tier, quotas and a per-month cost limit apply;
    on the desktop the safeguards follow the switch; the consent statements never do.
12. **Where the code lives.** Datasets, runs and model cards in `packages/platform-sdk`; the product
    `wasifyai-training` (graph, routes, actions); the Unsloth component and mflux as installed components like
    ComfyUI and the notebooks' reader; **the screens in `packages/ui`** (Teach, Datasets, My models), so the web can
    use them later. Studio's own React screens are a **reference only**: our UI is rebuilt on our components.

## Consequences

- Non-technical people get a three-step path for three kinds of training, and technical people keep the knobs.
- We reuse Unsloth's trainers (and their continuing fixes) instead of writing our own, at the price of a large
  component, a pinned version, and AGPL obligations for redistribution (a source link and the licence text).
- The Mac is a real training machine for language models, sorters and (through mflux) image LoRAs, and the honest
  answer for the rest is an NVIDIA box or a rented GPU.
- A new class of long jobs (hours, overnight, resumable) needs a per-capability timeout, as ADR-0054 noted.
- The model card and the plain-words evaluation are the base of trust; the fields are decided now to avoid a migration.

## Alternatives considered

- **Copy Studio's training modules into our tree (level B).** More control, but we would own and track 30,000 lines
  and their coupling. Kept as the fallback if the component route fails.
- **Show Studio's screens with a new theme.** Fast, and it keeps every option in the user's face. Rejected: the
  owner's requirement is simplification.
- **AI Toolkit for everything.** Excellent on NVIDIA, unproven on a Mac. Kept as an alternative image engine there.
- **No training in the app.** The owner wants it.
- **Training only in the cloud.** Private data would leave the machine and the Mac path works.

## Open questions

1. How to drive the component (REST routes with a loopback token or the worker subprocess) and how big its Mac
   install is (spike T0).
2. The licence of Studio redistribution: AGPL-3.0 allows it with source availability; the notice text and where the
   source link lives are a legal read before shipping.
3. Rented-GPU billing: the person's own account first.
4. Whether "train overnight" is shared with agent scheduling (ADR-0072).
5. Memory and time tables per Mac configuration (16, 32, 64 GB), measured per family.

## Not in v1

Preference tuning and reinforcement learning; distillation; training audio or embedding models (video models: see the amendment below); voice cloning
models; continued pre-training and full fine-tuning on the simple path (Advanced only, on NVIDIA); sharing or selling
models; continuous training on chats.

## Owner's answers (2026-10-18)

- **Rented GPUs:** the person's **own account and key on the desktop**; **our own account on the web app**
  (to be confirmed when the web hosting is settled). The first provider is not named yet; it is chosen in T0.
- **Decision model** means Unsloth's decision model (confirmed).

## Amendment after spike T0 (2026-10-19; report: `docs/spikes/training-t0.md`)

Measured on the owner's M5 Pro, 64 GB. Verdict: **T1 Go**, with the conditions below.

- **The component seam (decision 2) is concrete:** Unsloth's trainer runs **headless**, with no Studio UI and no server:
  `unsloth train --config x.yaml`, the Python adapter `create_mlx_trainer_adapter()`, and the worker entry
  `run_mlx_training_process(event_queue, stop_queue, config)`, all with progress, stop-with-save and resume (measured).
  Studio's REST routes (`/api/train/*`) exist but were read, not run. Our seam is a **small runner script of ours that
  runs as a separate process and only speaks JSON lines over a pipe** (progress out, a stop line in).
- **Licence boundary, as the texts read (no legal advice; counsel must read it before shipping):** the repository
  `LICENSE` is Apache-2.0, but `COPYING` is the AGPL text with the statement that `unsloth/*` is Apache-2.0 and
  `studio/*` and `unsloth_cli/*` are AGPLv3. In the installed packages the "Apache" `unsloth` library has AGPL headers in
  67 of 145 files; **the MLX trainer itself (`unsloth_zoo/mlx/*`) carries AGPL v3 headers while the package metadata
  says LGPL-3.0-or-later**. AGPL v3 says inclusion of a covered work in an aggregate of separate and independent
  works does not extend the licence to the rest. The conservative reading is the one already planned and now sharper:
  **ship the component unmodified, with its `COPYING` and a source link, and a runner that is a separate executable**.
  Open for counsel: the mixed headers, and whether a runner importing the adapter in-process counts as a "larger program".
- **T1 conditions:** (a) the licence reading above; (b) pre-seed the transformers side environments (60 MB each) so
  installs need no network; (c) pin unsloth 2026.10.6 and mlx 0.32.3 and count the **2.1 GB** environment as the
  component's size (a no-torch variant was not tried); (d) own the Qwen3.5 PEFT conversion (`mlx2peft.py`) and the
  **thinking-off serving rule**.
- **Measured descriptors (decision 3):** Unsloth MLX QLoRA Qwen3-0.6B 0.31 s/step, 1.19 GB; Qwen3.5-0.8B 0.22 s/step,
  1.76 GB; mlx-lm 0.058 s/step, 0.98 GB and 0.48 s/step, **6.33 GB** (Qwen3.5's large vocabulary); Laya sorter 0.14
  s/step, a 12 s run, 15 ms per answer; Z-Image LoRA with mflux 9 to 12 s/step when not swapping (30 s or worse with
  full swap), 39.9 GB footprint; captions 2.5 to 3.4 s per picture with Qwen3.5-9B. Table in the report, section 7.
- **Not measured:** Qwen3.5-9B and any model over 2B; the 16 and 32 GB tiers; Clef; the REST routes; Unsloth's diffusion
  trainer and AI Toolkit; rented GPUs; Windows and Linux.

## Built (2026-10-24): stage T1 on the desktop, with the image card first

Desktop first, then the web (owner, 2026-10-24); `docs/train-day1-plan.md` has the order and what is left.

- **The product** `products/wasifyai-training` (`/products/wasifyai-training/train/...`): a SQLite store of datasets, pictures
  (with their checks), runs and trained models; picture checks in words (too small, blurry, a copy of another); the picture
  moderator while safeguards are on (fails closed); daily limits for pictures and runs and the usage events `train.picture` and
  `train.run`; the descriptions written by the person's vision model (a character's identity traits, a style's look left out);
  three magic words; the statement of whose the pictures are (required before a run); runs with progress and samples, one at a
  time, stopped when the app closes; a trained model with its card; found by name and magic word in My creations (kind `lora`);
  the action `train.start` (a long action: `job.status` and `job.cancel` follow and stop it).
- **The trainer was a preview** until the real one below (`PreviewTrainer` stays for the product tests): it runs every step, writes sample pictures that say "Preview" and an adapter file
  that is not a model, and the screens say so. The real trainer (mflux, then Unsloth's component) replaces it behind the same
  interface (`TrainJob` in, `TrainResult` out); that is the next stage.
- **The screens** (`packages/ui/src/training`, the client `packages/client/src/training.ts`, the desktop page): the front door with
  three cards (only the picture card is live), Add pictures, Check (what is it, name, magic word, whose, the descriptions), the run
  with its sample pictures and Stop, My models with rename and remove. Checked in a browser against the real engine: twelve pictures,
  the descriptions typed by hand (the dev engine had no vision model), a run, a model.
- **Not built yet:** the real trainer; Use it with before and after pictures; publishing into ComfyUI; the language and sorter cards;
  the web (Postgres store, worker job, the same screens); the magic-word check against the real tokenizer; the blur threshold
  (6.0) was measured on three photographs only.

### Captions on the desktop, measured (2026-10-24)

The descriptions are written by the chat model the person chose, through the desktop's text provider. That provider refused every
picture ("reads text only") whatever the model; it now sends a picture to a model that sees (a model file with its projector, or a
tool such as Ollama that lists `vision`), and still refuses sound. Tried for real on this Mac through the engine, three to six
photographs: **Qwen3.8 27B (Ollama, MLX, 18 GB)**: good captions that leave out what stays the same, about 7.7 s a picture warm (6
pictures 46 s; the first three 24 s with the load); **Gemma 4 e4b (Ollama, 9.5 GB)**: about 6.7 s a picture, but it described the
set instead of the picture ("various backgrounds"), so it does not do this job with this instruction. The measured model of the T0
spike, Qwen3.5 9B with its projector (2.5 to 3.4 s a picture), is the small choice. A model that only reads text says so in words.

## Amendment (2026-10-24, owner): the person can choose the base model and the method

The owner asked that the person be able to select the **base model** and the **method** (LoRA, QLoRA, full fine-tuning), and
that the design be flexible enough to **train the models that are installed**, without copying Unsloth Studio's screen. This
changes decision 5's rule "The app chooses the model, method, steps, resolution and learning rate": the app still chooses and
recommends **by default**, and the person may choose instead. The rest of decision 5 holds (no jargon on the main path, the
person supplies material, one recommendation in a sentence, every refusal has a next step).

1. **Two levels.** The main path is unchanged: the three cards and the three steps, ending with one recommendation ("This will
   take about 25 minutes and pause chat and image making"). Under the recommendation a collapsed **"Choose the model and method"**
   shows the choice in plain words. It is not the whole of Studio's Advanced panel (steps, rank, learning rate, YAML stay in
   "For experts", decision 5); it is the two choices the owner named.
2. **Base model: any installed model that can be taught, and the recommended ones.** The list is built from the engine
   descriptors (decision 3) joined with what is on this computer (the model picker's rows, ADR-0086, and the Models page). Each
   row says in words whether it can be taught here and why not when it cannot ("needs an NVIDIA GPU", "this model is a GGUF file,
   which cannot be taught; its original is not installed", "needs 40 GB, this computer has 24 GB free"). A model that is not
   installed but is recommended is listed under Recommended with its download size, as in the picker. **Nothing is guessed:** a
   model with no descriptor is shown as "cannot be taught yet", not offered.
3. **Method: the ones the engine and the model support**, in words first, the technical name second:
   **Small adapter (LoRA)**, the default and the only one for pictures; **Small adapter, less memory (QLoRA)**, for language
   models, where the engine can quantise the base; **Teach all of it (full fine-tuning)**, Advanced only, with the memory it
   needs shown first. A method the chosen model or computer cannot do is listed with the reason, not hidden.
4. **Train as: the card decides the family** (pictures, writing, sorting, and video: the next amendment) and so which base models are listed.
   A family with no engine here is not a card that does nothing: it says what is missing.
5. **Engine behind the choice.** The product asks `engine_for(family, base, method)`; engines stay descriptors behind the one
   `TrainJob`/`TrainResult` interface (mflux today for pictures on a Mac, Unsloth's component later), so a new base model or
   method is a descriptor entry and not a screen change. The trained model's card records the base (name and hash), the method
   and the engine, so the choice is reproducible.
6. **What it needs before it is built:** the descriptors file per engine and family (decision 3), the installed-model scan for
   trainable bases (the picture bases are known; language bases need the original weights, not a GGUF), `fit` per base and
   method (measured, not guessed), and the screens (`packages/ui/src/training`) with the collapsed choice. The run route takes
   an optional `base` and `method`; absent means the recommendation, so existing callers and the action `train.start` keep
   working (they gain two optional fields).

**Status:** decided, not built. The picture trainer built on 2026-10-24 uses one fixed base (FLUX.2 klein base 4B) and LoRA; it
is the first descriptor and the first row of the list.

## Amendment (2026-10-24, owner): video model training is a family of its own

The owner asked that video model training be in this ADR. It was not: it appeared only as an engine fact (Unsloth Studio's
diffusion trainer lists video models, line 35) and under "Not in v1". It is now a **fourth family**, decided here and
**not built**; ADR-0076 (image LoRA) keeps "Video LoRAs" out of its own scope and points here.

1. **What it is.** A **video LoRA**: a small adapter that teaches the video model a look, a motion or a character from a set of
   short clips, used from the Video screens the way an image LoRA is used from Create (a magic word in the prompt, and
   "Use it" with a before and after clip). Card, in plain words: **Make my own look or motion for video** (the label is
   written with the screens; it follows the no-jargon rule of decision 5). It is a **third step on the same flow**: Add
   clips, Check, Teach, then Use it. Method: LoRA only to begin with; the method choice of the amendment above applies as
   engines allow.
2. **The person supplies clips, not settings.** The dataset is a folder of short clips (and still pictures, which the video
   trainers also take). The checks, in words, are the video ones: too short or too long, too small, too dark or blurry, a
   still frame passed off as a clip, a copy of another clip, the sound (ignored) and, with the safeguards on, the picture
   moderator on sampled frames (ADR-0047). Descriptions are written by the person's vision model from sampled frames (as for
   pictures, ADR-0076 decision 2) and describe the scene and the motion, not the thing being learnt. The statement of whose
   the clips are is required, and a real person's face asks whose it is (decision 7).
3. **Base models are the installed video models that can be taught.** The desktop's video model today is LTX-Video 2B 0.9.5
   (ADR for video, stage V8). **Whether it can be taught, with which engine, in how much memory and in what time is not known:
   nothing has been measured.** Per decision 3 no number is guessed; a spike (**TV0**) measures it before any build.
4. **Engines (descriptors, decision 3).** Studio's diffusion trainer lists video models (LTX-2 and others) on **NVIDIA**; the
   Mac path is unproven, and mflux trains images only. So on this Mac the card is honest: "Teaching video models needs an
   NVIDIA graphics card for now. Train on another machine of yours or a rented GPU" (the tiers of decision 4), unless TV0
   finds a Mac engine. Windows and Linux with NVIDIA are the first place it could work, as for the other families.
5. **Cost and safety.** Video training is the heaviest family: the screen shows the estimate and the memory it needs first, a
   rented run shows the destination, size and cost and needs a click (decision 4), the quotas of decision 11 apply, and the
   one-run-at-a-time rule holds (decision 8).
6. **Where the result goes.** A video LoRA is a model with a card (decision 9; kind `lora`, family `video`, base recorded),
   found in My creations search, and **published to where video is made**: the ComfyUI video workflow's `loras` folder with the
   right key names for that model, the same way image LoRAs are published. The action `train.start` gains `family: "video"`
   (ADR-0068 floor: `make`, `costly`, and `leaves_device` when rented).
7. **Needs before it is built:** the TV0 spike (can LTX-Video 2B be taught, on what, how fast, how much memory, does it keep
   the magic word, does it load in ComfyUI after the key rename); the video descriptors; the clip checks and the frame
   captioner; the screens; the licence of each trainable base model (decision 3, `commercial_use`).

**Status:** decided, not built; it follows the picture card's real trainer and the language card. Not in the first release
unless TV0 finds a path that works on the owner's Mac.

## Built (2026-10-24, later): the real picture trainer (mflux) on this Mac

`services/api/src/wasifyai_api/desktop_training.py` (`MfluxTrainer`) replaces the preview in the desktop engine. It runs
`mflux-train` (0.22.0, MIT) as a separate process in its own process group, holds the one big-model slot, reads the progress
bar, copies each sample picture as it appears (`step-0000-1.png` is what the untrained base drew), takes the adapter out of the
last checkpoint and removes the pictures copy and the checkpoints. A stop or the slot being wanted kills the group. It says in
words why it cannot run (not an Apple-silicon Mac; the tool not set up; the base model not on the computer) and **never
downloads silently** (`HF_HUB_OFFLINE=1`).

- **Base and recipe:** FLUX.2 **klein base 4B** (Apache-2.0, 15 GB on disk: transformer 7.75 GB, text encoder 8.1 GB, VAE 0.17 GB),
  not the distilled klein that Create image runs (the file in ComfyUI hashes to the distilled repo, not the base). LoRA rank 16 on
  the attention and feed-forward layers of the 5 double and 20 single blocks, 8-bit base, 768 px, gradient checkpointing, full
  timestep range (0 to 28, sigmoid), AdamW 1e-4, one picture a step, 4 sample rounds of 2 prompts (one scene it saw, one new).
- **Measured, once, on the owner's M5 Pro (64 GB), through the real screens:** 12 pictures of one fictional character, descriptions
  written by Qwen3.8 27B (Ollama), 204 steps (17 epochs): **39 minutes** wall in all (2,361 s, with the model load and 10 sample
  pictures); about **9 s a step** between samples; adapter **77.7 MB**. `docs/spikes/train-t3/before-after.jpg`: before training the
  magic word gave a young woman with hair pulled back; after it the same words gave long dark wavy hair and the face and build of
  the set, in the seen scene and in a new one (a sunny park). That is one run on one set: **binding** (the word means the
  character) looks right by eye on 2 prompts, not by a test.
- **Not measured:** the peak memory (the `fit` figure of 28 GB is the engine's number and is **not measured** for klein; the
  Z-Image run of T0 had a 39.9 GB footprint); the quality over several datasets; style and object runs; resume.
- **Not built yet (at that point):** Use it, publishing and the check on the distilled klein: built the same day, below. Still to do: the web stage.
- **Found on the way:** the progress bar of the sample pictures (28 steps) looks like training progress, so only the bar whose
  total is the run's own count is read; the bar is redrawn in place, so a step is read when it is written, not when the next one
  starts. A Hugging Face download that is still going has the folders but not the weight files, so "on this computer" means the
  big files are there.

## Built (2026-10-25): publishing to the image engine, and Use it

- **The key rename** (`products/wasifyai-training/wasifyai_training/comfy_lora.py`, no new dependency). mflux names the layers
  as diffusers does and trains the three attention projections apart; ComfyUI's klein has the original fused layout. Each layer
  is renamed (`transformer_blocks.N.attn.to_out` is `double_blocks.N.img_attn.proj`, `ff.linear_in` is `img_mlp.0`, a single
  block's `to_qkv_mlp_proj` is `linear1`), and the three q, k, v pairs of a block become one `qkv` pair that gives exactly the
  three updates (A stacked three high, B on a block diagonal; a test multiplies them out). A layer it does not know is an error,
  never dropped. Checked against the real distilled file: all 60 layers of an adapter match its tensor shapes.
- **Published automatically:** when a run is kept, the engine writes the converted file to `<models>/loras/wasify-<name>-<run>.safetensors`,
  the engine's discovery lists it as a ready style (family flux), and Create's Styles list offers it. The card records
  `published.lora_name`; removing the model removes the file. A failure leaves the model kept and unpublished.
- **Use it (the screen):** on the "is ready" panel and in My models (under "Try it"): the prompt (starting with the magic word in a
  scene it has not seen), "Draw it", and the same words drawn twice with one seed, without and with the model, side by side. It
  uses the image engine's own run client, so it follows Create's rules (one job at a time, the safeguards).
- **Measured, through the real screens on the owner's M5 Pro:** 12 pictures, Qwen3.8 descriptions, 200 steps (204), 41.5 minutes
  (2,491 s), adapter 77.7 MB, converted file 83.6 MB. **A LoRA taught on klein base 4B works on the distilled klein 4B that
  Create runs** (the two are different weights, hash-checked): same prompt and seed, without it a young woman with light brown
  hair, with it long dark wavy hair and the face of the set, the composition unchanged
  (`docs/spikes/train-t3/use-it-distilled-klein.jpg`). ComfyUI logged no unloaded keys. A 96-step adapter on placeholder captions
  already changed the picture the same way. Binding to the magic word (the word means the character, other words do not) is
  **not tested**: that needs prompts with and without the word.
- **Still open:** the web stage; the evaluation of the model (decision 10: the "did not pass" mark); the weight slider; the peak
  memory; a style and an object run.
