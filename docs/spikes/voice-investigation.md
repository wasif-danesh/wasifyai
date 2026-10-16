# Voice, music and avatar: VoiceStudio and Unsloth's audio module (investigation)

Date: 2026-10-16. Method: **static reading of source** of two reference clones
(`~/Projects/VoiceStudio` at `8e0d0ce5`, `~/Projects/unsloth` at `133a8076d`), the owner's installed audio.cpp
(`~/.unsloth/audio.cpp`, release `v0.9.0-unsloth.1`, run with `--help` and `--list-devices` only), and the upstream
audio.cpp repository and licence summary on GitHub. Nothing from VoiceStudio was run. No new model was
measured; the speed numbers quoted are the Phase 0 ones (`docs/spikes/unsloth-phase0.md`). The proposal that follows
from this is ADR-0066 (Proposed).

## 1. The short version

- **Both projects run the same engine for speech and music: audio.cpp**, a C++ (ggml) server on loopback HTTP.
  Unsloth Studio drives it for speak, clone, edit, convert, music, separate and transcribe. VoiceStudio drives it
  as one opt-in engine among 17 speech engines. audio.cpp's code is **Apache-2.0** (ShugoAI LLC, verified in the
  installed copy's `LICENSE`); its weights carry their own licences, family by family.
- **Neither product has lip sync.** In VoiceStudio "lip sync" is a timing score for dubbed speech (the word
  means "fits the source duration"). Unsloth Studio refuses InfiniteTalk and MultiTalk checkpoints by name
  (`video_families.py:925`). The one real find: **audio.cpp has a `liveavatar` family** (audio-driven avatar video
  on Wan2.2 S2V, Apache-2.0), which Unsloth lists as "unsupported", and whose spec is tagged CUDA with a 14B
  denoiser, so it is not a Mac option.
- **What the owner asked for (pick any model from a dropdown, for speech, music and lip sync) is a data problem,
  not a code problem.** The two projects solve it differently, and the difference is the main lesson:
  VoiceStudio has **one Python class per engine** (about 17 classes, 4,447 lines in `tts_backend.py` alone) plus
  subprocess sidecars for engines whose dependencies conflict; Unsloth has **one engine and a table of model
  families** with the capabilities of each declared as data (`AudioCppFamily`), and the model's own option list read
  from its spec file. Our shape should be Unsloth's, with two fixes (section 6).
- **Licences decide more than architecture.** VoiceStudio is AGPL-3.0 with a paid commercial licence and "Pro"
  features, and its default voice model (OmniVoice) was changed to **CC-BY-NC in July 2026**. Unsloth Studio is
  AGPL-3.0. Neither can be copied into our Apache-2.0 platform. We read them; we do not import them (section 7).

## 2. VoiceStudio

| | |
|---|---|
| What it is | "Open-source, fully-local ElevenLabs alternative": voice cloning, voice design, video dubbing, dictation, audiobooks; Electron app plus a FastAPI backend, 646 languages claimed |
| Licence | AGPL-3.0-only; a commercial licence for closed-source embedding and "VoiceStudio Pro features" is sold (`LICENSE-NOTICE.md`) |
| Size | 1,080 Python files, 872 TS/TSX files; backend: 42 routers, about 100 service modules, a dozen engine packages |
| Contract | `TTSBackend` ABC (`services/tts_backend.py`): `generate(text, ref_audio, ref_text, instruct, language, duration, ...) -> tensor`, `is_available()`, `ensure_ready()`, `unload()`, `sample_rate`, `supported_languages`, plus declared flags `supports_voice_design`, `supports_emotion`, `instruct_vocabulary` ("tags" or "freeform"), `gpu_compat`, `min_vram_gb`. Engines are registered lazily (`_LAZY_REGISTRY`), chosen by one env var or the Model Catalogue |

### What is worth learning from it

1. **Honest availability.** `is_available() -> (ok, reason)` and an "ready - advice" convention surface why an
   engine cannot run, with HF tokens scrubbed from the text. `engine_routing.py` turns declared `gpu_compat` and
   the host's capabilities into `accelerated / cpu_fallback / cpu_only / unavailable` with a reason, **never a
   silent fallback**. We should show the same states in our dropdown.
