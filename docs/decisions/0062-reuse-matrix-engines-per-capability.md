# ADR-0062: Reuse matrix: which engine and which Unsloth parts, per capability

- **Status:** Accepted (2026-10-15)
- **Date:** 2026-10-15
- **Depends on:** ADR-0056 (one engine, two shells), ADR-0059 (image engine), ADR-0060 (documents), ADR-0061
  (how Unsloth code enters). Evidence: `docs/spikes/unsloth-phase0.md`.

## Context

ADR-0061 set the method (reference clone, selective import, gates). Phase 0 has now run the reference on the owner's
Mac (MacBook Pro M5 Pro, 64 GB) and measured what can be measured. This ADR records the result as one matrix, so
each later vertical starts from a decision and a revisit trigger, not from a rediscussion. Reuse levels are the
ones in ADR-0061: **A** engine behind a provider adapter, **B** import and own, **C** reference only.

## Decision

### The matrix (desktop first, Mac; web uses the same contracts with hosted backends)

| Capability | v1 engine | Unsloth reuse | Level | Evidence (M5 Pro) | Revisit when |
|---|---|---|---|---|---|
| Image generate, edit, remix, LoRA | **ComfyUI sidecar** (ADR-0059) | gallery with restorable recipe, load/unload and progress shape, memory-guard ideas, family catalogue | **C** | klein 4B 1024x1024, 4 steps: ComfyUI 9 s warm; Unsloth diffusers 17.6 to 18.9 s; GGUF 20.5 to 21.7 s; sd.cpp 27 s | A newer sd.cpp or a CUDA-less target |
| Image engine alternatives | sd.cpp provider kept possible | none | n/a | sd.cpp direct 27 to 28 s sampling; crashes on fp8 text encoders; no MLX path for klein | sd.cpp Metal improves, or a non-torch platform |
| LoRA training | **mflux** (ADR-0054 re-opened, ADR-0056 inventory) | `/api/train/diffusion/*` shape as a reference | **C** | full timestep range binds the trigger at 150 to 300 steps with shipped defaults (wasifyai-art spike) | ai-toolkit on CUDA hosts |
| Video generate | **ComfyUI** (existing LTX workflows; Wan 2.2 5B text-to-video also runs) | route shape (load, progress, cancel, gallery), OpenAI-style `/videos` | **C** | Wan 2.2 5B 640x352, 33 frames, 10 steps: ComfyUI 85 to 108 s; sd.cpp 58 s sampling plus 17.5 min VAE decode | sd.cpp decode fixed; a Unsloth-supported family becomes our default |
| Text to speech | **audio.cpp** native binary (Kokoro) | `audio_cpp_*` modules and the prebuilt server (69 MB, no torch) | **A or B** | 6 s of audio in 0.6 to 0.7 s warm (about 10x realtime), English | Voice catalogue needs (ADR-0042) outgrow it |
| Speech to text | **audio.cpp** (Parakeet-TDT-0.6B-v3), whisper.cpp fallback | STT sidecars and registry | **A or B** | 34.6 s of audio in 0.2 s warm (about 150x), vs 3.0 s for Whisper small on transformers | Accuracy evaluation on real recordings |
| Local LLM runtime | **llama.cpp** managed; the user's Ollama as a provider (ADR-0060) | prebuilt installer and lifecycle | **B** | prebuilt Metal build installs in one step | Memory budget (ADR-0056 open question) |
| Single resident model | our slot manager | `gpu_arbiter.py` (owners, eviction under one lock, idle unload, VRAM settle wait) | **C** (then re-implement) | already built upstream with its failure modes | n/a |
| Documents: parse, OCR, chunk, store | parsers on PyMuPDF/python-docx, Tesseract, page-aware chunker, SQLite + FTS5 + sqlite-vec | `core/rag` as a unit | **B** | 8 pages to 8 chunks in 15.5 s incl. embedder load; retrieval 16 ms | Corpus evaluation, scale to 100k+ chunks |
| Retrieval mode | dense by default, chosen per eval corpus (ADR-0060) | `retrieval.py` modes | **B** | dense 10/10 at rank 1; hybrid 8/10; lexical 8/10 on paraphrased questions | Larger corpus, reranker |
| Embedder (v1, English) | `bge-small-en-v1.5` | default and GGUF companion | **B** | works as shipped | Adding Bengali and Hindi: `bge-m3` |
| Desktop shell, updater, auth handoff, tray, deep links | Tauri 2 | `src-tauri` modules | **B** | read in Phase 0; not yet built | Phase 1 |
| Provisioning (manifest and pins, prebuilt binaries, progress markers) | our component manifest | `install_*_prebuilt.py`, pins, `install.sh`/`.ps1` | **B** | the isolated install worked end to end (4.9 GB without models) | Windows and Linux CI |
| Remote UI tunnel | named tunnel or own relay (ADR-0058) | `cloudflare_tunnel.py` as a reference | **C** | quick tunnels lack SSE and are for testing | Phase 3 |
| LLM fine-tuning, GGUF export, data recipes | not built | none | **drop** | out of scope | n/a |

### Rules that follow

1. **Engines are chosen by measurement on the target machine, and the matrix changes only with new numbers**
   (ADR-0024's rule, applied to engines). Each later vertical starts with a one-day bake-off recorded here.
2. **No second heavy Python environment.** v1 ships ComfyUI's environment and the engine's own; audio.cpp,
   llama.cpp and whisper.cpp are native binaries. Unsloth's torch environment (2.1 GB) is not shipped.
3. **A shared models folder is a product requirement.** Engines that insist on their own copies (Unsloth's native
   sd.cpp route took an 8 GB encoder duplicate of a file already present) are used only when the copy is the
   cost of the capability, and the duplicate is shown to the user before downloading.
4. **Single resident model:** audio.cpp, llama.cpp and ComfyUI all go through the slot manager; small utility
   models (the English embedder, the STT/TTS binaries when idle) are the exempt class (ADR-0056).
5. **English first (v1).** The matrix is measured on English only. Languages are added by configuration and
   evaluation (embedder, voices, STT model), not by new code paths.

## Consequences

- The first vertical is image on ComfyUI with a gallery and recipe modelled on Unsloth's; the second adds the
  documents product on the imported RAG package; audio then reuses audio.cpp; video last, on ComfyUI.
- The Unsloth reference clone and its measurement scripts are no longer needed after review; the spike document
  keeps the numbers.
- Items measured only on this Mac: cold start and memory on 16 GB machines, Windows and Linux, and any CUDA
  numbers are unknown and must be measured before those platforms are promised.

## Not measured, so not decided

Unsloth's own video families (MiniMax H3, LTX-2, Wan 2.1/2.2, HunyuanVideo) through its API; the whisper.cpp engine
through the OpenAI route; RAG with scanned PDFs (needs Tesseract) and with languages other than English;
peak memory for each engine (the numbers available were process peaks or Unsloth's estimates).
