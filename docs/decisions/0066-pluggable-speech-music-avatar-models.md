# ADR-0066: Speech, music and lip sync run any model the person picks: descriptors, engine adapters and one dropdown

- **Status:** Accepted (2026-10-16), with the owner's answers at the end.
- **Date:** 2026-10-16
- **Depends on:** ADR-0056 (one engine, two shells), ADR-0061 (how outside code enters), ADR-0062 (engines per
  capability; rule 2 no second heavy Python environment, rule 4 single resident model), ADR-0063 and ADR-0064
  (models found on the computer, the hub), ADR-0042 to ADR-0044 (speech, transcription, lip sync on the web stack).
  Evidence: `docs/spikes/voice-investigation.md`.

## Context

The owner wants the Voice stage to be flexible: the person selects the model from a dropdown, for speech, for music
and for lip sync (MuseTalk, InfiniteTalk or another), and every feature of the reference products will come in time,
some now. Reading VoiceStudio and Unsloth Studio showed two ways to be "flexible":

- VoiceStudio writes **a class per engine** (17 speech engines, one 4,447-line file, a sidecar process for each
  engine whose dependencies conflict).
- Unsloth Studio runs **one engine (audio.cpp) and a table of model families** whose capabilities are data, but the
  table is written twice (server and client) and the client guesses from repository names.

Neither has lip sync. audio.cpp has an experimental `liveavatar` family (CUDA, 14B). Our web stack has MuseTalk as a
deployment-level choice. Weight licences differ widely: OmniVoice (VoiceStudio's default) is non-commercial.

## Decision

1. **A model is a descriptor, not code.** One entry per model in the product's `models.yaml` (the file the desktop
   already has for images and language models), extended with:
   `task` (one or more of `speak`, `clone`, `design`, `edit`, `convert`, `music`, `separate`, `transcribe`,
   `lipsync`), `engine` (adapter kind, see 2), `family`, `languages`, `voices`, `capabilities` (for example clone:
   reference text required/optional/unused; music modes with lyrics, duration bounds, edit actions; lip sync inputs:
   image or video, audio, max seconds), `options` (the request options with type, bounds, enum values),
   `hardware` (platforms, accelerators, memory floor, speed class), and `licence` (SPDX, **`commercial_use`:
   yes, conditional, no, unreviewed**, evidence URL, review date). Files stay pinned by size and SHA-256 as today.
2. **One adapter per runtime, not per model.** An adapter implements a small protocol: `available()` (with a
   reason), `ensure_ready()`, `run(task, request) -> result`, `cancel()`, `unload()`, `compute_profile()`.
   Adapters planned: `audiocpp` (the pinned prebuilt server, loopback; speech, transcription, music, conversion,
   separation), `comfyui` (as built: workflows and map files; music and video today), `sidecar` (an optional,
   separately installed environment with a local process; MuseTalk-class models), `llamacpp` (as built),
   `remote` (an OpenAI-compatible endpoint or the web stack's media worker). A new model on a runtime we have is a
   descriptor. A new runtime is an adapter and an ADR amendment.
3. **Capabilities are declared once, on the engine, and the window reads them.** `GET /desktop/models?task=speak`
   returns descriptors with their state; the window builds its dropdown and its controls from that response. No model
   or family names in TypeScript. Request options are validated on the engine against the descriptor (unknown names
   dropped, numbers clamped, enums checked), so a new model's controls need no UI change.
4. **The dropdown states are honest.** Each row is one of: *ready*, *can install* (files, sizes, source and licence
   shown, confirm required: ADR-0059/0064 rule), *needs the runtime* (one click installs the pinned component),
   *found on this computer* (ADR-0063), or *not available here* with the reason (platform, accelerator, memory).
   A licence badge is always shown; **a model whose `commercial_use` is `no` or `unreviewed` is never the
   recommended default**, and an unreviewed model needs a review entry before it enters the catalogue (CLAUDE.md
   rule 12). There is no silent fallback to another model or to the CPU.
5. **The request carries `model`.** Resolution order: the request, the person's default for that task (settings key
   `desktop.default_model.<task>`), the catalogue's recommended model, otherwise a typed error before any work.
   Graphs keep asking for capabilities (`caps.speech.synthesize(model=...)`, `caps.music.generate(model=...)`,
   `caps.video.lipsync(model=...)`), never for files (rule 4 of CLAUDE.md). Recipes record the model id and the
   options, so a result can be reproduced; they do not record file paths.
6. **One resident model.** The audio runtime is another owner of the `SlotManager`. audio.cpp is run as **one
   process** configured with `--max-loaded-models 1`, `--idle-unload-ms` and `--min-free-memory-mb`, instead of one
   process per model. Small models (the speech-to-text model, Kokoro-class text to speech) stay in the utility class
   of ADR-0056 only if measured small enough.
