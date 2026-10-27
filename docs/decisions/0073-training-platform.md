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

**Status:** built for pictures on 2026-10-25 (see "Built: the choice of model and method"); the language engine adds the other
rows. The picture trainer uses one base (FLUX.2 klein base 4B) and LoRA; it is the first descriptor and the first row of the list.

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
- **Not measured (at that point):** the peak memory (measured later, see the next section); the quality over several datasets; style and object runs; resume.
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

## Amendment (2026-10-25, owner): the cards say which kind of model they train

The front door has four cards, in a two by two grid, each with a small label above its plain headline: **Image model training**
(Make my own character or style: built), **Language model training** (Teach my assistant to write like me: coming next),
**Decision model training** (Teach it to sort things, with the example "spam or not spam": coming next) and **Video model
training** (Make my own look or motion for video; from short clips; says it needs an NVIDIA graphics card for now: coming
later, see the video amendment). The labels use the family names of decision 5's table so a person looking for them finds them;
the headlines stay in plain words. Not live means a "Coming ..." tag and no button, never a button that does nothing.

## Built (2026-10-25): Set up training, in the app

A fresh install can now train. `services/api/src/wasifyai_api/training_setup.py` (routes `/desktop/training-setup`, the card
**Set up training** on the Train screen) fetches, on request, what the picture trainer needs, in the same shape as the other
components (3D, the notebooks' reader):

- **Shown first, repeated on the button:** the trainer (mflux 0.22.0, MIT, from PyPI, about 1.1 GB) and the picture model it learns on
  (FLUX.2 klein base 4B, Apache-2.0, from Hugging Face, 15.98 GB), the free disk space needed (about 20 GB), and a button that
  carries the exact total ("Download and set up (17.1 GB)"). The engine refuses a start whose size is not the one shown. A part
  that is already on the computer (a Hugging Face cache that holds a whole copy of the model, a developer's `WASIFYAI_MFLUX_DIR`) is
  used where it is and not offered again.
- **Reproducible:** the trainer's environment is made with `uv` from a **hashed lock** of the exact packages the real runs were made
  with (`products/wasifyai-training/trainer/requirements-aarch64-apple-darwin.lock`, `scripts/lock-trainer.sh`, carried by the engine
  bundle), `--require-hashes`. The model's 19 files have a pinned size and SHA-256 (`training_pins.json`, checked against the values
  Hugging Face publishes), go through the resumable downloader of the Models screen, and are used from the app's own folder
  (`model_path`: the trainer fetches nothing and reads no Hugging Face cache).
- **Checked, then installed:** the tool must start and every model file be whole before `installed.json` is written. A failed install
  removes the environment it made and keeps the model files that arrived; a new start continues. **Stop** keeps them too.
  **Remove** (Training tools, on the Train screen) gives the space back and keeps the pictures and the models taught.
- **Not Apple silicon:** the card is replaced by the reason in words (mflux runs on MLX); nothing is offered.
- **Rehearsed for real, 2026-10-25:** an engine with no trainer and an empty Hugging Face cache, a local stand-in for the hub: the card
  showed the offer, one click made the environment from the lock (offline, from uv's cache), fetched and hash-checked all 19 files,
  started the tool and enabled Start; a run then trained from the app's own copies (step 6 reached, stopped cleanly, no process
  left). **Not rehearsed:** the download from huggingface.co and PyPI themselves (the owner had approved the 16 GB once; the
  stand-in served the same bytes), and an interrupted download resuming through this installer (the downloader's own tests cover it).
- The hard-coded path of the spikes' environment is gone: a developer's own copy is named by `WASIFYAI_MFLUX_DIR`.

## Built (2026-10-25, later): "Did it learn?", safety around a run, and the style and object runs

All of it was run for real through the screens on the owner's M5 Pro (64 GB), with the person's own Qwen3.8 27B as the vision model and the
distilled klein as the image engine. Three picture sets: 12 pictures of one fictional character, 15 pictures in one paper-collage style and
15 of one blue teapot (the last two drawn by the app's own image engine).

- **Did it learn? (decision 10).** After a run the model is drawn on two new scenes three ways (with the model and its magic word, with the
  model and no word, the base model alone) from one seed, and the picture-reading model says for each whether it looks like the pictures it
  learnt from (three small references are kept with the model; the judge compares with what all the references share). The card gets a
  sentence and **Passed** or **Did not pass** (never blocking), the reasons show under each picture, and the check starts by itself after a
  run (and by a button later). It passes when the pictures with the word look like the references at least half the time and the base
  model's do not. A soft check by a vision model, not a proof. **Measured:** character **passed** (1 of 2 with its word, base 0 of 2; it also
  appeared without the word, 2 of 2: strong); object **passed** (1 of 2, base 0 of 2; the first judge, which counted a spout that varied
  between the references against it, said 0 of 2, so the instruction was changed); style **did not pass** (below).
- **Safety around a run.** Before a run the screen shows what could stop it (memory, disk, a flat battery) and what to look out for (tight
  memory, battery power), and what waits while it runs; **Pause** keeps the last checkpoint (every 25 steps; the newest two are kept) and
  **Carry on** picks it up where it stopped, also after the app was closed (a run left going is paused when it has a checkpoint, else
  stopped); **Discard** removes what was kept. Real run: paused at step 50 of 200, carried on, finished, passed its check. The first real
  attempt found a bug no test had: the resumed trainer still read the checkpoint it started from, which the clean-up had removed (it
  failed at step 124); that checkpoint is now kept. An older training database is migrated (the status check gained `paused`).
- **Measured on this Mac:** the most memory a run held (system footprint, Metal included): **21.0 GB** for the style and the object runs and
  **35.0 GB** for the character run; the memory check uses the worst case, 35 GB (it said 28 GB, a guess). Time: **25 to 41 minutes** for
  150 to 250 steps, 9.2 to 11.6 s a step in all (model load and sample pictures included), so the estimate is 10 s a step (it said 7.5 s):
  character "about 33 minutes". Peak memory differed between kinds for a reason not found.
- **Magic words against the real tokenizer.** The engine reads how the model's own tokenizer splits a word (in the trainer's environment) and
  the app refuses a word that is one piece or holds a word the model knows (and suggests only words it likes). Measured on the klein
  tokenizer: 483 of 500 random pronounceable words pass; "dog" and "sunrise" are one piece, "brainy" holds "brain".
- **Style did not carry over to a new scene: not solved.** Three real runs of the paper-collage set, each judged 0 of 2 on new scenes (a
  lighthouse and a bowl of fruit stayed photographs): 250 steps at learning rate 1e-4, 500 steps at 1e-4, 250 steps at 3e-4. The scenes it was
  shown are learnt (the fox turns into a paper cut-out by step 508) and a stronger strength (up to 2.0) does not bring the style to a new
  scene (`docs/spikes/train-t3/style-500-steps-seen-and-new-scene.jpg`, `style-strength-0-1-1.5-2.jpg`). More steps and a higher rate are
  therefore not the lever; untried: more pictures of more different subjects (15 was used), the text-stream layers (mflux's recipe here trains the
  image stream only), a higher rank. The check reports it honestly and says what to try ("add pictures of different things"); the style preset
  stays at 250 steps and 1e-4. Backlog D32.

## Built (2026-10-25): the choice of model and method

The amendment of 2026-10-24 is built for pictures; nothing in it is guessed.

- **Descriptors:** `products/wasifyai-training/wasifyai_training/bases.py`. A `Descriptor` names a family, a base model, its engine, its
  licence and the methods it cannot use with the reason for each. Today one: FLUX.2 klein base 4B, engine mflux, LoRA only (QLoRA: "pictures are
  taught as a small adapter"; full fine-tuning: "far more memory than a Mac has"). `engine_for` is `bases.resolve(kind, base, method)`: it
  returns the descriptor and method a run will use, or says in words why a choice cannot be used. A new base or method is one descriptor entry.
- **The list:** `GET .../train/choices?kind=` joins the descriptors with the engine's fit (too big, not set up) and the models the discovery scan found
  (kind `diffusion`); an installed model with no descriptor is listed as "cannot be taught yet", never offered.
- **The run:** `POST .../train/runs` and the action `train.start` take optional `base` and `method`; absent means the recommendation, so
  every earlier caller works. A refused choice answers with the reason and starts nothing. The run's settings, and so the model's card, record the
  method and the engine beside the base.
- **The screen:** under the recommendation a closed "Choose the model and method" (`packages/ui/src/training/Choose.tsx`, `use-choices.ts`): models
  with the recommended one marked; methods in words first with the technical name second; teaching all of it under "For experts"; anything that
  cannot be used is disabled with its reason. A method the chosen model cannot use falls back to the model's recommendation.
- **Tests:** `test_bases.py` (rows, reasons, refusals, the run record), the client and the screen (closed by default sends nothing; an open choice
  sends only what changed).
- **Not built:** the rows for writing models (QLoRA, full fine-tuning on Unsloth's component) and for video; they are descriptor entries when
  those engines arrive.

## Built (2026-10-25, last): the character recipe against AI Toolkit, and steps by picture count

The owner asked whether the app's trainer is "the wrong tool", because an earlier AI Toolkit run of the same character drew more realistically. Measured
on the owner's 37 approved pictures and captions (Ena), drawn through Create's own klein workflow on a private ComfyUI (the distilled model, 4 steps,
seed 42; scripts were kept outside the repository):

- **Same base.** The AI Toolkit run trained `flux-2-klein-base-4b`, as the app's does (it was first guessed to be the distilled model: wrong).
  The differences are the steps (500 against the preset 200), the resolution (512 against 768), the text-stream layers (AI Toolkit trains
  `txt_attn` and `txt_mlp`, 160 tensors; ours the image stream only, 120) and the number of pictures the earlier app run used (11 against 37).
- **mflux, 518 steps, 512 px, 37 pictures** (51 minutes, 6.0 s a step): through Create, as realistic as the AI Toolkit adapter and sharper (the
  AI Toolkit adapter drew smooth skin and a flat dress at 1024); the 200-step checkpoint of the same run looked as good; the earlier 200-step app
  run on 11 pictures also looked as realistic and as close to the reference. **A plain "A beautiful woman" with no word gives a woman of Ena's
  look from all of them.**
- **Where it is weak:** with only the magic word and no "woman" (`enav7qx, natural portrait photo, three-quarter view`) the 37-picture run drew a man
  in a portrait and in sportswear: the word alone does not bind the person strongly enough; AI Toolkit's adapter did for the portrait but not for the
  sportswear. The 11-picture app run, whose descriptions say "she" and "the woman", bound a woman reliably. So the descriptions of a character should
  keep the person's kind (woman, man, dog) in words; this is a measured lead, not changed yet.
- **Decision: steps follow the picture count; a character is taught at 512 px.** `trainer.steps_for(kind, pictures)`: 14 passes over the pictures, never
  fewer steps than the preset (200, 250, 150), never more than 500; 11 pictures stay at 200 steps, 25 take 350, 37 take 500. A run states its side
  (`settings.side`: 512 for a character, 768 for the others, which are not measured at 512), the engine passes it as `max_resolution`, and the time
  estimate uses the measured seconds a step for that side (6 s at 512, 10 s at 768); each set says its own steps and estimate. **Not proven:** that 500 steps
  beats 200 in likeness (no difference seen on one seed and four prompts), and that 512 px equals 768 px on the same data.
- **Not done:** training the text-stream layers (needs the `txt_*` rename in `comfy_lora.py`, a different layer list) and an A/B of it; the in-app
  Try it on this recipe; a likeness score (only eyes, mine and the owner's).

## Amendment (2026-10-26, owner): the decision card is built, and it is called "Teach it to decide"

The third card is live. Its headline is **Teach it to decide** (the words "sort things" described only one of its three kinds); the
family label stays "Decision model training". Engine, measurements and what is not built: ADR-0075, "Built (2026-10-26, later)". It is
taught as a whole model (Laya: 420 million numbers), so decision 3's list of methods shows LoRA and QLoRA with the reason and the
recommended method is "full" (the model is small enough to teach all of it; a run holds about 11 GB).

## Spike TV0 result (2026-10-26): the video model can be taught on this Mac

Measured in `docs/spikes/video-training-tv0.md` (decision 3 and 7 of the video amendment asked for it). **LTX-Video 2B 0.9.5, the model the app already uses, was
taught a look by a LoRA on this Mac's graphics chip** with a small script of ours on PyTorch (MPS), `diffusers` and `peft` (no NVIDIA card): about **0.5 s a step and
7.4 GB** at 384x256 with 25 frames, **7.7 s a step and 9.8 GB** at 768x512 with 49 frames (2 s) with gradient checkpointing (without it 49.6 GB). The result loads in the
app's own ComfyUI (fp32) after a rename of its keys (the file as saved is silently ignored there). So decision 4's "Mac path is unproven" and the card's
"needs an NVIDIA graphics card for now" are **no longer true for this model**; the card's words change when the feature is built (TV1), not before.
Still open: a real subject (the data was synthetic), the steps needed at a real size (300 at 768x512 were not enough; 800 at 384x256 were), image to video,
and 16 GB Macs. The only ready-made Mac trainer found (`ltx-trainer-mlx`) teaches LTX-2.3, a different and much larger model that the product does not ship (ADR-0037 avoids its licence). It was **not run because it needs a download of 20 GB or more that was not asked for and its numbers would not transfer to the 2B model**; nothing in ADR-0037 forbids running it as a measurement.

**Real-subject test (2026-10-26, owner's approval and the fictional character Ena):** a video LoRA taught from the 36 Ena pictures alone (no clips) took 12.5 minutes (640x576, 1500 steps,
7.2 GB) or 36 minutes (768x704, 3000 steps, 9.6 GB), and **worked in the app's own ComfyUI in half precision** (the fp32 setting was not needed). It moved a generic "woman on a
beach" toward Ena (long dark hair, brown skin, a face turned to the camera) but **the likeness is partial** and weaker than the picture LoRA's; it also leaks into prompts without
the magic word. Pictures alone teach a subject, so the screen can take pictures as well as clips. Details: `docs/spikes/video-training-tv0.md`, section 8.

## Built (2026-10-26, later): video model training, "Make my own look or motion for video"

The fourth card is live on the desktop (owner: "I want you to finish the whole video training work. I let you decide the order of steps. I approve it so you won't need
any approval of mine. I'll test it in the morning."). It teaches the app's own **LTX-Video 2B 0.9.5** (ADR-0037) a look, a motion or a subject from pictures and short clips
and gives the result back as a **look** that the three Video screens can apply. The card's old words ("Needs an NVIDIA graphics card for now", "Coming later") are gone
(decision 4 of the video amendment is superseded for this model: TV0 showed it works on the Mac's graphics chip).

**What it is, in the order a person meets it**

1. **Train models › Video model training › Make my own look or motion for video.** A set is made with `family: "video"` (`datasets.family`; `items.media`, `seconds`,
   `frames`). Pictures and clips go in the same set (a still picture teaches a subject well, TV0 section 8; clips teach motion). The set is checked in words, a description
   is written for each (the clip's middle frame is what the vision model reads), the magic word, the name and whose it is are chosen as for pictures, and the person
   chooses Teach it. A video set cannot be started by the picture engine (`wrong_family`), and the picture routes still list only picture sets unless asked
   (`?family=`).
2. **Clip checks** (`clips.py`, real ffmpeg through `imageio-ffmpeg`, else `ffmpeg` on the path): too short (under 2 s), too small (under 384 px on the shorter side), too
   dark, blurry, still (a mean grey change between frames, `STILL_BELOW = 1.5`) and a copy. Unreadable files, files under 0.3 s, over 10 minutes or under 64 px on a side are
   refused in words. The frame goes through the same moderation as a picture (ADR-0047).
3. **Plan.** The size follows the median shape of the set (wide 768x512, tall 512x768, square 704x704); a clip gives up to three windows of 25 frames (about one second)
   spread over it; steps are 60 a sample, between 600 and 2,400, capped to a budget of about two hours; **the time is the mean of the samples' costs** (a picture is one
   frame, a window about four times the tokens), not the cost of the largest. A run with clips always uses gradient checkpointing (without it 49.6 GB, TV0).
4. **The trainer** is an environment of its own (`components/video-trainer/`): PyTorch with `diffusers`, `peft` and `transformers` from a committed hashed lock
   (`video-requirements-aarch64-apple-darwin.lock`, 47 packages, about 182 MB, `scripts/lock-video-trainer.sh`) plus five small pinned files of Lightricks' repository
   (the tokenizer and the text encoder's settings, 0.8 MB, revision `8984fa25…`, each with a size and SHA-256). Set up in the app by the same card as the other trainers
   (sizes first, nothing fetched before the button). **The 16 GB of the video model and its text encoder are not fetched here**: they are the files the Video screens
   use, found where the models screen keeps them; when they are missing the card says so and where to get them (**Select video model** on a Video screen).
   `video_train.py` is the script (flow matching, logit-normal sigma, LoRA of rank 32 on the attention layers, T5 captions of up to 128 tokens, fixed-noise held-out
   loss), run with the trainer's Python and read as JSON lines like the other two.
5. **The result.** A model card (`kind: lora`, `card.family: "video"`) and a file `wasify-video-<name>-<run>.safetensors` in the models folder's `loras` folder, with the
   keys renamed for ComfyUI (`ltx_lora.py`: the `transformer.` prefix removed; without it ComfyUI loads the file and does nothing). It is searchable like every
   creation (ADR-0041) and removing the model takes the file back.
6. **Use it** (`products/wasifyai-video`): the three workflow maps carry a `lora_chain` (up to two `LoraLoaderModelOnly` nodes between the model and the sampler), the
   request takes `loras: [{name, weight}]` (strength 0.1 to 2.5, refused in words outside it), and the Video screens show **My looks** (a closed section, only when a look
   exists): up to two, a strength each (1.5 to start: TV0 found a look needs 1.5 to 2 at the app's guidance of 3), and the magic word is added to the prompt when it
   is missing. The discovery scan recognises a video look by its tensor names (`ltx-video`) so it is not offered as a picture style.
7. **Actions.** `train.start` takes a `dataset_id` of a video set and runs the video engine (no new action: the catalogue stays at 51); `docs/help/train.start.md` and the
   three Video help files say so.

**Measured on this Mac (64 GB, 2026-10-26)**

- The component's real install through the app's installer: 182.5 MB, 26 s (the packages were in uv's cache).
- **A real run through the real routes** (`docs/spikes/video-training-tv0.md`, section 9): Ena, 12 pictures and 3 four-second clips, 21 samples, 1,260 steps at 512x768 with
  checkpointing: **46 minutes (2,769 s), peak 12.0 GB**, training loss 1.16 to 0.50, a 58 MB look published. Made with the product's own workflow maps on the app's installed
  ComfyUI (no fp32 flag): the same prompt gives the back of a head without the look and a dark-haired woman with Ena's colouring with it at 1.5; **2.0 is over-baked**, so the
  screens start at 1.5. Image to video with a look runs (it was untested). A run of 10 Ena pictures started from the window took 298 s (600 steps).
- **A real window check, end to end** (a temporary harness against the real engine, deleted): the card is live, clips and pictures are added and checked in words, the Check step shows the video
  notices and the video model choice, Teach it runs (298 s for 10 pictures), the model appears in My models, **My looks** on the Video screen lists it, and Make my video with it (strength 1.5, the
  magic word added) made a real 768x512, 5 s clip in 185 s through the engine, the graph, the workflow's `lora_chain` and the app's own ComfyUI.

**Not built / not verified:** the web (the trainer is desktop only; the card says "On the desktop app"); a 16 GB Mac (untested, memory is 9.8 GB at 768x512 with clips
but nothing else was measured); a look kept warm; likeness: the look is partial for a person (TV0 section 8), so the screens say a style or motion works best;
a before-and-after clip on the model's card (the picture card has "Did it learn?"; the video card says "look at it" and offers nothing to judge); the comparison with
LTX-2.3 (backlog D38, waits for the owner's yes).

## Amendment (2026-10-27, owner): Train on the web, identical to the desktop

"Do the Train work for web. It should be identical to desktop." Plan, stages and the three seams (Postgres rows, files in object storage, a remote trainer that runs the
desktop engine class on an engine worker): `docs/train-web-plan.md`. The owner's answers: all four cards one at a time; "Use in chat" for a writing model works on the web (a worker
serves the adapter behind a per-person alias); every signed-in person may train, with the desktop's quotas and safeguards. Models a person taught are never shared with others: a
generation names the person's own models and the media worker receives them for that job only. On a Linux GPU host the picture and writing trainers need another engine (P7).

## Built (2026-10-27): Train on the web, identical to the desktop

All four cards run on the web (`docs/train-web-plan.md` has the design, the stages and the real runs). **Seams:** the same `TrainingStore` on Postgres (`pgstore.py`; the shared SQL needed two portability fixes
that running both databases found); the files in object storage under the person's own prefix with the API's disk as a cache (`files.py`, `folder_ready`, `folder_saved`, `folder_gone`); and a **remote trainer** per family
(`remote_train.py`) that queues an engine job, which a worker runs with the desktop's own engine class (`services/engine-worker/.../train.py`, handlers `train.video`, `train.image`, `train.decision`, `train.writing`, and the
ask jobs). An admin sets each trainer up on a worker (`POST /admin/workers/engines/<name>/fetch`; Admin > Workers > Trainers). A person's own looks and styles are never shared: a request names them, the graph resolves
the storage key of **that person's** model (or refuses, "not yours"), and the media worker fetches the file for that one job into its `loras` folder and removes it.
**Checked for real** through the web stack on this Mac: Ena's video look (2,761 s, the desktop's loss to four decimals, used from the web API for a real 768x512 clip), a decision model (43 s), a writing model (12 s) and a picture
style. **Not built:** *Use in chat* for a writing model (a worker would have to serve the adapter behind a per-person chat alias), pausing a run, a queue of runs, the Linux GPU trainers (P7).
