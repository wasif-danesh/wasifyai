# Spike T0: training platform measurements (Unsloth component, mlx-lm, Laya, mflux)

Date: 2026-10-18 to 2026-10-19. Machine: MacBook Pro M5 Pro, 64 GB, macOS (Darwin 27.0.0). Plan: `docs/phase5-agent-training-video-builder-plan.md`
stage T0; ADR-0073 to ADR-0076 and ADR-0078. Scratch folder (outside the repo): `~/Projects/wasifyai-spikes/t0/` (scripts, logs, adapters).

**Read this first.** Four spikes shared this Mac. Every model run took the shared lock, but other spikes' runs
(TD0 ran 10 to 20 minute jobs) still overlapped in time with some of mine, so **speed numbers for runs longer than a
minute are marked where contention showed**. The language-model runs were seconds long and are clean. Nothing here is
a quality claim about a trained model: the data is a 44-row fixture I wrote and a 108-row toy sorter set.

## Answers in short

| # | Question | Answer (measured unless marked) |
|---|---|---|
| 1 | Can Unsloth's trainer be driven headless as a separate pinned component? | **Yes.** `unsloth train --config x.yaml` ran a QLoRA job on the MLX backend with no UI and no server; the Python adapter and the worker entry point gave progress, stop-with-save and resume (all measured). The REST routes (`/api/train/*`) exist but were read, not run. |
| 2 | Tiny QLoRA run, Unsloth MLX against mlx-lm | Both work and both learned the style (0 of 12 held-out replies carried the sign-off before, 12 of 12 after). **Unsloth was slower per step on the 0.6B model (0.31 s against 0.06 s) and much lighter on Qwen3.5-0.8B (1.76 GB against 6.33 GB peak; 0.22 s against 0.48 s per step).** Table below. |
| 3 | Chat-template round trip | Training text from Unsloth's formatter equals the model's own template (44 of 44, both models). The served prompt equals the training prompt token for token **only when thinking is switched off** (44 of 44); with the default (thinking on) it was **0 of 44** for both Qwen3 and Qwen3.5. |
| 4 | GGUF LoRA | llama.cpp's `convert_lora_to_gguf.py` converted adapters for **Qwen3 and Qwen3.5** and `llama-server --lora` applied them. Unsloth's own PEFT export **refuses Qwen3.5** adapters; a 30-line converter of ours fixed it (verified identical to Unsloth's output on Qwen3). |
| 5 | Decision model | Licences read (below). **Laya trained and served on the Mac through Studio's MLX decision trainer**: 30 steps in 9.2 s of training, 12.3 s wall, 15 ms per answer. Laya without Studio (its own MPS script) was **not tested**. Clef was not run (19 GB, not approved), but the pinned llama.cpp and Studio's MLX path both contain Clef code. |
| 6 | Image LoRA | **Z-Image (base) LoRA trains with mflux 0.22.0 on this Mac: about 9 to 12 s per step when not swapping (30 s or worse when swap is full)** at 768 px, 8-bit, gradient checkpointing, rank 16, full timestep range, with a peak memory footprint of 39.9 GB (resident 12.6 GB). Automatic captions: about 3 s per picture with Qwen3.5-9B, scenes right, **but the mascot's own design leaked into 5 of 6 captions**. The magic-word tokenizer check works; both text encoders use the same Qwen3 tokenizer. |

**Go or no-go: T1 go. T2 go for small models (Qwen3 and Qwen3.5 up to 0.8B measured), conditional for 9B (not measured).** Conditions are at the end.

## 1. Driving the Unsloth trainer headless (source reading plus runs)

Reference clone `~/Projects/unsloth` at tag `v0.1.907-beta`; the runs used the owner's installed Unsloth Studio environment
(`~/.unsloth/studio/unsloth_studio`: unsloth 2026.10.6, unsloth_zoo 2026.10.6, mlx 0.32.3, mlx-lm 0.31.3, mlx-vlm 0.7.8, mflux 0.22.0,
torch 2.11, Python 3.13), with `UNSLOTH_STUDIO_HOME` pointed at my scratch folder. That whole environment is **2.1 GB** (torch 389 MB, mlx 221 MB, studio backend 131 MB).

### Entry points

| Entry point | Where | Takes | Progress, stop, resume | Measured |
|---|---|---|---|---|
| **CLI** `unsloth train --config c.yaml [--dry-run]` | `unsloth_cli/commands/train.py`, schema `unsloth_cli/config.py` (Pydantic, `extra=forbid`, flags generated from it) | `model`; `data{dataset, local_dataset[], format_type}`; `training{training_type lora/full, max_seq_length, load_in_4bit, output_dir, num_epochs, max_steps, learning_rate, batch_size, gradient_accumulation_steps, warmup_steps, save_steps, weight_decay, random_seed, packing, train_on_completions, gradient_checkpointing}`; `lora{lora_r, lora_alpha, lora_dropout, target_modules, use_rslora, use_dora, finetune_*}`; `logging{wandb, tensorboard, hf_token}` | Prints `Step n/N | Loss | Grad | LR | Tok/s | Peak GB` lines (not machine readable). Ctrl+C stops with a save and exits 130; bad config exits 2, failure 1. **No resume flag, no evaluation split, no decision models, no project name.** | Yes (both models) |
| **Python adapter** `core.training.training.create_mlx_trainer_adapter()` (the object the CLI uses on Apple silicon) | `studio/backend/core/training/training.py` | `load_model`, `prepare_model_for_training`, `load_and_format_dataset`, `start_training(**kwargs)` including `resume_from_checkpoint`, `max_steps`, `save_steps`, `output_dir` | `get_training_progress()` returns `step, total_steps, loss, eta_seconds, peak_memory_gb, warnings, output_dir, error, is_completed`; `stop_training(save=True)` | Yes: stopped at step 20, saved `checkpoint-21`, resumed from it, finished at step 60 (session start step 21) |
| **Worker entry** `core.training.worker.run_mlx_training_process(event_queue, stop_queue, config)` | `studio/backend/core/training/worker.py` | A config dict built by `_build_training_worker_config` (about 90 keys incl. `is_decision`, `decision_layout`) | Events `status`, `warning`, `progress`, `complete`, `error`; stop is `{"type":"stop","save":bool}` on the stop queue | Yes (used for the Laya run) |
| **REST** `POST /api/train/start`, `/stop`, `/reset`, `GET /status`, `/metrics`, `/progress` (SSE), `/hardware`; diffusion under `/api/train/diffusion/*` | `studio/backend/routes/training.py` (5,215 lines), request model `TrainingStartRequest` | Same keys as the worker config plus start-request status and acknowledge routes | Server-sent progress, `/stop`, `resume_from_checkpoint` | **Not run** (needs the server, an auth database and an API key; read only) |
| **Export** `unsloth export <checkpoint> <out> --format lora/gguf/merged-16bit/merged-4bit [--adapter-format mlx/peft]` | `unsloth_cli/commands/export.py` | A run directory | Writes under `<home>/exports/<out>` | Yes, see section 4 |

**Recommended seam for T1 (a measurement-backed opinion):** our adapter starts the component's Python as a **child process
running a small runner script of ours** that calls the Python adapter (language models) or the worker entry (sorters),
writes one JSON line per progress event to stdout, and reads a stop line on stdin. This needs no server, no password and no API key, and it
is what the CLI itself does. The REST route is the alternative if we want Studio's own history and cancellation, at the price of its auth.

### Things that matter for a pinned component

- **It installs packages at run time.** On the first Qwen3.5 run the trainer printed `transformers 5.3.0 not found ... installing at runtime` and installed
  transformers 5.3.0, huggingface_hub 1.8.0, hf_xet and tiktoken into `<home>/.venv_t5_530` (**60 MB, 2 seconds**, from PyPI or the local cache). The installed app has three such side environments
  (`.venv_t5_510` with transformers 5.10.2, `.venv_t5_530` with 5.3.0, `.venv_t5_550` with 5.5.0). A shipped component must pre-seed them or it fails offline. This happened inside my scratch home; I had not asked to approve it separately, so I am recording it here.
- **Output location.** The CLI honours `output_dir` anywhere. The decision trainer only writes under `<home>/outputs` (`path escapes root` otherwise). `UNSLOTH_STUDIO_HOME` moves everything.
- **Isolation slip.** One Laya run started without `UNSLOTH_STUDIO_HOME` and wrote `~/.unsloth/studio/outputs/laya-sorter`. I moved it into the scratch folder and
  restored the empty `outputs` directory; nothing else under `~/.unsloth` changed after 00:33 that night (checked with `find -newer`).
- **Qwen3.5 adapters cannot be exported to PEFT by Unsloth**: `Adapter export failed: ... language_model.model.layers.9.mlp.up_proj.lora_b: outside a Hugging-Face-mirroring transformer stack`.
- Laya's `predict` needs `torch` (the MLX stack otherwise runs without it).
- Models are quantised on the fly (`base_quantized_source: runtime`, 4-bit affine, group 64); the adapter is the MLX format (`adapters.safetensors`, `adapter_config.json`) and is identical in size to mlx-lm's.

### Licence boundary: what the files say (no legal advice)

| Item | What the text says |
|---|---|
| Repository `LICENSE` | Apache License 2.0. |
| `COPYING` (repository root) | The GNU AGPL v3 text, followed by: "Files under unsloth/\*, tests/\*, scripts/\* are Apache 2.0 licensed. Files under studio/\*, unsloth_cli/\* which is optional to install are AGPLv3 licensed." `studio/LICENSE.AGPL-3.0` is the same AGPL text. |
| README | "dual-licensing model of Apache 2.0 and AGPL-3.0 ... certain optional components, such as the Unsloth Studio UI are licensed under ... AGPL-3.0". |
| File headers in the installed packages (counted) | `studio/backend`: 802 of 818 Python files carry an AGPL header; `unsloth_cli`: 23 of 24 AGPL. `unsloth` (the "Apache" library): 67 of 145 files carry an AGPL header, 57 an Apache header, 4 LGPL (e.g. `models/decision_mlx.py`, `models/_decision_fast.py`, kernels are AGPL). `unsloth_zoo`: 89 of 235 AGPL, 67 LGPL, 3 Apache. |
| **The MLX trainer itself** (`unsloth_zoo/mlx/*.py`, including `trainer.py`, 11,377 lines) | Every file but one carries the AGPL v3 header. The package metadata says `LGPL-3.0-or-later`, and the wheel ships both a `LICENSE` (LGPL) and a `COPYING` (AGPL). So the package metadata and the file headers disagree for the part we would run. |
| `unsloth` wheel metadata | `Apache-2.0`, and it also ships `COPYING` (AGPL). |
| AGPL v3, section 13 | A modified version offered to users over a network must offer them the Corresponding Source. We would run it unmodified. |
| AGPL v3, end of section 5 | "Inclusion of a covered work in an aggregate does not cause this License to apply to the other parts of the aggregate", where an aggregate means separate and independent works "not combined with it such as to form a larger program". |
| AGPL v3, section 6 | Conveying object code needs the Corresponding Source offered in one of the listed ways. |
| `apps/desktop` | Already AGPL-3.0-only for imported shell code (`NOTICE`). |

What this means for the plan as written (ADR-0073 decision 2): a **separate process with its own notice and a source link** matches the aggregate wording above and the way
`apps/desktop` is already handled; the risk to read with counsel is the **mixed headers** (the "Apache" `unsloth` package contains AGPL files, and the trainer in `unsloth_zoo` is AGPL by header but LGPL by metadata) and
whether our runner script that imports the adapter in-process counts as a "larger program". Keeping the runner as a **separate executable that only speaks JSON lines over a pipe, and shipping the component unmodified with its `COPYING`**, is the conservative reading. This is a reading of the texts, not an opinion on how a court would see it.

## 2. One tiny QLoRA run: Unsloth MLX against mlx-lm

Data: `data/train.jsonl`, 44 chat rows I wrote (a short two-sentence answer in a fixed voice that ends with "- Wasi"), 6 validation rows, `messages` format. Models: `Qwen/Qwen3-0.6B` and `Qwen/Qwen3.5-0.8B`
(downloaded, Apache-2.0, 1.5 GB and 1.75 GB). Settings both sides: 4-bit base (affine, group 64), LoRA rank 16, alpha 16, all attention and MLP linear layers, batch 2, no accumulation, 30 steps, learning rate 2e-4, max length 512, loss on answers only, seed 3407.
Differences I could not remove: Unsloth uses warm-up plus linear decay, 8-bit Adam and a chunked cross-entropy; mlx-lm used a constant rate and plain AdamW. On Qwen3.5 the two chose different trainable sets (Unsloth 7.27 M parameters, mlx-lm 10.8 M).

| Run | Training time (30 steps) | Seconds per step (warm) | Peak memory | Process peak footprint | Wall (incl. load) | Loss first to last | Adapter |
|---|---|---|---|---|---|---|---|
| Unsloth MLX, Qwen3-0.6B | 9.3 s | about 0.31 | 1.19 GB (its own figure) | 2.10 GB | 25.3 s | 4.62 to 2.28 (mean 3.02) | 40.4 MB |
| mlx-lm, Qwen3-0.6B | about 1.8 s | **0.058** (17.2 it/s) | 0.98 GB | 1.63 GB | 6.8 s | 4.77 to 1.15 (val 2.619) | 40.4 MB |
| Unsloth MLX, Qwen3.5-0.8B | 6.6 s | **0.22** | **1.76 GB** | 3.06 GB | 25.8 s | 4.48 to 1.47 (mean 2.44) | 29.1 MB (7.3 M params) |
| mlx-lm, Qwen3.5-0.8B | about 14 s | 0.48 (2.08 it/s) | **6.33 GB** | 7.47 GB | 22.6 s | 4.11 to 1.03 | 43.3 MB (10.8 M params) |

Reading: on the small Qwen3 model mlx-lm is about five times faster per step (Unsloth's first step spends seconds compiling and its per-step cost includes the compiled loss).
On Qwen3.5, whose vocabulary is about 248,000 tokens, Unsloth's chunked loss ("CCE") keeps peak memory 3.6 times lower and the step twice as fast. A 9B model has the same large vocabulary, so this is the number to watch on 16 and 32 GB Macs; it was **not measured** (see "Not done").

Did it learn (greedy replies to 6 held-out and 6 new questions, thinking off, reply ends with "- Wasi")?

| Model | Base | Unsloth adapter | mlx-lm adapter |
|---|---|---|---|
| Qwen3-0.6B (MLX) | 0 of 12 | 12 of 12 | 12 of 12 |
| Qwen3.5-0.8B (MLX) | 0 of 12 | 12 of 12 | 12 of 12 |
| Qwen3-0.6B (llama-server, GGUF LoRA on the f16 base) | 0 of 12 | 11 of 12 | 12 of 12 |
| Qwen3.5-0.8B (llama-server, GGUF LoRA) | 0 of 12 | 12 of 12 | 12 of 12 |

The replies also carry wrong facts (a 0.6B model after 30 steps copies the voice, not the product): this proves the pipeline, not usefulness.

## 3. Chat-template round trip

Method (`roundtrip.py`): format the 44 rows with Unsloth's own formatter (`utils.datasets.format_and_template_dataset`, the one the trainer calls), compare with the tokenizer's native `apply_chat_template`,
then start `llama-server` on the converted GGUF and compare its `/apply-template` output and `/tokenize` ids with the training prompt (the text up to the start of the answer).

| Check (44 rows) | Qwen3-0.6B | Qwen3.5-0.8B |
|---|---|---|
| Training text equals the native template | 44 of 44 | 44 of 44 |
| llama.cpp token ids equal the Hugging Face tokenizer ids on the training text | 44 of 44 | 44 of 44 |
| Served prompt equals training prompt, **default (thinking on)** | **0 of 44** | **0 of 44** |
| Served prompt equals training prompt, **`enable_thinking=false`**, string and token ids | **44 of 44** | **44 of 44** |
| llama-server's rendering of the whole conversation equals the training text | 0 of 44 (cause not inspected) | 0 of 44 |

The training text puts an empty `<think>\n\n</think>\n\n` before every answer. A server that starts the answer with only `<|im_start|>assistant\n` (Qwen3) or
`<|im_start|>assistant\n<think>\n` (Qwen3.5) shows the model a prompt it never trained on. **Rule for T2: serve a fine-tuned Qwen3 or Qwen3.5 with thinking off (`chat_template_kwargs {"enable_thinking": false}`), or train with
thinking content; ADR-0074 decision 5's test must be run with that flag, and it should compare against the server's `/apply-template`, not only the Python template.**

## 4. GGUF LoRA

Base: `convert_hf_to_gguf.py` f16 (9 and 12 seconds, 1.5 GB each). Adapter: PEFT directory, then `convert_lora_to_gguf.py --base <hf dir> --outtype f16`, loaded with `llama-server -m base.gguf --lora lora.gguf`
(Unsloth's prebuilt llama.cpp b11696, Metal).

| Architecture | Base to GGUF | Unsloth adapter to GGUF | mlx-lm adapter to GGUF | Applied in llama-server |
|---|---|---|---|---|
| Qwen3 (0.6B, `Qwen3ForCausalLM`) | yes | yes (392 tensors, 20.2 MB) after `unsloth export --adapter-format peft` | yes, via our converter | yes (sign-off 11 of 12 and 12 of 12) |
| Qwen3.5 (0.8B, `Qwen3_5ForConditionalGeneration`, hybrid linear attention) | yes | yes (228 tensors, 14.5 MB) via our converter; **Unsloth's own PEFT export fails** | yes (372 tensors, 21.7 MB) | yes (12 of 12 and 12 of 12) |

`mlx2peft.py` (about 30 lines): transposes `lora_a`/`lora_b` and renames `language_model.model.layers.N.*` to `base_model.model.model.language_model.layers.N.*.lora_A/B.weight`, writes `adapter_config.json` (r 16, alpha 16). On Qwen3 its output equals Unsloth's export tensor for tensor (392 of 392 equal).
Adapters trained on the 4-bit base worked on the f16 base. **Not tested:** other architectures (Gemma 4, Llama, Phi), merged GGUF export, quantised bases with a LoRA, and 9B. The pinned llama.cpp lists many more architectures in `conversion/`, including a `clef.py` converter.

## 5. Decision model (ADR-0075)

### Licences, read from the files

| | `convaiinnovations/laya` | `Cloudflare/clef-flash` |
|---|---|---|
| Licence file in the Hugging Face repo | **None.** The repo has no `LICENSE` file. The licence is the front matter of `README.md` (`license: apache-2.0`, tag `commercial-use`) and the footer "Apache 2.0 · Convai Innovations". | `LICENSE`, the full Apache-2.0 text (read to the end), ending in "Copyright 2026 Alibaba Cloud" (the Qwen file reused). `README.md`: "Released under the Apache-2.0 license, following the base model Qwen/Qwen3.5-9B". |
| Other licence sources | The GitHub repository `NandhaKishorM/laya` shows a `LICENSE` and an Apache-2.0 badge (page text, the file not opened); the studio wheel vendors `laya` 0.3.5 with an Apache-2.0 `LICENSE.laya`. | Base model Qwen3.5-9B: Apache-2.0 (`LICENSE` read). |
| Data or use restrictions | **None stated, and the training data is not named.** The card says the base checkpoints are "near chance" zero-shot on its own benchmark and the 0.766 figure is a model fine-tuned on that benchmark's training split; ships over-confident; `noul` answers can follow the option labels; weak on more than 20 options; English checkpoint fails on non-Latin scripts. | None stated; training data not named; the card tests it on public benchmarks listed in the Decision Index. |
| Size | model.safetensors 842.6 MB (English, 421 M parameters), multilingual 643.8 MB | 4 shards of 18.8 GB plus a 0.24 GB head |
| `commercial_use` (our flag) | **conditional**: Apache-2.0 declared, but no licence file in the weights repo and no training-data statement | **yes** for the weights as licensed; training data not stated |

### Can Laya train and run on the Mac, and without Studio?

Through the Studio component: **yes**. `laya_driver.py` called the worker entry with `is_decision: true`, `decision_layout: laya`, LoRA rank 16, batch 8, 30 steps (3 epochs of 84 rows):

| Measure | Result |
|---|---|
| Training | 9.2 s wall in the driver; 12.3 s for the whole process; 30 steps (about 0.14 s per step) |
| Memory | resident peak 2.4 GB; process peak footprint **7.97 GB** (Metal) |
| Output | 842.6 MB (`model.safetensors`, `rl_agent_config.json`, `encoder/`, `tokenizer/`): the full model, not a small adapter |
| Held-out result (Studio's own report) | accuracy 1.0, calibration error 0.0035 on 8 decisions |

Test on 24 unseen sentences (3 categories): **Laya before training 22 of 24, after training 24 of 24**, mean confidence minus accuracy 0.166 before and 0.013 after; **15 ms per answer** (median, after a 0.4 s first call);
a bag-of-words Naive Bayes baseline got 16 of 24. The task is easy, so this shows the path works and calibration moves; it does not show how much training helps on a hard set.
The plan's "embeddings baseline" was **not** run (I used bag of words to avoid another download).

Studio's MLX decision code (`unsloth/models/decision_mlx.py`) also handles **Clef** checkpoints and an LLM with a Clef head, and the pinned llama.cpp converts Clef to GGUF (`conversion/clef.py`). The ADR says Clef is "GPU only"; that is **not confirmed by the code** and was **not run** (19 GB download not approved).
Laya **without** Studio: the Laya README names `notebooks/laya_finetune_typed_decisions_mps.py` (PyTorch MPS or CPU); **not run**.

## 6. Image LoRA (ADR-0076)

### Z-Image with mflux

Base `Tongyi-MAI/Z-Image` (licence: `apache-2.0` in the README front matter; the repo has no `LICENSE` file; downloaded 19 GB: transformer 12.3 GB, text encoder 8.0 GB, VAE 0.17 GB). mflux 0.22.0 (MIT) lists `z-image` and `z-image-turbo` as trainable; the base needs no assistant adapter.
Recipe used (`zimage/train.json`): 15 pipbot pictures from `wasifyai-art`, `quantize: 8`, `gradient_checkpointing: true`, `max_resolution: 768`, batch 1, `steps: 28`, `guidance: 4.0`, **timestep 0 to 28 with `sigmoid`** (the full range our klein finding requires), AdamW 1e-4, rank 16 on `attention.to_q/k/v/to_out.0` and `feed_forward.w1/w2/w3` of blocks 0 to 30, checkpoint every 15 steps.

| Measure | Result |
|---|---|
| Seconds per training step | **8 to 11 s, typically 9 to 10 s** (per-step deltas read from the progress bar: 9, 8, 9, 11, then 8, 8, 10, 14, 13, 14, 8, 9, 9, 9, 10, 9, 10, 9, 9, 10, 9, 9; steps that wrote a checkpoint or a preview took 31 to 42 s) |
| Preview image before training (28 inference steps) | 6.1 s per step |
| Peak memory | process footprint **39.9 GB**, resident peak **12.6 GB** (the footprint includes Metal buffers and the transient load) |
| Total for 30 steps | **6,856 s wall for the whole process, which is not a clean number**: four stalls of 265, 438, 499 and 946 s (between steps 4 and 5, 5 and 6, 7 and 8, 14 and 15) and a further long stall in the 28-step preview. The likely cause is memory pressure: the re-run below saw 22.0 GB of the 23.5 GB swap in use (the run's own footprint is 39.9 GB, and other apps and spikes were resident). Without the stalls the 30 training steps take about 5.5 minutes. |
| Estimate for the product | 150 to 300 steps at 9 to 10 s = **about 23 to 50 minutes** (klein 4B was 7.5 s per step in `wasifyai-art`) |

A short clean re-run (15 steps) was queued behind TD0; see "Clean re-run" at the end. **Not tested:** whether the Z-Image LoRA binds to a magic word, quality, ComfyUI loading and the key rename for Z-Image, Z-Image-Turbo, resume after a pause.

### Automatic captions (Qwen3.5-9B Q4_K_M plus mmproj F16 in the installed llama-server, thinking off)

Downloaded for this: `unsloth/Qwen3.5-9B-GGUF` Q4_K_M 5.68 GB and `mmproj-F16` 0.92 GB. Ten pictures: six pipbot mascot renders and four pictures of the fictional "Ena" character from `character-lora`. Each picture takes two calls (class noun, then caption) with the instruction of ADR-0076 decision 2 (describe the scene, not the identity).

| Measure | Result |
|---|---|
| Server start | about 3 s (weights already cached) |
| Time per picture | **2.5 to 3.4 s** (both calls; 500 to 700 prompt tokens, 35 to 69 reply tokens) |
| Class noun | right in 10 of 10 (robot, woman) |
| Scene correct against the existing ground-truth caption (pipbot 04, 07, 10, 12, 15) | 5 of 5; picture 01 said "coffee" where the picture is tea |
| **Identity features leaked into the caption despite the instruction** | **mascot: 5 of 6** ("round red body, silver limbs, yellow antenna"); **people: 1 of 4** ("long dark hair") |
| Format (1 to 3 sentences, English, no names) | 10 of 10 |

Captions are in `logs/captions.json`. Reading: the scene is reliable; the "do not describe the subject" instruction is not. T3 needs a **second pass that strips the learned-trait words** (compare the ten captions and delete phrases repeated in more than half of them), or a check that warns. Faces and unusual mascots were only tried on this small set; memory of the server was not captured.

### Magic-word check against the real tokenizer

`Tongyi-MAI/Z-Image/tokenizer/tokenizer.json`, the FLUX.2 klein tokenizer and Qwen3's `tokenizer.json` have the **same SHA-256**, so the Z-Image and klein text encoders both use the Qwen3 tokenizer and one check serves both families.
The check (`magicword.py`): encode the word as it appears in a caption (leading space), reject it if it is in the system dictionary, is a single token, or has a piece that is a dictionary word.

| Word | Pieces | Verdict (pieces of 4 or more letters / of 3 or more) |
|---|---|---|
| pipbot | pip, bot | rejected (two pieces); it still bound in the shipped klein run 6 |
| zqx7k, zorvik, mrlzo | z-qx-7-k, z-or-vik, m-rl-zo | ok / ok |
| enav7qx | en-av-7-qx | ok / ok |
| xelmira | x-elm-ira | ok / rejected (elm, ira are words) |
| marlo, sks, robot | mar-lo, sk-s, robot | rejected |

Of 500 random pronounceable strings, 360 pass the 4-letter rule and 222 pass the 3-letter rule, so suggestions are easy to generate. **Weakness found:** `javarobo` passes, because the rule only looks at tokenizer pieces; add a substring check against the word list. Whether a passing word binds is not predicted by this check (pipbot is the counter-example).

### Not done in this section

Rented-GPU runs (Unsloth's diffusion trainer, AI Toolkit): **not done**, as instructed (no account). Unsloth's diffusion trainer has no Mac path (read in `routes/training.py`: CUDA, XPU or CPU).

## 7. Descriptors (for the engine files of ADR-0073 decision 3)

| Engine | Family and model | Mac measured (M5 Pro 64 GB) | Engine licence | Model licence | `commercial_use` |
|---|---|---|---|---|---|
| unsloth-mlx (component) | language, Qwen3-0.6B QLoRA | 0.31 s/step, 1.19 GB MLX peak (2.10 GB footprint), 30 steps in 9 s | AGPL-3.0 by header (mixed, section 1) | Apache-2.0 (`LICENSE` read) | yes |
| unsloth-mlx | language, Qwen3.5-0.8B QLoRA | 0.22 s/step, 1.76 GB (3.06 GB footprint) | same | Apache-2.0 (`LICENSE` read) | yes |
| mlx-lm (fallback) | language, Qwen3-0.6B | 0.058 s/step, 0.98 GB (1.63 GB) | MIT | same | yes |
| mlx-lm | language, Qwen3.5-0.8B | 0.48 s/step, 6.33 GB (7.47 GB) | MIT | same | yes |
| llama.cpp (serve) | GGUF LoRA, Qwen3 and Qwen3.5 | converts and applies; 12 replies in 2.5 to 3.6 s (greedy, 90 tokens) | MIT | same | yes |
| unsloth-mlx (decision) | sorter, Laya English 421 M | 0.14 s/step, 12 s run, 2.4 GB resident, 7.97 GB footprint, 15 ms/answer | AGPL-3.0 by header; Laya runtime Apache-2.0 | Apache-2.0 declared (README), no licence file, data unstated | conditional |
| unsloth-mlx (decision) | sorter, Clef-flash 9.4 B | not run | same | Apache-2.0 (`LICENSE` read) | yes (weights) |
| mflux | image, Z-Image base | 9 to 12 s/step when not swapping, 10 to 12.6 GB resident, 39.9 GB footprint | MIT | Apache-2.0 declared (README), no licence file | yes (declared) |
| mflux | image, FLUX.2 klein base 4B | 7.5 s/step (earlier `wasifyai-art` spike) | MIT | Apache-2.0 | yes |
| llama.cpp (caption) | multimodal, Qwen3.5-9B Q4_K_M | 2.5 to 3.4 s per picture | MIT | Apache-2.0 | yes |
| Unsloth diffusion, AI Toolkit | image, NVIDIA | not run (no GPU account) | | | |

## 8. Go or no-go

| Stage | Verdict | Why, and the conditions |
|---|---|---|
| **T1** platform and simple screens | **Go** | The component runs headless with progress, stop-with-save and resume, measured. Conditions: (a) counsel reads the licence section, because the headers disagree with the package metadata and the "Apache" package contains AGPL files; ship the component unmodified, with `COPYING`, and a runner that only speaks JSON lines; (b) pre-seed the transformers side environments (60 MB each) so installs do not need the network; (c) the runner pins unsloth 2026.10.6 and mlx 0.32.3 and stores the whole 2.1 GB environment as the component size (or measure the no-torch variant, not tried); (d) own the Qwen3.5 PEFT conversion (`mlx2peft.py`) and the thinking-off serving rule. |
| **T2** language card | **Go for small models; conditional for 9B** | Qwen3 0.6B and Qwen3.5 0.8B: train in under 30 s, learn, convert to GGUF LoRA, serve. Not measured: **Qwen3.5-9B (ADR-0078's recommended base) and the 16 and 32 GB tiers**. Qwen3.5's large vocabulary made mlx-lm use 6.3 GB for a 0.8B model, so the 9B case on 16 GB may only work with Unsloth's chunked loss; measure it before promising it. Use Unsloth as the default engine and keep mlx-lm as the fallback for small Qwen3 models. |
| T3 image (mflux) | Go in principle | Z-Image trains at 9 to 12 s per step when memory is free (30 s or worse when swap is full); binding, quality and ComfyUI loading untested; captions need a trait-stripping pass. |
| T5 sorter (Laya) | Go, with a licence question | Trains and answers on the Mac through the component. `commercial_use: conditional` until Convai Innovations confirms the licence file and training data; Clef is Apache-2.0 with a full licence file, and Studio's code suggests it may run on the Mac, which should be tested before assuming "GPU only". |

## 9. Not done, or not verified

- Qwen3.5-9B and any model above 2 B: training memory and time; the 16 and 32 GB Mac tiers (only this 64 GB machine exists). A 9B QLoRA needs the bf16 weights (about 19 GB) or an MLX 4-bit copy.
- The REST routes, the diffusion trainer, AI Toolkit, rented GPUs; a no-torch install of the component; Windows or Linux.
- Laya through its own MPS script; Clef; an embeddings baseline for sorters; sorter quality on a hard dataset.
- Z-Image LoRA quality, binding, ComfyUI use; resume; Z-Image-Turbo.
- Captioning with faces of real people (none used), larger sets, other captioner models, server memory.
- Why llama-server's whole-conversation rendering differs from the training text (0 of 44).
- Other GGUF architectures; merged exports.

## 10. What the owner must do next

1. Have the AGPL section read by someone qualified (the question is the mixed headers and the in-process runner, section 1).
2. Decide whether to approve the **Qwen3.5-9B bf16 download (about 19 GB)** for a T0b run that measures 9B QLoRA memory and time with Unsloth and mlx-lm, and whether to approve the Clef-flash download (19 GB) to settle "Clef on the Mac".
3. Ask Convai Innovations (or read their GitHub `LICENSE` and data notes) about Laya's training data before `commercial_use` moves from conditional to yes.
4. Supply a rented-GPU account if the NVIDIA paths (Unsloth diffusion, AI Toolkit) should be measured.

## Reproduction

All in `~/Projects/wasifyai-spikes/t0/`: `unsloth.yaml`, `mlxlm.yaml`, `data/` (fixture and generators), `adapter_driver.py` (stop and resume), `laya_driver.py`, `laya_eval.py`, `roundtrip.py`, `gguf_test.sh`, `mlx2peft.py`, `magicword.py`, `caption.py`, `zimage/train.json`, `logs/` (every run, `runs.txt` lists wall times and lock waits). Lock waits were long (up to 5,583 s for the caption run); run times exclude them.

## Clean re-run (Z-Image, 15 steps, 2026-10-19 04:43 to 05:00)

Same recipe, one epoch. Per-step seconds read from the progress bar: **34, 34, 34, 21, 29, 36, 34, 34, 34, 62, then 12, 11, 11, 10, 19**. While 22.0 to 22.2 GB of swap was in use (checked at 04:55 and at the end of the run) steps took 21 to 62 s; the last five steps, when the stall cleared, took **10 to 12 s** (one at 19 s with a checkpoint write). Peak footprint again 39.9 GB, resident peak 9.9 GB, 962 s wall. So the only clean figure is **about 10 to 12 s per step** (9 to 10 s in the first run's good stretches), and **on this Mac with other apps open, a Z-Image run can fall to 30 s per step or worse when swap fills**. The product's start card must check free memory (ADR-0073 decision 8) and the estimate should be shown as a range. A genuinely clean run needs the machine idle; I could not get that while the other spikes and open apps (including Blender) were running.