7. **Specs are data we ship.** The spec JSON files of the pinned audio.cpp tag (Apache-2.0) are fetched at build
   time into the component, listed in its manifest with hashes, and are the source for generated descriptors
   (options, languages, voices, tasks). Hand-written fields in a descriptor are only what the spec cannot say:
   licence, measured speed, our recommendation, the capability notes. A test fails if a pinned family has no
   descriptor decision (include, or "unsupported" with a reason).
8. **Lip sync is an ordinary task.** Input: a picture (or a video) and a voice recording or a script (a script goes
   through `speak` first). Output: a video. The first adapters are the existing MuseTalk server (as a `sidecar`
   component on Mac and CUDA) and, on CUDA hosts later, a ComfyUI workflow (InfiniteTalk) and audio.cpp's
   `liveavatar`. Each is a descriptor with its own limits; the safeguards of ADR-0044 (consent for a real person's
   picture and voice, moderation, a visible mark on the output) apply to every lip sync model, whatever it is.
9. **Music is the same shape.** Descriptors for ACE-Step (ComfyUI today, audio.cpp too), Stable Audio, HeartMuLa,
   YuE2 and others carry `modes` (song, sfx, edit), lyric rules and duration bounds, and the music form is built
   from them.
10. **Reuse.** audio.cpp and its specs: use as an engine (level A, ADR-0061). Unsloth Studio's audio code and all of
    VoiceStudio: **reference only**; nothing is copied. Ideas adopted, with credit in `PROVENANCE`-style notes:
    availability with a reason and no silent fallback, sidecar isolation, attribute-based voice design for engines
    that need it, portable voices with a consent record and a watermarked preview, licence as data, the dubbing
    stages, and the one-engine-many-families shape.
11. **Web stack.** `media_bindings` (an admin picks the backend per capability) stay. The same descriptors list the
    models a deployment *allows*; the person chooses among those. Nothing in this ADR changes the existing web
    routes until the desktop side is proven.

## Alternatives considered

- **A class per engine (VoiceStudio).** Rejected: the cost grows with every model, and the quality of each class
  depends on its author; we would own 17 integrations to offer 17 dropdown rows.
- **Copy Unsloth's family table and pages.** Rejected: AGPL-3.0, written in two places, tied to its own hub and
  gallery. We rebuild the idea on our contracts from the spec files.
