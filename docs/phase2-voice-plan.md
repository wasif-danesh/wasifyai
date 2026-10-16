# Phase 2, Voice stage: plan (ADR-0066)

Accepted 2026-10-16. Steps V0 to V6 are in the ADR; this file records what each step builds and its evidence.
V0 evidence: `docs/spikes/voice-v0.md`.

## V1: the audio runtime, descriptors, Speak and Transcribe

Layers (ADR-0066 decisions 1 to 7):

| Piece | Where | Notes |
|---|---|---|
| Descriptor types, parsing, request validation, the engine protocol | `packages/platform-sdk/.../voice_models.py` | pure code; products reach the engine through `caps.extras["app_state"].audio`, as notebooks reach their library |
| Catalogue | `products/wasifyai-voice/models.yaml` | the files (folder `audio`, pinned by commit, size and SHA-256) are the existing download entries; a `voice:` block is the descriptor; `GET /desktop/models?task=speak` filters |
| Spec data | `products/wasifyai-voice/specs/` | the `v0.9.0` spec JSON of each listed family (Apache-2.0); the descriptors' voices and options are checked against them by a test |
| Runtime install | `wasifyai_api/audio_runtime.py` | pinned prebuilt (tag `v0.9.0-unsloth.1`, the build measured in V0), per platform, size and SHA-256 shown and confirmed before download; found-on-this-computer builds (`WASIFYAI_AUDIOCPP`, `~/.unsloth/audio.cpp`) are used without installing |
| Server | same | one `audiocpp_server` for every ready model, `lazy_load`, `max_loaded_models: 1`, loopback, a slot owner (`audio`) |
| Product | `products/wasifyai-voice` | `voice.db` (speeches, transcripts), files under `<data>/voice/`, graphs `speak` and `transcribe`, routes, My creations index (`speech`, `transcript`) |
| Window | `packages/ui/src/voice/`, `apps/desktop` | Voice menu: Text to speech, Speech to text; a model dropdown built from descriptors; setup card |

V1 models: Kokoro 82M (speak, recommended), VoxCPM2 (speak, plain), Parakeet TDT 0.6B v3 (transcribe, recommended).
Design and clone are V2 (their descriptors are declared now so the schema is proven, not exposed).

Rules carried from the ADR: validate before sending; unknown options are refused, never ignored; a model whose
`commercial_use` is not `yes` is never the default; no silent fallback to another model.

### V1 evidence (2026-10-16, the owner's Mac)

**Built.** The SDK descriptor types and checks (27 tests), the runtime installer, server and engine (17 tests on a
stand-in server, including install with a bad hash and an unsafe archive, restart when the set of models changes,
cancel, the slot), the product (31 tests: catalogue against the specs, the graph, the routes, search, exports), the
client (5 tests), the screens (12 tests) and the window pages. Python 1153 passed, UI 91, client 46, desktop 44;
ruff, pyright, typecheck, `pnpm build`, the real-window self-test (the two speech screens list their models).

