# Unsloth Phase 0: reference inventory (ADR-0061)

Date: 2026-10-15. Reference clone: `~/Projects/unsloth` at tag `v0.1.907-beta` (outside this repository, not a
remote). Method so far: **static reading of source** and read-only inspection of the owner's installed copy
(`/Applications/Unsloth.app`, data in `~/.unsloth`). Nothing here was run through the UI yet; the "runtime"
column lists what still has to be observed. Licence of `studio/`: AGPL-3.0; the `unsloth/` core library is
Apache-2.0 and unused.

## Size of what we would be importing from

| Area | Size | Note |
|---|---|---|
| Rust shell `studio/src-tauri/src` | 46k lines | process, install, update, auth, native, platform quirks |
| Backend `core/` | 365k lines (Python, no tests) | inference, diffusion, rag, training, export |
| Backend `routes/` | 86k lines | `inference.py` alone is 48k |
| Backend `hub`, `utils`, `storage`, `models` | 56k, 71k, 11k, 10k | |
| Frontend `src/features` | about 400k lines TS/TSX, 33 folders | `chat` 110k, `settings` 41k, `hub` 37k, `model-picker` 34k, `audio` 27k, `images` 13k, `video` 6k, `rag` 8k |
| Installed footprint on this Mac | 2.8 GB under `~/.unsloth` | Python env 2.1 GB, llama.cpp 224 MB, audio.cpp 69 MB, whisper.cpp 27 MB |

Conclusion: far too large to adopt wholesale; the reusable value is in a few well-bounded pieces.

## What each area actually is

| Area | Finding (source) | Reuse level (ADR-0061) |
|---|---|---|
| **GPU ownership** | `core/inference/gpu_arbiter.py` (289 lines): owners `chat`, `diffusion`, `video`; `acquire_for(owner)` evicts the current other owner under one lock; idle auto-unload (`media_keepwarm.py`) is opt-in. This is the single-resident-model rule of ADR-0056, already implemented | **C** reference, then re-implement against our slot-manager interface |
| **Image engines** | `diffusion_engine_router.py` selects one of three: **diffusers** (default on CUDA/ROCm/XPU), **native sd.cpp** (`sd-server` binary; for CPU, and MPS when enabled), **MLX via mflux** (opt-in, `UNSLOTH_DIFFUSION_MLX=1`, GGUF of declared families on Apple silicon). Env knobs exist because the Mac default was not settled upstream. FLUX.2-klein (4B, FP8) is a declared family | **A** candidate engine for the bake-off (ADR-0059); the three-engine split is a useful reference |
| **Image API** | `/api/inference/images/{status,info,load,load-progress,generate,generate-progress,generate/cancel,unload,gallery}`; generation is synchronous with a progress poll | **C**: we keep jobs plus SSE |
| **Video** | `routes/video.py` mirrors the image routes (load, generate, progress, cancel, status, unload, gallery) plus an OpenAI-style `/videos` route; same arbiter | **A** candidate engine |
| **Audio** | `audio_cpp_*` modules drive a prebuilt native `audiocpp_server` (69 MB) for TTS, music and separation GGUFs (a hub repo `audio-cpp/audio.cpp-gguf` holds many, for example Kokoro-82M); whisper.cpp for transcription | **A or B**: a native, small engine suits the desktop better than our containerised speech servers |
| **Documents (RAG)** | `core/rag`: SQLite store with **FTS5 plus sqlite-vec** (scope column, `kb_<id>` and `thread_<id>`), page-aware recursive chunking with token overlap and per-chunk page spans for highlighting, parsers on **PyMuPDF** and **python-docx**, Tesseract OCR (off by default, page-capped), a `sentence_transformers` embedder, folder sync | **B** for parsers, chunker, locators and the store schema; matches ADR-0060 |
| **Local LLM runtime** | prebuilt **llama.cpp** managed by the backend; optional vLLM and SGLang environments in their own processes (Linux NVIDIA only; "Studio never imports engine packages into its own Python process") | **A/B**: manage llama.cpp as a component; the separate-process rule is the one to copy |
| **Provisioning** | `install.sh` / `install.ps1` plus `install_*_prebuilt.py` with pinned manifests (`*_prebuilt_pins.json`) for llama.cpp, sd.cpp, whisper.cpp, audio.cpp, node, lemonade, mxc | **B**: adapt the manifest-and-pins approach |
| **Shell** | Tauri 2.12 with single-instance, deep-link, autostart, updater, process tree handling, `desktop_auth`, loopback | **B** (main reuse) |
| **Training** | LLM fine-tuning, plus `/api/train/diffusion/*` for image LoRAs | **Drop** (ours: mflux, ADR-0056 inventory) |