- **Fixed model per task, chosen by the deployment (today's web stack).** Rejected for the desktop: the owner's
  requirement is a choice by the person.
- **Run every model as a Python library in the engine.** Rejected by ADR-0062 rule 2 (a second heavy Python
  environment, 2 GB or more, per Phase 0); allowed only as an on-demand `sidecar` component.

## Build order (each step ends with tests, a real run on the owner's Mac, docs and `git add`)

| Step | What | Evidence |
|---|---|---|
| V0 | Spike, 1 day: one audio.cpp process with `--max-loaded-models 1` switching between Kokoro, Qwen3-TTS, VoxCPM2 and Parakeet; fetch and read the spec JSON of the pin; measure load, first and warm time, memory, and whether each family runs on Metal; read the licence of each model card | numbers in `docs/spikes/` |
| V1 | The audio runtime component (pinned, SHA-256, confirm), descriptor schema and loader, `GET /desktop/models?task=`, **Speak** and **Transcribe** with the dropdown, voices, a speech engine slot; the window's Voice and Library pieces | descriptor and adapter tests, real run, self-test |
| V2 | **Design** and **Clone** with saved voices, consent record and preview; **the notebooks' audio overview gets its voices** (two hosts, two voices) | listening check, E5 gap closed |
| V3 | **Music** from descriptors (audio.cpp families beside the ComfyUI workflow), edit modes | real runs |
| V4 | **Convert**, **Separate**, **Edit** | real runs |
| V5 | **Lip sync**: `sidecar` adapter, MuseTalk component, consent and mark; CUDA adapters later | real run on this Mac, safeguards test |
| V6 | **Dubbing** (separate, transcribe with word timestamps and diarization, translate, speak per segment with duration fit, mix) and audiobook | end-to-end clip |

"Some of the tools now" means V1 and V2 in this order, unless the owner says otherwise.

## Consequences

- The cost of a new model is a descriptor, a licence review and a measured speed; the cost of a new runtime is an
  adapter.
- The licence column and the "never silently fall back" rule make some choices visible that other products hide;
  that is intended.
- audio.cpp becomes a dependency of the desktop (Apache-2.0, a native binary of about 70 MB per platform, pinned).
  Its families move quickly (the pinned tag lists about 100); the pin and the descriptor test make a bump a
  deliberate change.
- Some models will exist in the catalogue as "not available here" (CUDA-only, too large). That is correct, and
  the reason is shown.

## Not decided here

- Streaming speech (`/v1/audio/speech/live`) and live dictation; the dictation widget.
- Bengali and Hindi voices (v1 is English only); the Indic servers of the web stack stay as `remote` descriptors.
- Seed-VC (GPL-3.0) and Stable Audio (conditional licence): whether they are listed at all.
- Watermarking every generated clip (VoiceStudio uses AudioSeal): a safeguards decision, ADR-0047.

## Answers (owner, 2026-10-16)

1. **Reuse level:** reference only for VoiceStudio and Unsloth's audio code; audio.cpp is the engine.
2. **Now:** V1 (speak and transcribe), then V2 (design, clone, voices for the notebook overview). Start with the V0 spike.
3. **Licence policy:** non-commercial models may be listed, with a badge, and are **never the default or the recommendation**.
4. **Lip sync:** MuseTalk stays, as an optional download (a `sidecar` component).

## Amendments

- **V0 (2026-10-16, `docs/spikes/voice-v0.md`):** (a) a descriptor is keyed by the audio.cpp spec's **package id**, not
  the family, because one family (Qwen3-TTS) holds three kinds of model; (b) it states **how** clone and design are
  delivered (`design.via`: a server task with an option, a parenthesised prefix in the text, or an attribute list),
  because VoxCPM2 silently ignores the option the others use; (c) `memory_gb` and `sample_rate` are measured fields
  (resident memory was 2 to 5 times the file size; VoxCPM2 is 48 kHz, the others 24 kHz); (d) the adapter validates
  before sending and never relies on the server's status codes (it answers user errors with 500); (e) the Metal
  backend is "for portability and testing" by the engine's own warning, so each family is marked per platform from a
  measurement; (f) a test must show each design path changes the audio.
- **V3 (2026-10-16, `docs/phase2-voice-plan.md`):** a music descriptor states per mode what the form asks for
  (lyrics, leaving the singing out, lengths) and how the runtime takes each part of a request (the duration as a
  request field or an option; the option that carries lyrics), because the families differ; a request a model
  cannot take is refused in words. The ComfyUI adapter for the same list, and clip editing, are the next music
  steps (V3b).
- **V4 and V3b (2026-10-16, `docs/phase2-voice-plan.md`):** (a) the tasks `separate`, `convert` and `edit` (speech)
  are descriptors like the others: a `separate` block names the stems a model returns and the rate it reads, a
  `convert` block the kind of target (a recording of the voice) with its length and the request fields, a
  `speech_edit` block the style of edit (tagged words) and how many separate changes it takes; (b) every result is a
  **track** with `parent_id` and an `edit` record, so the library, search, formats and favourites need no new kind;
  (c) a voice is changed **only into a saved voice made from a recording** (it carries the consent record of
  ADR-0044), never into a file a run was handed; (d) the second engine, `comfyui`, is `ComfyMusic`: the descriptor
  names a workflow and its map file, the sidecar is the one the images use, and the model holds the **image** slot,
  so one big model is in memory at a time; (e) a model whose weights card is unclear (dots.tts Edit: "other",
  pointing at an Apache-2.0 project) is `conditional`, so it is listed but never chosen for the person.
- **V5 (2026-10-16, `docs/phase2-voice-plan.md`):** (a) a lip sync model is a `sidecar` engine: the descriptor's
  `lipsync` block gives the longest voice, the largest picture and the frame rate, and **must say `mark: required`**;
  (b) the component is installed **by the engine** (the pinned source, the hashed lock, the app's `uv`), not by the
  shell, so the shell needs no change for each sidecar; its weights are ordinary catalogue entries; (c) a request
  needs the person's word about the picture and the voice (`check_lipsync`), refused before any work, and the word is
  stored with the clip; "made here from words" is only valid for speech made here; (d) the visible mark is drawn by
  the server on every frame and cannot be switched off; (e) the sidecar is its own owner of the one memory slot.
- **V6 (2026-10-17, `docs/phase2-voice-plan.md`):** dubbing adds no model and no descriptor: it is graph tasks that
  compose the ones there are (separate, transcribe, the chat model, speak or clone, then ffmpeg). (a) It is **two
  tasks**, `dub_script` and `dub`, so the person reads and changes the translation before anything is spoken;
  (b) which models speak a language is read from the descriptors' `languages` (`multi` means all), and a language no
  ready model speaks is refused before any work; (c) copying the original speaker's voice needs the person's word that
  it is theirs or that they have permission (the consent of a saved cloned voice) and is kept with the result;
  (d) the result is a track (`mode: dubbed`, `parent_id`, the script in `edit` and, for search, in `lyrics`); (e)
  one speaker only: diarisation is not in because the one model for it (Sortformer) is CC-BY-NC.
- **V7 (2026-10-17, `docs/phase2-voice-plan.md`):** the audiobook is, like dubbing, a graph task over the speaking
  models there are, not a model. (a) The chapters are **planned by a route** (`POST /audiobook/plan`: headings, or
  size when there are none) and approved by the person before anything is spoken; (b) a chapter is cut into pieces of
  at most 700 characters at sentence ends, with a longer pause after a paragraph; (c) **each chapter is a track,
  kept as soon as it is done**, so a failure or a cancel in chapter 7 leaves 1 to 6 in Your music and says so; (d) a
  track of the whole book is optional and limited to about two hours because it is built in memory; (e) the words
  of each chapter are in the track's `lyrics`, so a book is found by what it says.
