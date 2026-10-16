# V0 spike: one audio.cpp process, several models (ADR-0066)

Date: 2026-10-16, the owner's MacBook Pro (M5 Pro, 64 GB), audio.cpp `v0.9.0-unsloth.1` (Metal), Kokoro-82M Q8_0 and
Parakeet-TDT-0.6B-v3 Q8_0 already on disk from Phase 0. Scripts: `docs/spikes/voice-v0/` (`v0.py`, `v0b.py`; they
start their own server on a free port and need no download).

## Part 1: what ran (no download)

One `audiocpp_server --config server.json --no-ui` with `"lazy_load": true`, `"max_loaded_models": 1` and two model
entries (`id`, `family`, `path`, `task`, `mode`).

| Measurement | Result |
|---|---|
| Server start, nothing loaded | 2.3 s, 85 MB resident |
| `GET /v1/models` | lists each configured model with `loaded: true/false`: the slot state is observable |
| Kokoro, first request (loads the model, compiles Metal kernels) | 4.7 s for 4.8 s of audio, 0.9 GB resident |
| Kokoro, warm | 0.56 s for 4.8 s (8.6x realtime); 503 characters in 3.3 s for 31.2 s of audio (9.3x) |
| Parakeet after Kokoro (the swap) | 1.5 s on the first request, then 0.04 s for 4.85 s of audio (about 130x); **Kokoro is unloaded** (`loaded` flags: kokoro false, parakeet true); 2.6 GB resident |
| Kokoro after Parakeet (swap back) | 3.8 s, then 0.57 s; Parakeet unloaded |
| Round trip | Kokoro said "The marketing budget for the launch is three hundred and fifty thousand dollars"; Parakeet wrote "The marketing budget for the launch is $350,000." |
| Two concurrent requests to a cold model | 3.8 s and 4.3 s: they queue, nothing fails |
| Options | `speed` 1.5 shortens 2.80 s to 1.75 s; another voice (`am_adam`) gives different audio |

### Findings that shape the adapter

1. **`max_loaded_models: 1` is our slot rule, inside the engine.** One process serves every model; the least recently
   used is unloaded on a swap. The swap costs 1.5 to 4 s for models this size (bigger models will cost more: to be
   measured in Part 2). So the audio runtime is *one* slot owner, and a model change inside it is cheap enough to hide
   behind a dropdown, but not free: the window should say "loading" on the first request after a change.
2. **The server answers every user error with HTTP 500** and a JSON message: unknown voice
   (`unknown Kokoro voice id: nope`), unknown option (`unknown Kokoro TTS request option: nonsense`), unknown model
   id, a task mismatch (`Parakeet TDT prepare() requires an audio contract` when an ASR model is asked to speak).
   Our adapter must not trust the status code. It validates against the descriptor **before** sending (ADR-0066
   decision 3), and maps the rest to a typed error.
3. **Built-in voices are not listed by the server** (`/v1/audio/voices?model=` returned an empty list; that route
   lists saved reference voices). The voice list is in the family's spec file (`ui.builtin_voices`), so shipping the
   specs (ADR-0066 decision 7) is required, not optional.
4. **Memory:** Parakeet Q8 (916 MB file) holds 2.6 GB while loaded; Kokoro (190 MB file) holds 0.9 GB. Descriptors
   need a measured `memory_gb`, not the file size.
5. The first request pays Metal pipeline compilation; a warm-up request after load hides it if wanted.

## Part 2: Qwen3-TTS and VoxCPM2 (downloaded with the owner's yes; every file's SHA-256 matched Hugging Face's)