2. **Dependency isolation as a first-class primitive.** `SubprocessBackend`: an engine that needs its own venv
   (IndexTTS needs `transformers<5`, the app needs `>=5.3`) runs as a long-lived child process, talking
   length-prefixed JSON on stdin/stdout (64 MB frame cap, op allowlist, process-group cleanup). This is the answer
   for MuseTalk-class models, and it matches our rule "no second heavy Python environment in v1" only as an
   **optional component installed on demand**, like our document reader.
3. **Voice design is attributes, not prose, on OmniVoice.** `instruct` is a comma-separated list over closed
   categories (gender, age, pitch, style, accent, dialect); engines that take free text (Qwen3-TTS VoiceDesign,
   VoxCPM2, audio.cpp families) declare `instruct_vocabulary = "freeform"`, and clients reduce prose to tags only
   where the engine demands it. The guide you linked (voicestudio.sh/docs/guides/voice-design) describes the
   desktop workflow: pick a preset or describe observable traits, audition a fixed test line, keep the **seed** fixed
   to compare close variations, then **Save design profile** so Voice, Stories and Audiobook can use it.
4. **A saved voice is a portable file** (`.ovsvoice`: ZIP with manifest, optional reference clip, consent
   attestation, SPDX licence tag, **watermarked preview**). Verified-own-voice status is granted only if a real
   consent recording, statement and attestation are all present; plain local generation never requires it.
5. **Weight licences are data.** `config/model_licenses.json` holds, per model, `license`, `commercial_use`,
   `review_status` (`noncommercial`, `unreviewed`, ...), `evidence_url` and pinned `revision`. A test keeps it in
   step. For example `k2-fsa/OmniVoice` is CC-BY-NC plus Higgs Audio 2 plus Llama 3 terms: `commercial_use: false`.
6. **Dubbing pipeline** (the flagship; no equivalent in Unsloth): ingest, Demucs vocal/instrumental split, ASR with
   word timestamps (WhisperX) and diarization (pyannote, HF-gated), translation (engine choice), per-segment TTS
   with a duration planner and fit/speech-rate control, loudness and mix, subtitle export; a `singing` mode that
   routes sung segments to a different model; a content-hash job cache; abort that kills child processes.
7. **Operational hardening**: HF download retry with a closed-client reset, a language check enforced once in the
   base class, a "lease" so an engine is not unloaded mid-render, AudioSeal watermark, an MCP server and an
   OpenAI-compatible `/v1/audio/speech`.

### What not to copy

- The engine-per-class growth: 4,447 lines in one file, each engine a new class. Adding a model should be a row.
- Env-var selection (`OMNIVOICE_TTS_BACKEND`) as the primary switch.
- Heavy Python in-process (torch) for the default engine. Our desktop stack is native binaries (ADR-0062 rule 2).

## 3. Unsloth Studio's audio module

Licence AGPL-3.0 (`studio/`); the `unsloth/` core library (Apache-2.0) is unused (ADR-0061). The audio module is
`backend/core/inference/audio_*.py` (about 14,600 lines, of which `audio_cpp_models.py` is 2,955 and
`audio_cpp_backend.py` 1,155) and `frontend/src/features/audio` (about 8,000 lines in the top folder, 27k with its
subfolders).

### How it is built