## Findings that change or confirm our ADRs

1. **Confirms ADR-0056 #5** (one resident model): Unsloth built a global arbiter, with eviction, a handoff lock
   and an idle unload. Our slot manager should copy its failure modes (in-flight loads, owner epoch, VRAM settle
   wait), not invent them.
2. **Confirms ADR-0060**: SQLite + FTS5 + sqlite-vec with locators is what Unsloth ships; our desktop vector
   store choice is already proven in this shape. PyMuPDF is AGPL, which the owner accepts.
3. **Changes ADR-0059**: Unsloth itself runs sd.cpp and MLX/mflux next to diffusers, so a *single* engine
   decision is the wrong frame. The bake-off should include **sd.cpp** (one native binary, no Python or torch) as
   well as the ComfyUI sidecar and the Unsloth engine.
4. **mflux is shared ground**: their MLX engine and our trainer use the same library, so LoRAs trained by our
   trainer are a first-class test for their engine.
5. **Size**: a 2 GB Python environment (torch, transformers, diffusers) is the cost of their default path. The
   native binaries (llama.cpp, sd.cpp, whisper.cpp, audio.cpp) are 27 to 224 MB each.

## Still to observe at runtime (not yet done)

The owner's installed copy has generated no images yet (`~/.unsloth/studio/images` is empty) and detected
`MLX - Apple Silicon`. To fill the last column of the matrix we need, on this Mac, for the same prompt, seed and
size and for FLUX.2 klein 4B:

| Check | How |
|---|---|
| Which image engine runs by default on this Mac | status endpoint after a load |
| Cold start, seconds per image, peak memory | one run each with diffusers/MPS, sd.cpp, MLX |
| Our mflux-trained LoRA loads and is applied | `ena` or `pipbot` adapter from the spike results |
| Cancel, progress, unload really free memory | cancel mid-run, check memory |
| Video (LTX) and TTS (Kokoro) behave on the Mac | one run each |
| RAG on a mixed PDF/DOCX set including Bengali | upload, search, check locators |

Two ways to do it, both need the owner's choice (see the note in the conversation): drive the installed app's UI
by hand, or install the reference clone in an isolated home (`UNSLOTH_STUDIO_HOME`) which downloads about 2 to 3 GB.

## Reuse matrix (draft, from source only; superseded by ADR-0062 after the runtime results below)

| Capability | Engine source | Product layer | Level |
|---|---|---|---|
| Image generate/edit | bake-off: ComfyUI sidecar, sd.cpp, Unsloth engine | ours: queue, remix lineage, catalog, LoRAs, assistant tool | A or C, by evidence |
| Video | bake-off: ComfyUI LTX (existing workflow) against Unsloth video | ours: shots, timeline later | A or C |
| Speech and music | audio.cpp and whisper.cpp binaries | ours: voice catalog, Indic engines, recorder | A or B |
| Documents | their parsers, chunker, locators, store schema | ours: collections, citations UI, authoring and export | B |
| Local LLM | llama.cpp prebuilt, managed | ours: alias router, assistant | B |
| Shell and installer | Tauri shell, manifest and pins | ours | B |

## Runtime results, image (2026-10-15, MacBook Pro M5 Pro, 64 GB)

Setup: reference clone installed in isolation (`UNSLOTH_STUDIO_HOME=~/Projects/unsloth/_home`, 4.9 GB, no
autostart or shortcuts), served on `127.0.0.1:8899`. FLUX.2 klein 4B (distilled) from the owner's ComfyUI folder,
**no model download**: the transformer, `qwen_3_4b` text encoder and the base repo's VAE (the ComfyUI-format
`flux2-vae.safetensors` was refused: it lacks `quant_conv` / `post_quant_conv`). ComfyUI 0.40.0 with the
wasifyai-art `flux2-klein-4b` workflow as the comparison. Prompt "a red ceramic teapot on a wooden table, soft
window light, photo", 1024x1024, 4 steps, guidance 1, seed 7.