Files, from `huggingface.co/audio-cpp/audio.cpp-gguf`: `qwen3-tts-12hz-0.6b-base-q8_0.gguf` (1,991 MB),
`qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf` (2,817 MB), `voxcpm2-q8_0.gguf` (2,955 MB); specs of tag `v0.9.0` in
`docs/spikes/voice-v0/specs/`. One server, five models configured (Kokoro, Parakeet, the three above), Metal,
`max_loaded_models: 1`. Reference voice: a Kokoro clip (so the clone check is about mechanics, not about a real
person's voice). Scripts: `v0c.py`, `v0d.py`. The clips were transcribed back by Parakeet.

| Model and use | First request (loads) | Warm | Audio rate | Resident memory while loaded | Heard back by Parakeet |
|---|---|---|---|---|---|
| Qwen3-TTS 0.6B Base, **clone** (`voice_ref` + `reference_text`) | 2.8 s | 1.1 s for 3.9 s of audio (3.5x realtime) | 24 kHz | 5.0 GB | exact |
| Qwen3-TTS 1.7B VoiceDesign, **design** (`options.instruct`, server task `vdes`) | 2.6 s | 1.5 s for 4.2 s (2.9x) | 24 kHz | 6.2 GB | exact |
| VoxCPM2, plain | 3.4 s | 2.5 s for 3.8 to 4.8 s (1.5 to 2x) | **48 kHz** | 6.5 GB | exact (one comma missing) |
| VoxCPM2, clone | | 2.5 s | 48 kHz | | exact |
| Kokoro (Part 1) | 4.7 s | 0.56 s for 4.8 s (8.6x) | 24 kHz | 0.9 GB | exact |

- **Model switches inside the one process** cost 2.1 to 3.6 s (Kokoro back: 3.6 s; Qwen design: 2.1 s; VoxCPM2: 3.3 s).
  Loading a 3 GB model is fast; the cost is mostly kernel set-up.
- **All five families run on Metal.** The server prints a warning at start: audio.cpp "is optimized for CUDA. The
  metal server backend is intended for portability and testing, but performance and model coverage may be lower than
  CUDA." So "runs on a Mac" is per family, and speed is a measurement, not a promise.
- **Voice design works, and is audible in the pitch.** Qwen: "a deep, calm, elderly man with a slow, warm British
  voice" gave a median pitch of 93 Hz; "a bright, energetic young woman speaking quickly" gave 312 Hz (a rough
  autocorrelation estimate, not a listening test). The clone came out at 222 Hz against a 205 Hz reference.
- **VoxCPM2 silently ignores `options.instruct`**: the audio was byte-identical with and without it, and the server
  returned no error (Kokoro, by contrast, rejects an unknown option with a 500). VoxCPM2 takes the design as a
  **parenthesised description in front of the text**: `"(A deep, calm elderly man with a slow British voice)Our new..."`
  gave 119 Hz, `"(A bright, energetic young woman speaking quickly)..."` gave 245 Hz, against 205 Hz plain. The same
  idea, "describe the voice", is delivered three different ways (server task `vdes` + option, text prefix, or an
  attribute list), so a descriptor must state **how** (`design.via`), and a test must prove each design path changes
  the audio. A silent ignore is the worst case for the dropdown: the person thinks the control worked.
- **Memory is 2 to 5 times the file size** (Qwen 0.6B Base Q8: a 2.0 GB file, 5.0 GB resident), so the descriptor's
  `memory_gb` must be measured (as the image models' figures are), never taken from the file.
- **Qwen3-TTS has three package kinds** (Base = clone only; CustomVoice = preset speakers; VoiceDesign = design) that
  share one `family`. The spec's `packages[].id` tells them apart (`qwen3_tts_1_7b_voicedesign_q8_0`), and the
  server task differs (`tts` or `vdes`). Unsloth guesses the kind from file names; a descriptor keyed by package id
  does not need to. A Base model with no reference answers 500 "requires voice clone reference audio": the
  descriptor's `clone.reference: required` prevents it before sending.
- The specs of Qwen3-TTS and VoxCPM2 carry **no `options` list** (Kokoro's does), so option lists for these come from
  the GGUF's embedded spec or from our descriptor. The spec does carry `tasks` (`tts`, `clone`, `design`), `languages`
  (Qwen: 10), `capabilities`, `packages` with exact file paths, `ui.recommended_package` and the download source.

## What V0 settles for ADR-0066 (amendments are in the ADR)

1. One audio.cpp process with `max_loaded_models: 1` is the right shape; swaps are 2 to 4 s.
2. Descriptors are keyed by the spec's **package id**, and carry measured `memory_gb`, `sample_rate`, speed class and
   how clone and design are delivered.
3. Validate before sending; never trust a status code, and never trust "accepted" either (VoxCPM2).
4. Weight licences read from the model cards: Qwen3-TTS (Apache-2.0), VoxCPM2 (Apache-2.0, "free for commercial use"),
   Kokoro (Apache-2.0), Parakeet (CC-BY-4.0, attribution). All four may be recommended defaults.

## Not measured

Real voice similarity of a clone (needs a person's recording and a listening check), languages other than English,
VoxCPM2 q8 versus bf16 quality, the other audio.cpp families (ACE-Step is the next one, for V3), and memory on a
16 GB Mac (all of this was on 64 GB).