| Piece | File | What it does |
|---|---|---|
| Runtime process | `audio_cpp_server.py` | One `audiocpp_server` child per loaded model, bound to 127.0.0.1 on an ephemeral port, started with exactly one model under a per-launch random id; readiness requires `/health` and that id in `/v1/models`. Binary found by env var, install dir, managed folder, PATH. Pinned prebuilt archives with SHA-256 (`audio_cpp_prebuilt_pins.json`, `install_audio_cpp_prebuilt.py`). |
| Model identity | `audio_cpp_models.py` | `AudioCppModel` (a repo/folder/file at one variant), `AudioCppVariant` (quantisation), package variants (several GGUFs that load together), header parsing of the GGUF to learn the family, remote header reads. |
| **Family policy** | same | `AudioCppFamily` per family: `task` (tts, music, asr, sep), `server_task`, `request_defaults`, `voices`, `unsupported` (why Studio refuses it), and optional capability records **`CloneSpec`** (reference text required/optional/unused, emotion audio, speed, instructions), **`EditSpec`** (markup, sentence or instruction style), **`ConvertSpec`** (modes, built-in voices, pitch, routes), **`SeparationSpec`**, **`MusicSpec`** with **`MusicMode`**s (song, sfx, edit: lyrics required/optional/unused, duration min/max/default, variations, edit actions, instrumental toggle). |
| Model options | `option_schema`, `validate_options` | The request options come from the runtime's `model_specs/<family>.json` (`options.request`: name, type bool/int/float/enum/string, min/max, values, default), else the spec embedded in the GGUF; a Studio-side list for families whose spec is too noisy. The server **drops unknown names, clamps numbers, checks enums**; the UI renders any option generically. |
| Workflows | `audio_workflows.py`, `workflows.ts` | Seven pages: speak, clone, edit, convert, music, separate, transcribe. `workflow_for_audio_type` and `inventory_audio_workflows` decide which workflow a model serves. |
| Requests | `audio_cpp_backend.py` | Speak and clone go to `/v1/audio/speech` (`voice_ref`, `reference_text`, `language`, `speed`, `instructions`, `options`, `seed`); edit, convert, music and separate go to `/v1/tasks/run` with a server task token (`tts`, `gen`, `asr`, `sep`, `vdes` for voice design). An option the family rejects is retried without the request's own hints (`instruct`, `language`) but never without the user's options. Cancel restarts the server. |
| Storage | `audio_gallery.py`, `audio_voices.py`, `audio_inputs.py` | Clip = `{id}.wav` + `{id}.json` recipe (the sidecar is written last and is what makes a pair a record); saved voice = 24 kHz mono WAV (at most 30 s) + JSON; inputs are named by id and resolved inside the account, so a client never names a file. |
| Device | `audio_device.py` | `auto / cpu / gpu`, so audio can leave the accelerator to a resident chat model. |

### Weaknesses to avoid

- **The capability table is written twice**: `audio_workflows.py` on the server and `workflows.ts` /
  `audio-cpp-catalog.ts` / `picker-filter.ts` in the client, with name lists such as `isCloneOnlyFamilyId`. Hub
  search rows have no backend data yet, so the client guesses by repo name. Our dropdown must read capabilities from
  the engine, once.
- **Specs are not shipped with the prebuilt.** The 69 MB bundle has no `model_specs/`, so Unsloth keeps a frozen
  list of 100 spec-family names for the pinned tag (`audio_cpp_spec_families.py`) to refuse a newer family
  up front. We must ship the spec JSON of the tag we pin (Apache-2.0 data, fetched at build time and checked in
  our component manifest).