**Real run** (the real audio.cpp, the real models, through the engine's HTTP routes):

| Step | Result |
|---|---|
| Before the runtime | both speak models "needs the runtime"; the plan shows 42 MB (darwin-arm64, measured) and the copy found at `~/.unsloth/audio.cpp` |
| Use the found copy | accepted (same tag, same binary hash) |
| Kokoro, first request | 6.1 s for 4.85 s of speech (3.6 s of it loading the model) |
| Kokoro, warm | 0.7 s for 2.3 s |
| VoxCPM2 (swap, 48 kHz) | 3.2 s for 4.6 s |
| A wrong voice, a wrong option | refused in words before the runtime was asked |
| Parakeet on the speech it was given | 0.5 s; "The marketing budget for the launch is $350,000."; export to text, SubRip and WebVTT |
| An .m4a | converted with `afconvert` and transcribed identically |

**Found while building.**
- The runtime joins words it normalises ("is$350,000."), so subtitle text is cut from the full text when the words
  add up to the same letters.
- The server accepts only WAV for transcription (mp3 and m4a get a 400): conversion is ours.
- Same seed gives the same speech; a different seed does not.
- Not done in V1: the real installer download (tested with a local archive and a hash check; the found copy was used
  instead), Windows and Linux (pinned, not measured), streaming, long recordings as background jobs, voices by
  language beyond English, design and clone (V2).

## V2: design, clone, saved voices and the overview's voices

Built 2026-10-16. New models in the catalogue: Qwen3-TTS 0.6B Base (clone, recommended) and 1.7B VoiceDesign
(design, recommended), both Apache-2.0, and VoxCPM2 now declares clone and design. See "Your voices and the
audio overview" in `docs/desktop-profile.md` for what each piece does.

**Tests.** SDK 43 (rules, `check_clone`, `check_design`), engine 19 on the stand-in server (the description goes
as an option for Qwen and as a bracketed prefix for VoxCPM2, the recording path and its words reach the runtime),
voice product 57 (graph with saved voices, routes with consent, the store upgrade from version 1, search of
voices, the recording cut), notebooks 129 (the overview, the route sweep with three new routes), client 47,
UI 99. Python 1195 passed, ruff, pyright, typecheck, `pnpm build`, the real-window self-test (the Voices screen too).

**Real run** (real audio.cpp, the real models, a Kokoro clip as the reference so the check is about the mechanism,
not about a person's voice; each output was read back by Parakeet):

| Step | Result |
|---|---|
| Described voice "a deep, calm, elderly man with a slow, warm British voice", Qwen3-TTS | 5.5 s (first, loads the model), median pitch **87 Hz**, read back exactly |
| Described voice "a bright, energetic young woman speaking quickly", Qwen3-TTS | 2.0 s, **320 Hz** |
| The man's description through VoxCPM2 | 3.3 s, 105 Hz, read back exactly |
| Clone refused without a consent answer | 422 `consent_required`, nothing saved |
| Clone of a 4.8 s reference (pitch 185 Hz), Qwen3-TTS 0.6B Base | 2.8 s, **187 Hz**; read back "chips" for "ships" (one word) |
| The same voice through VoxCPM2 | 3.5 s, 213 Hz, read back exactly |
| Clone saved without the words, default model | refused in words before the runtime was asked ("needs the words spoken in the recording") |
| Audio overview, 6 turns, Kokoro (a woman and a man) | 7.6 s for the whole conversation, 1.1 MB WAV; read back word for word |

**Found while building.**
- A voice is a recipe, not a model's file, so one cloned recording can be spoken by Qwen3 and by VoxCPM2; what
  differs is what each needs (Qwen needs the words in the recording, VoxCPM2 does not), and that is checked
  before anything loads.
- The pitch of a described voice follows the description clearly on both models; whether a *clone sounds like the
  person* needs a listening check with a real recording, which was not done.
- Not done in V2: recording from the microphone, hosts of the overview in saved voices, watermarking output,
  design or clone for languages other than English (the models list more; v1 is English only), voices for the
  assistant.

## V3: music

Built 2026-10-16 (see "Music" in `docs/desktop-profile.md`). New models: ACE-Step 1.5 Turbo Q8_0 (6.19 GB, MIT,
downloaded with the owner's yes and checked against Hugging Face's SHA-256), Stable Audio 3 Small music and sound
effects (catalogued, **not downloaded or run**: the owner chose to skip them; their request shape follows the
spec and the shared code, but it is untested against the real model).

**Tests.** SDK 52 (music rules and checks), engine 22 on the stand-in server (how the request is built for each
family; raw and JSON answers; friendly failures), voice product 69 (music graph, `/tracks`, the store's upgrade
to version 3, search), client 49, UI 104. Python 1223 passed, ruff, pyright, typecheck, `pnpm build`, the
real-window self-test (the Music screen too).

**Real run** (real audio.cpp on Metal, ACE-Step 1.5 Turbo Q8_0, through the engine's routes):

| Step | Result |
|---|---|
| 20 s song with lyrics, first request | 20.9 s, 48 kHz stereo WAV of exactly 20.0 s; about 4 s of it loading the model |
| The same request again (same seed) | 16.6 s, **byte-identical** audio |
| 60 s song, first request | 37.5 s (about 1.6 times faster than real time) |
| 20 s instrumental ("No singing") | 11.3 s |
| Memory while loaded | 3.0 to 3.1 GB for a 6.2 GB file |
| Refusals | description too short; "sfx" on a song-only model; both in words, before anything loaded |
| Comparison | the web product's note for the ComfyUI workflow says about 77 s for a 60 s song on this Mac: audio.cpp took 37.5 s (different days, not a controlled comparison) |

**Found.**
- Whether the lyrics are sung in order cannot be checked by machine: Parakeet heard "Nine shy fun someone
  watching" from a sung verse. A listening check is the only test, and it was not done.
- The runtime's default seed is fixed, so without a chosen seed every request would repeat; the engine now picks
  one and stores it with the track, which is also what makes "make it again" possible.
- The server's spec files for ACE-Step and Stable Audio list no request options, so the request shape comes from
  our descriptor, not from the runtime.
- Not done in V3: clip editing, the ComfyUI engine for music, lyrics writing, a longer-than-4-minute song, Stable
  Audio's real run.

