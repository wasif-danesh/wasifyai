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
effects (catalogued here; downloaded and run in "V3 finish" below).

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
- Not done in V3 (clip editing, lyrics writing and Stable Audio's real run were done in "V3 finish"): the ComfyUI
  engine for music, a longer-than-4-minute song.

## V3 finish: edits, lyrics, takes, favourites, formats, assistant, Stable Audio

Built 2026-10-16 with the owner's yes for the Stable Audio downloads (3.4 GB: music and sound effects, through the
app's own download route, sizes exact and SHA-256 checked by the download manager).

**Real runs** (audio.cpp on Metal, M5 Pro):

| Step | Result |
|---|---|
| Stable Audio 3 Small, 20 s clip | 7.5 s cold, 0.8 s warm (about 20 times real time); same seed gives identical audio |
| Stable Audio sound effect, 6 s | 2.8 s |
| ACE-Step edits | repaint 8 s, extend 13.7 s, cover 8.1 s |
| Stable Audio edits | inpaint 3.5 s, restyle 1.0 s; unmasked audio stayed about 10 times closer to the source than masked audio |
| Wrong action for a model | refused in words before anything loaded |
| Lyrics through Qwen3 4B (the chat model) | 6.3 s; a 30 s song made from those lyrics |
| ACE-Step options | `bpm` and `keyscale` change the output; `language` and invented options are silently ignored by the runtime, so the descriptor decides what is sent |

**Tests.** SDK, engine (stand-in server records the last request, checks the audio file), voice product (graph
edit/lyrics, store upgrade to version 4, routes), client 52, UI 114, desktop 44, web 280, Python 1259 passed;
ruff 0.16.10 via `uv run`, pyright 0 errors, `make contracts`, `pnpm build`, the real-window self-test (Your music
and Lyrics screens too). Search eval corpus: three more concepts for the kinds `track`, `voice` and `notebook`.

**Still open.** A listening check by the owner (sung lyrics in order; whether a cloned voice sounds like its
person); the Stable Audio licence card is gated, so its `conditional` rating rests on audio.cpp's summary; the
ComfyUI ACE-Step engine (V3b); more music models; a watermark decision.

## V4: audio tools, and V3b: music on the image engine

Built 2026-10-16 (see "Audio tools" and "Music on the image engine" in `docs/desktop-profile.md`). Downloads made with
the owner's yes ("whatever is best to run your test"), through the app's own download route, sizes exact and
SHA-256 checked: HTDemucs 4 stems (61.9 MB), HTDemucs 6 stems (42.5 MB), Mel-Band RoFormer (251.7 MB), Tone Color VC
(65.6 MB), MeanVC2 (342.4 MB), dots.tts Edit (2.96 GB), and the ACE-Step 1.5 Turbo all-in-one checkpoint for ComfyUI
(10.03 GB). The five new spec files (`products/wasifyai-voice/specs/`) are from the pinned tag v0.9.0.

**Real runs** (audio.cpp on Metal and ComfyUI on MPS, M-series Mac, through the engine's routes):

| Step | Result |
|---|---|
| Add a 48 kHz song from a file | converted to 44.1 kHz stereo, kept as a track, 0.1 s |
| HTDemucs 4 stems, 20 s song | 9.2 s warm (17.1 s cold, 9.4 s of it loading); the four stems add up to the mix within 3% |
| HTDemucs 6 stems | 10.4 s warm; stems add up within 10% (guitar and piano are the weak ones, as documented) |
| Mel-Band RoFormer | 6.7 s warm; vocals plus instrumental equal the mix exactly |
| Change a voice (pitch of the female source 203 Hz, of the male target recording 122 Hz) | Tone Color VC: output 123 Hz, 0.4 s for 5.5 s of speech; MeanVC2: output 114 Hz, 0.5 s |
| Edit speech, three edits (replace a word, delete a word, insert a word) | each result written down again by Parakeet and found to say exactly what was asked; 4.5 s warm for 5.5 s of speech, 6.5 GB of memory |
| ACE-Step 1.5 Turbo through ComfyUI | 20 s song 44.8 s cold, a 15 s song 19 to 21 s warm (about 0.7 times real time), 48 kHz stereo; the same request again came from ComfyUI's cache, identical |
| Refusals | unknown stem, unknown or description-only voice, no change in the words, no model chosen for an editing task: all in words, before a model was loaded |

**Found.**
- The separators and Tone Color VC are strict: Demucs wants 44.1 kHz (it answers a 48 kHz file with an error), Tone
  Color VC wants both files at 22.05 kHz because the prebuilt has no resampler. The graph makes a copy at the rate the
  descriptor states (`input_rate`) and removes it afterwards.
- The editing model takes the tagged words through the **speech** route, with the recording as an option; the
  runtime would also ignore a misspelt option, so the request is built from the descriptor.
- ComfyUI's ACE-Step node always sends a tempo and a key (the audio.cpp build lets the model choose), so the ComfyUI
  descriptor lists their defaults (120, C major).
- A listening check by the owner is still needed for the quality of voice conversion and of the edited speech.

**Tests.** SDK 84 (tool rules, the length checks, 7 cases of tagging changed words), engine 29 on the stand-in server
(stems in order, the rates, the fields each model reads) plus 8 for ComfyUI (workflow and options agree, states,
errors, cancel, slot), voice product 105 (graph, routes), client 56, UI 126, desktop 44; Python 1312 passed.

**Not done.** Voice conversion into built-in voices (RVC) and singing (Seed-VC is GPL-3.0, Vevo2 is non-commercial),
speech enhancement, diarisation, a longer than one hour recording, a ComfyUI music model that edits clips, and the
other V3b candidates (HeartMuLa, YuE).

## V5: lip sync (MuseTalk as an optional sidecar)

Built 2026-10-16 (see "Lip sync" in `docs/desktop-profile.md`, ADR-0044 "The desktop", ADR-0066 amendment V5). The
first real runs used the copy of MuseTalk this Mac already had (set up for the web product on 2026-10-09,
`.lipsync/musetalk`). With the owner's yes (2026-10-17) a **fresh install from the pins** was then run into an empty
app data folder: the environment (the pinned source at commit `0a89dec`, 76 hashed packages on the app's `uv` and
Python 3.12, about 2.1 GB on disk) was ready in **40 seconds** with a warm package cache, and the 11 weight files
(4.2 GB, each downloaded by the app's own download manager against its pinned size and SHA-256) took about 6
minutes.

**Real runs** (the app's own engine and routes, MuseTalk 1.5 on MPS, a public-domain painting as the face):

| Step | Result |
|---|---|
| The engine and the model listed | state "ready", commercial use yes, recommended |
| **Fresh install**: environment, then weights, then a clip | engine "managed" and installed; model "ready"; the weights linked into `src/models` and `torch/hub/checkpoints`; a 3.3 s clip from words in 109.6 s (cold: the engine and all models loaded for the first time), 300x446 H.264 and AAC with the mark comment in the file |
| No word about the picture and the voice | refused before any work (not even the speech was made) |
| 5.4 s clip from words (speech made here, then the video) | done in 32.5 s including loading the models; 300x446 H.264 and AAC, 25 fps; the "AI-generated" label on a dark plate in the bottom-left of the frame (looked at), `comment=AI-generated (lip sync, MuseTalk)` in the file |
| The clip in My creations search | found by its title (kind `lipsync`) |
| A picture with no face | "No clear face was found in the picture. Try a front-facing one." |
| A clip from a speech in the library | done; its models were loaded again (28 s) because the speech model had taken the one memory slot in between, as designed |
| 9.95 s clip from words, cold | 59.8 s of engine time (models loaded again, as above); a warm run was not measured on this pass. The server process's resident memory read 1.3 GB between runs; the GPU memory MuseTalk uses is not in that figure (11.8 GB at peak, ADR-0044) |

**Found.**
- The first real run failed: OpenCV cannot draw on the array the blending step returns (`stamp` needs its own
  contiguous, writable copy). The unit tests could not see it because they use a stand-in server; the real run did.
- The MuseTalk code reads `./models/...` relative to its folder and the face-alignment package looks in torch's cache,
  so the weights are catalogue files laid out by links when the server starts, and `TORCH_HOME` points at the
  component's own folder (nothing is fetched at run time: the face detector's two files are catalogue entries too).
- Two of the weights (`unet.pth`, the face parser) are pickles; they are trusted only because their SHA-256 is pinned.
- The language coverage and lip accuracy are **not measured** (English only, by eye); no listening or viewing check
  by the owner yet.

**Tests.** SDK 93 (lip sync rules, consent), engine 24 for the lip sync runtime (pins, what counts as installed, the
installer's steps and failures on stand-ins, the sidecar process on a stand-in server including cancel and a server
that never starts, the layout of the weights, the copy of the server files) plus 3 on the engine, voice product 120
(graph: consent before any work, speech made here, source checks, failures; routes: pictures and clips; store
upgrade to schema 5; search), client 60, UI 135, desktop 44; Python 1360 passed.

**Not done.** Another platform's install (only Apple silicon is pinned), other lip sync models
(InfiniteTalk, LivePortrait, CUDA), video input, a CUDA lock for Windows and Linux, a visible check of languages, and
the safeguards of ADR-0047 on the desktop (consent and the mark are there; a classifier and moderation are not).

## V6: dubbing

Built 2026-10-17 (see "Dubbing" in `docs/desktop-profile.md`, ADR-0066 amendment V6). No download was needed: the
models were all there (Mel-Band RoFormer, Parakeet, Qwen3-TTS 0.6B Base, Kokoro, and Qwen3 4B as the chat model).

**Real run** (the app's engine and routes; a 10.3 s English speech made with Kokoro, dubbed into Spanish in the
speaker's own copied voice, the person's word given as "own"):

| Step | Result |
|---|---|
| The script | 18.7 to 19.5 s (separating the voice and the background, writing down 4 lines with times, translating them): "Buenas noches a todos." / "Gracias por venir esta noche." / "Significa mucho para todos nosotros." / "Tenemos un espectáculo maravilloso programado, y espero que disfrutéis ..." |
| The dub | 14 to 16 s (loading the copying model included): 4 lines spoken, 3 played a little faster to fit, the largest overrun 0.16 s, a 11.9 s track at 44.1 kHz, `mode: dubbed`, voice "the original speaker", consent "own" |
| Heard back (the dub transcribed by Parakeet) | "Buenas noches a todos. Gracias por venir esta noche. Significa mucho per todos nosotros. Tenemos un spectacolo maravilloso programado." The first three lines are the translation with an accent (the copied voice is an English speaker), the last line's second half was not picked up by the transcriber; the track is as long as all four lines |
| Refusals (tests) | no word about copying the voice; no voice model for the language; no script; no stretch of one voice to copy; ffmpeg missing: each in words before the model speaks |

**Found.** The first mix cut the last line off because the mix ended at the length of the background; it now runs to
the end of the longest line (a test mixes real audio to check). The speech models speak slower in some languages
than the original: lines are sped up at most 1.3 times and any remaining overrun is reported, so a person can
shorten the line and make it again. A listening check by the owner is needed for how the dub sounds (accent, pace).

**Tests.** The pure parts (languages, script checks, time slots, the translation prompt and reading of the answer,
the voice to copy) and the mix on real ffmpeg audio (a line at its time over silence, a background kept under a line,
a line that runs past the end), and the graph on a fake engine and a scripted language model: 21 tests in all (the
mixing ones skip where there is no ffmpeg); client 63; UI 141.

**Not done.** More than one speaker, a video as the source, the speaker's tone carried into another language, the
original's non-speech sounds, and a listening check of the quality in other languages.

## V7: audiobook

Built 2026-10-17 (see "Audiobook" in `docs/desktop-profile.md`, ADR-0066 amendment V7). No download: Kokoro and
Parakeet were already here.

**Real run** (the app's engine and routes; a 530-character, three-chapter story with Markdown headings, Kokoro and
the built-in voice Heart, a whole-book track asked for):

| Step | Result |
|---|---|
| The plan | 3 chapters found at the `#` headings (253, 151 and 126 characters), 35 s estimated |
| The book | 17.1 s of work for 43.0 s of speech (the three chapters), all three kept as tracks of 19.6, 12.1 and 11.3 s at 24 kHz, plus the whole book as one track of 47.5 s (with the 1.5 s pause between chapters); 10 progress steps ("Chapter 2 of 3, part 1 of 2") |
| Heard back | Parakeet wrote down chapter 1 as "The lighthouse. The sea was black that night. ... He could not tell whether it was a ship or only the wind." |

**Found.** The estimate (15 characters a second) was 20% too fast for Kokoro with its pauses; it is 13 now. The whole
book is joined in memory (a 24 kHz track is about 170 MB an hour), so a single track is limited to about two hours
and every chapter stays its own track.

**Tests.** The chapters (headings in five styles, by size, refused texts), the pieces (sentence ends, long sentences,
Chinese) and the joining, 11; the task on a fake engine (order, titles, saved designed and cloned voices, the whole
book, refusals before anything is spoken, a failure in chapter 2 keeping chapter 1) 12 and the plan route 2; client
66; UI 148.

**Not done.** A listening check of a long read (pace and pauses over an hour), a book from a notebook's sources, and
more than one voice.

## Listening check

The quality of every voice, music, audio tool, lip sync, dubbing and audiobook feature needs ears, not tests. `docs/listening/` has a checklist (`README.md`), a page to play and rate 34 samples made by the app on 2026-10-17 (`index.html`), and the two scripts that make the samples and the page again (`scripts/listening_samples.py`, `scripts/listening_page.py`). The samples themselves are git-ignored. What the owner hears there decides the defaults (separator, voice changer, song model for non-English lyrics) and which weaknesses are fixed first.

**Result (2026-10-17):** the owner listened to the whole set and said it sounds good, with no per-sample ratings or notes. So there is no listening finding to fix; the open items below stay open until a closer check of the weak spots named in `docs/listening/README.md` (lyric order, copied-voice likeness, dubbing in other languages, long reads).