| Measure | Unsloth, diffusers on MPS (default) | ComfyUI sidecar |
|---|---|---|
| Model load | 4 to 9 s (weights already warm) | included in first run |
| First image (cold) | 19.0 s | **14.1 s** |
| Warm images | 17.6, 17.7, 18.1 to 18.9 s | **9.0 and 9.2 s** |
| Speed modes (`eager`, `default`) | 18.1 to 19.4 s: no gain | n/a |
| Resident memory | its own estimate 16.0 GB (bf16), not measured here | process peak 17.6 GB |
| Cancel | clean 409, 9.5 s after the request (step boundary) | about 1 s (wasifyai-art README) |
| LoRA from `character-lora` (ai-toolkit format, `diffusion_model.*` keys) | applied at weight 1.0, 26 s | applied, 14.3 s |
| Workflows reported after load | `txt2img`, `reference`, `inpaint` | ours: text, edit, remix |
| Engine chosen | `diffusers` (single-file load requires it; sd.cpp and MLX need a GGUF) | n/a |

Findings:

1. **On this Mac, ComfyUI is about twice as fast as Unsloth's default diffusers/MPS path** for klein 4B, and
   cancels faster. The speed modes do not change that. This is a measured result, not an assumption.
2. Unsloth's value here is not the diffusers path. It is: the memory guard, the GGUF and quantised routes, the
   family catalogue (15 families), the gallery with recipe, load/unload and progress APIs.
3. **It reads our files.** A ComfyUI models folder works as a shared source (transformer plus text encoder), and
   a trained LoRA dropped into `<home>/loras/diffusion` is listed and applied, so one models folder can serve
   both engines.
4. **The memory guard is conservative and noisy**: the first load was refused ("17 GB free, 5 GB usable") with
   45 GB actually free; the retry loaded. Treat its refusals as advice, not truth.
5. The `vm_stat` approach to measuring resident memory was too noisy to report; process RSS is meaningless for
   MPS (Metal buffers). Use the engines' own estimates or `footprint` in the next round.