- **Unsupported is a long list**: `minimax_h3`, `auk`, `liveavatar` and `vibeasr` ("multi-file package Studio cannot
  load yet"), forced aligners, diarization (Sortformer), VAD, music transcription, speech-to-speech
  (Apollo, AudioSR, UniverSR, PersonaPlex). Several of these are exactly what dubbing needs.
- One server process per model, restarted on cancel. audio.cpp itself offers `--max-loaded-models`,
  `--idle-unload-ms`, `--min-free-memory-mb` and `--config <server.json>` for several models in one process;
  that fits our slot manager better (section 6).

### Music

Six music families are wired: `ace_step` (song with optional lyrics, edit: repaint, extend, cover), `stable_audio`
(song and sfx up to 120 s, edit: inpaint, restyle; Stability Community Licence), `heartmula` (lyrics required),
`yue2`, `minimax_music3` (approximate duration, lyrics required), `midashenglm_gen` and `controlfoley` (sound
effects). A `MusicMode` states what the form must ask for. A real-time factor per family (`rtf`: 1 to 6) is used to
estimate time. This is the shape our music dropdown needs; our current music product runs only ACE-Step 1.5 turbo
through ComfyUI.

## 4. The engine underneath: audio.cpp (`0xShug0/audio.cpp`)

- **Code:** Apache-2.0. The installed build is `v0.9.0-unsloth.1` (Unsloth's fork, git `795c45f`, 2026-09-30),
  backends `cpu, metal` on this Mac (Apple M5 Pro found). Upstream release `v0.9.0` also ships Windows CUDA 12.4/13.3,
  Vulkan, CPU and Linux builds; both are pinned with SHA-256 in `audio_cpp_prebuilt_pins.json`.
- **API:** `GET /health`, `/v1/models`, `/v1/audio/voices`, `POST /v1/audio/speech` (also `/speech/live`,
  chunked PCM in, SSE out), `/v1/audio/transcriptions` (+ `/details`, `/live`, batches), `/v1/audio/alignments`,
  `POST /v1/tasks/run` and `/v1/tasks/batch`, and optional model install/status routes.
- **Server controls:** `--max-loaded-models`, `--idle-unload-ms`, `--min-free-memory-mb`, `--busy-timeout-ms`,
  `--model-spec-override`, `--voice-dir`, `--list-devices`.
- **Families by task** (upstream README, 2026-10-16): speech generation (Kokoro, Qwen3-TTS, VoxCPM2, Chatterbox,
  CosyVoice 3, Fish Audio, F5-TTS, VibeVoice, Higgs Audio, OmniVoice, Breeze, MOSS-TTS family, dots.tts, NeuTTS,
  Pocket-TTS, Piper, Supertonic, Kitten and others), ASR (Parakeet-TDT, Qwen3-ASR, Canary, Cohere, Moonshine,
  VibeVoice-ASR and others), VAD and wake words, diarization and alignment, music and sound (ACE-Step, HeartMuLa,
  MiniMax Music 3, Stable Audio, YuE2, MiDashengLM, ControlFoley), **voice conversion** (RVC, Seed-VC, MeanVC2,
  ToneColor, Vevo2, MioCodec), separation (HTDemucs, BS-RoFormer, MelBand-RoFormer, MossFormer2, SAM-Audio,
  TF-GridNet), restoration (Apollo, AudioSR, UniverSR, Sidon), and **video and avatar** (`liveavatar`, `minimax_h3`,
  `controlfoley`).
- **Specs:** one JSON per family in `model_specs/`: `family`, `tasks`, `modes`, `languages`, `runtime`,
  `capabilities`, `options.request/session/load`, `package_defaults`, `packages`, `ui` (`recommended_package`,
  `tags`, `builtin_voices`, `default_voice`), `sources`. This is the file a model descriptor should be generated from.
- **LiveAvatar** (`liveavatar.json`): audio-driven avatar video on Wan2.2 S2V, offline and blockwise streaming,
  inputs a reference image plus audio, 480x832, 48 frames per segment, 4 steps; package of three GGUFs
  (text/audio encoder, VAE, 14B denoiser in NVFP4+LoRA); runtime tags CUDA, GGUF, streaming; Apache-2.0;
  marked experimental. **Not usable on this Mac as published**; relevant for CUDA hosts later.

### Weight licences (audio.cpp's own summary, `docs/model_licenses.md`; a summary, to be checked per model card)

| Commercial use | Families |
|---|---|
| Yes, permissive | ace_step (MIT), chatterbox (MIT), heartmula (Apache), kokoro_tts (Apache), liveavatar (Apache), qwen3_tts (Apache), voxcpm2 (Apache), parakeet_tdt (CC-BY-4.0, attribution) |
| Conditional | stable_audio (Stability Community Licence: free under USD 1M yearly revenue, registration and "Powered by Stability AI"), rvc (base models MIT, packaged voices undocumented), seed_vc (GPL-3.0) |
| No | f5_tts (CC-BY-NC), fish_audio (research licence), omnivoice (CC-BY-NC since July 2026), Breeze-TTS-2 (research and non-commercial, per VoiceStudio's guide) |

CLAUDE.md rule 12 requires a commercial-use check **before adding any model**. The dropdown must show this column.

## 5. Where we are today

| Capability | Web stack (built) | Desktop (built) | Notes |
|---|---|---|---|
| Speak | `wasifyai-tts`: `speech.synthesize` via the `speech` provider to a Speaches server (Kokoro) and an Indic Parler server; `voices.yaml` (ADR-0042) | none | desktop TTS measured in Phase 0: Kokoro through audio.cpp about 10x realtime |
| Transcribe | `wasifyai-stt` via the same provider (ADR-0043) | none | Parakeet through audio.cpp about 150x realtime |
| Music | `wasifyai-music`: ComfyUI workflow `ace-step-1.5-turbo` | not enabled | one workflow, no model choice |
| Lip sync | `wasifyai-lipsync`: `video.lipsync` provider to `services/lipsync-musetalk` (MuseTalk v1.5, MIT; a 5 s clip in about 30 s on MPS, 11.8 GB peak). InfiniteTalk was removed (ADR-0044) | none | engine chosen by deployment, not by the user |
| Choosing a model | `media_bindings` (admin picks the backend per product and capability, ADR-0025/0032); image variants were designed (ADR-0051, withdrawn) | image: Models panel and chip | no per-request choice for speech, music or lip sync |

The shared pieces we can build on are already in the repository: per-product `models.yaml` with pinned files and
licence (`desktop_models.py`), the slot manager (`slots.py`), discovery of models other tools left on the computer
(ADR-0063), the hub (ADR-0064), component installs with confirm (the document reader), the tool host for the
assistant, and the notebooks' audio overview, which is a **script without voices** only because no desktop speech
engine exists (E5).

## 6. What the flexible design needs (summary of ADR-0066)

1. **A model is a descriptor row**, not a class: id, title, task(s), engine kind, family, files, size, memory,
   languages, voices, **capabilities** (clone needs reference text yes/no, design, edit styles, music modes,
   lip-sync inputs), **option schema**, and **licence** (SPDX, `commercial_use`, evidence URL, review status).
2. **An engine adapter per runtime, not per model**: `audiocpp` (loopback server), `comfyui` (workflows and map
   files, as built), `sidecar` (an optional venv process, for MuseTalk-class models), `llamacpp`, `remote`
   (OpenAI-compatible or the web stack). Adding a family audio.cpp already runs is a descriptor, no code.
3. **One place declares capabilities** and the window reads them from `GET /desktop/models?task=...`. No name
   lists in TypeScript.
4. **The dropdown shows state and reason** for every model: ready, can install (size shown, confirm required),
   needs the runtime, unsupported on this computer (reason), licence badge, speed class. No silent fallback.
5. **The request carries `model`.** Resolution: request, then the person's default for that task, then the
   catalogue's recommended model, else a typed error before any job. Same rule for speech, music and lip sync.
6. **Options come from the spec and are validated on the engine** (clamp, drop unknown, check enum), so a new
   model's controls appear without UI work.
7. **One resident model**: the audio runtime is another slot owner; run audio.cpp with `--max-loaded-models 1`
   and `--idle-unload-ms` rather than one process per model, and put it behind the existing `SlotManager`.

## 7. Reuse decision (for ADR-0066 and the owner)

| Source | Licence | Proposed level (ADR-0061) |
|---|---|---|
| audio.cpp runtime and `model_specs/*.json` | Apache-2.0 | **A: use as an engine**, pinned prebuilt, our own thin client |
| Unsloth `audio_cpp_*`, `audio_*`, `features/audio` | AGPL-3.0 | **C: reference only.** We write our own descriptor layer from the spec JSON and from measurements; facts about families are ours to restate, the code is not copied |
| VoiceStudio (all) | AGPL-3.0 + commercial licence | **C: reference only.** Ideas to adopt: honest availability, sidecar isolation, attribute voice design, portable consented personas, licence-as-data, dubbing stages |
| Seed-VC | GPL-3.0 | not in the default set; shown only as "conditional" until the owner decides |

Importing AGPL code into `apps/desktop` is allowed by ADR-0061, but nothing in this list is a large saving
(the engine is the value, and it is Apache-2.0), and the VoiceStudio licence model (paid commercial licence)
makes copying a business risk. Recommendation: reference only for both.

## 8. Not verified

- No VoiceStudio code was run; no claim here about its quality or speed.
- No audio.cpp family beyond Kokoro and Parakeet was run on this Mac. "Runs on Mac" for a family comes from the
  spec's runtime tags and must be confirmed per model (many are CUDA-tagged).
- Weight licences are from audio.cpp's own summary page and VoiceStudio's table, not from each model card.
- Bengali and Hindi (v1 is English only), streaming (`/speech/live`), and the quality of voice design in each
  family were not examined.