Not yet measured: the sd.cpp and MLX engines (need a klein GGUF, `unsloth/FLUX.2-klein-4B-GGUF`, 2.6 GB for
Q4_K_M), LTX video (the owner's `ltx-video-2b-v0.9.5.safetensors` is already local), Kokoro TTS and whisper
(small downloads), RAG with Bengali (an embedder download).

Reuse-matrix change: for **images on Mac, ComfyUI stays the first engine** (ADR-0059 holds), with Unsloth's
engine kept as a provider candidate for GGUF and low-memory machines and as the source for the gallery, recipe
and memory-guard ideas.

## Runtime results, continued (2026-10-15)

Same prompt, seed, size and steps as above (klein 4B, 1024x1024, 4 steps, seed 7), M5 Pro, 64 GB.

| Image path | Cold | Warm | Notes |
|---|---|---|---|
| ComfyUI sidecar, bf16 single file | 14.1 s | **9.0 to 9.2 s** | 17.6 GB process peak |
| Unsloth diffusers/MPS, bf16 single file (default) | 19.0 s | 17.6 to 18.9 s | speed modes: no gain |
| Unsloth diffusers/MPS, GGUF Q4_0 (dequantised on device) | n/a | 20.5 to 21.7 s | |
| Unsloth native sd.cpp on Metal, GGUF Q4_K_M | 112.5 s | 27.0 s | needs `UNSLOTH_DIFFUSION_SD_CPP_MPS=1`; applying a LoRA restarted the server (112 s again) |
| Unsloth MLX engine | not available | | `family 'flux.2-klein' has no MLX implementation`, falls back to diffusers |

Conclusions:

1. **ComfyUI is the fastest path on this Mac for klein 4B**, by about 2x over every Unsloth path. ADR-0059 holds.
2. Unsloth's sd.cpp-on-Metal route is slower than diffusers here and is off by default; its MLX route does not
   cover FLUX.2 klein. The "three engines" are a CUDA/CPU story more than a Mac one for this family.
3. The **native sd.cpp route does not accept separate text-encoder or VAE files**, so it needs its own copies
   (11 GB total for klein: GGUF 2.6, text encoder 8.0, VAE 0.3). The MLX attempt downloaded another 10.7 GB.
   Unsloth's model handling duplicates files that a shared ComfyUI folder already has; our shared-folder
   requirement is better served by ComfyUI's `extra_model_paths`.
4. **Cancel** on Unsloth stops at a step boundary (clean 409, 9.5 s). ComfyUI interrupts in about a second.
5. **An ai-toolkit-format LoRA works unchanged** in both engines (Unsloth lists it from `<home>/loras/diffusion`).

### Speech (audio.cpp, Kokoro-82M GGUF)

| Test | Result |
|---|---|
| Load incl. download | 44.8 s |
| English, 6.0 s of audio | 1.5 s first, 0.6 s warm (about 10x realtime) |
| Hindi, 6.6 s of audio | 1.0 s first, 0.7 s warm (about 10x realtime) |
| API | OpenAI-compatible `POST /api/inference/audio/speech`; model loaded with `/api/inference/load`; options include a built-in speaker list |

audio.cpp is a 69 MB native binary with no Python or torch for this path, which is the attractive part for a
desktop app; wasifyai's containerised Speaches/Kokoro (ADR-0042) gets the same engine class on the server side.
Bengali is not offered by Kokoro, as in ADR-0042.

### Video

Not measured. Unsloth's video families are MiniMax H3, LTX-2 and 2.5, Wan 2.1 and 2.2 and HunyuanVideo 1.5; the
owner's local `ltx-video-2b-v0.9.5` is an older generation and is not among them. The smallest alternative
(`Wan-AI/Wan2.1-T2V-1.3B-Diffusers`, 480p, 33 frames) is a 28.9 GB download, and there is no shared model with the
ComfyUI LTX workflow to compare against. Pending the owner's decision.

### Not measured

Speech to text (whisper) and RAG with Bengali were not run through the API: both need further model downloads
(a whisper model and a multilingual embedder) and UI-oriented endpoints. The static findings for RAG stand.

### Disk cost of this phase

The isolated install is 4.9 GB (`~/Projects/unsloth/_home`); downloaded models went to the Hugging Face cache.
`rm -rf ~/Projects/unsloth/_home` removes the install; the model files are shared in `~/.cache/huggingface`.

## Runtime results: speech to text and RAG (2026-10-15, English only)

Scope note from the owner: Bengali and Hindi are **not required in v1**; they are added after release. Everything
below is English. A synthetic sample was used, so word error rates are optimistic and are for comparing engines,
not for promising accuracy.

### Speech to text (34.6 s of Kokoro speech, a known paragraph)

| Engine and model | Load | Warm run | Speed | Word error |
|---|---|---|---|---|
| **audio.cpp, Parakeet-TDT-0.6B-v3 (GGUF)**, Metal | 6.7 s (plus a 65 s download) | **0.2 s** | about 150x realtime | 0.0% |
| Transformers, Whisper small, MPS (Unsloth default) | 6.2 s (plus a 101 s download) | 3.0 s | about 12x realtime | 0.0% |

- audio.cpp's native engine is more than 10x faster than the Python/transformers Whisper path on this Mac and
  needs no torch for this path.
- The OpenAI-compatible `/audio/transcriptions` route chooses its engine from stored settings, not from a request
  field, so the whisper.cpp (`gguf`) engine could not be addressed directly through it; whisper.cpp is available
  (the sidecar loads) but was not benchmarked. The model list per engine: transformers (Whisper tiny to large-v3),
  `mtmd` (Qwen3-ASR 0.6B and 1.7B through llama.cpp), `gguf` (whisper.cpp) and audio.cpp (Qwen3-ASR, Parakeet,
  Canary-180M-Flash, Moonshine, Nemotron streaming).

### RAG (`/api/rag`, default embedder `unsloth/bge-small-en-v1.5`)

Corpus: an 8-page PDF, a DOCX with a table, a TXT, and a scanned (image-only) PDF; ten facts and ten paraphrased
questions (little word overlap with the source sentences).

| Mode | Recall@1 | Recall@3 | Median latency |
|---|---|---|---|
| dense (vectors) | **10/10** | **10/10** | 16 ms |
| hybrid (vector + keyword, rank fusion) | 8/10 | 9/10 | 17 ms |
| lexical (FTS5) | 8/10 | 8/10 | 10 ms |

- Ingestion: PDF 8 chunks in 15.5 s including the first embedder load; DOCX and TXT about 1 s each. Chunks are
  page-aware and every hit returns filename, page and score.
- **The scanned PDF failed on purpose** with a clear message ("Could not read scanned PDF pages: 1 ... Enable OCR
  and configure Tesseract language data"); Tesseract is not installed here, as documented in `PDF_OCR.md`.
- **Hybrid fusion was worse than dense alone** on paraphrased questions: keyword hits push down the right
  chunk. That is one small corpus, but it is a warning against assuming hybrid is better; ADR-0060 should keep
  the mode configurable and choose it from the evaluation corpus, not from habit.

### What this changes

- ADR-0060: add "retrieval mode is chosen by the eval corpus (dense, hybrid, lexical)" and an OCR note: OCR needs
  Tesseract plus language data, so v1 either bundles it or declines scanned PDFs with a clear message.
- ADR-0056 reuse matrix: STT engine for the desktop is **audio.cpp (Parakeet)** with whisper.cpp as the
  fallback; TTS is audio.cpp (Kokoro).
- English-only v1 removes the multilingual embedder (`bge-m3`, 1.2 GB) from the v1 path: the small English
  `bge-small-en-v1.5` default works. The multilingual rule stays a design constraint (no English-only
  assumptions in interfaces), tested after release.

## Could sd.cpp replace ComfyUI later? Measurements (2026-10-15)

Binary: Unsloth's prebuilt `stable-diffusion.cpp master-951`, Metal, called directly (no Unsloth wrapper), M5 Pro.

| Test | ComfyUI | sd.cpp direct |
|---|---|---|
| klein 4B image, 1024x1024, 4 steps, bf16 | **9 s warm**, 14 s cold | 27 to 28 s sampling, 38 to 40 s with model load |
| klein 4B image, Q4_K_M GGUF | n/a | 22.9 s sampling, 34 s with load |
| Wan 2.2 TI2V 5B video, 640x352, 33 frames, 10 steps, fp8 text encoder | 107.6 s cold, 84.4 s warm | **crashes** (no Metal kernel for fp8 e4m3; segfault on CPU too) |
| same, fp16 UMT5 text encoder (11.4 GB, both engines) | 107.6 s cold, 88.5 s warm | sampling **58 s**, VAE decode **1,054 s**, total about 1,120 s (two runs) |
| same, with `--vae-tiling` | n/a | decode did not finish within a 20 minute cap |

Findings:

1. **Replacing ComfyUI with sd.cpp is possible behind the provider interface (ADR-0032/0059) but not
   advisable on Mac today:** images are about 3x slower, and video is unusable because of the Wan VAE decode
   (about 17 minutes). Sampling alone on video is competitive (58 s), so the problem is a single stage that may be
   fixed upstream; it should be re-measured with newer builds before any decision.
2. **sd.cpp does not read ComfyUI's fp8 text-encoder format** (`umt5_xxl_fp8_e4m3fn_scaled`); it needs fp16 or
   GGUF files, which doubles model storage when both engines are kept.
3. What a switch would involve: a provider that maps capability inputs to sd-server/sd-cli parameters, a model
   catalogue of GGUF/fp16 files, and re-validating every family; workflows, map files and `lora_chain` are
   ComfyUI-specific and would not carry over. Edit/reference modes depend on per-family sd.cpp support.
4. Keep the door open: the provider interface, not the engine, is the product contract. A `sd.cpp` provider is a
   candidate for CUDA-less Linux or Windows machines where torch MPS/CUDA is unavailable; measure there.

The two remaining VAE-option runs (`--vae-conv-direct`, and both flags) were stopped by the owner's request to
free memory; they are not recorded here.
