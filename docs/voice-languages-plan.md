# Voice in many languages, and Bengali back (plan, 2026-11-13)

Owner, 2026-11-13: the voice screens do not support multiple languages, and Bengali must come back. This plan
covers both. It replaces the "v1 is English only" line of ADR-0066 for voice. Nothing here is built yet.

## What is true today

**The models speak more than the app lets them.** The desktop's `products/wasifyai-voice/models.yaml` is
narrower than the models themselves:

| Model | Job | What the model speaks | What the app lists |
|---|---|---|---|
| Kokoro 82M | speak | 9 languages, 54 voices (en-us, en-gb, es, fr, hi, it, ja, pt-br, zh; audio.cpp spec, eSpeak-ng) | en-us and en-gb, 28 voices |
| VoxCPM2 | speak, copy, design | 30 languages and 9 Chinese dialects (spec) | en only |
| Qwen3-TTS 0.6B / 1.7B | copy, design | 10 languages | 10 languages |
| Parakeet TDT 0.6B v3 | transcribe | 25 European languages | 25 (no Bengali, Hindi, Chinese, Japanese) |
| MeanVC2, dots-tts-edit | change voice, edit words | en, zh | en, zh |
| ACE-Step 1.5 | music | "50+ languages" | multi |

**The screens do not ask for a language**, except Dub and the Lyrics writer:

- **Speak** has no language choice. The voices are a flat list, and the box says "in any language the model
  speaks" without saying which those are.
- **Transcribe** has no language choice. Detecting the language is unsafe for Bengali: ADR-0043 measured
  Whisper calling 8 of 10 Bengali clips Hindi.
- **Voices** can be searched by language, but nothing groups or filters by it.
- **Dub** has a language list (`LANGUAGE_NAMES` in `DubbingWorkspace.tsx`) built from the models. Only Dub uses
  it.
- **Lyrics** takes a free-text language ("English").

**Bengali is gone.** It was built and checked on 2026-10-09 in the old `wd-tts-ai` product (commits 5498cbb4,
6f34a349; ADR-0042):

- **Speech:** Indic Parler-TTS with the voices Aditi (female) and Arjun (male). A native listener graded it
  good.
- **Transcription:** ADR-0043 measured IndicConformer 600M at a word error of about 0.13 on Bengali, against
  0.67 to 0.80 for every Whisper model.

Both lived only in the web's container stack; the Indic server needed about 12 GB in the Podman VM. The desktop
voice product (ADR-0066) never got them.

**The cloud side lists many languages but nothing is checked per language.** ElevenLabs v4, Gemini 3.8 Flash
TTS, MiniMax Speech 2.8 HD, Chatterbox (23 languages), Scribe v2 (90 languages) and Whisper are in the
catalogue. Which of them speak or write Bengali well is not measured.

## Aim

Every voice screen starts from the language, on the desktop and the web. A person picks বাংলা / Bengali, or
any other language, and sees only the models and voices that speak it. Where none does, the screen says so and
offers one, on this computer or in the cloud. Each language the app claims is checked with a real run.

## Stages

### L0: Checks before building (no product code)

Downloads and paid runs need the owner's yes first.

1. **Kokoro's other 26 voices on this Mac:** one sentence per voice, written back by a transcription model, to
   confirm audio.cpp's GGUF and eSpeak-ng speak each language.
2. **VoxCPM2 beyond English:** a few sentences in 5 or 6 of its 30 languages (Hindi, Spanish, French, Chinese,
   Arabic, Japanese).
3. **Indic Parler-TTS on every platform and Mac size** (owner, 2026-11-13): on PyTorch MPS on 16, 24 GB and
   bigger Macs, measuring memory, speed and first-load time, and on a CPU on Linux and Windows. If 16 GB is
   tight, make it fit (half precision, loading only while speaking, a smaller run of words at a time) rather
   than switching models. Speak Bengali and the chosen Indian languages: Hindi, Marathi, Telugu, Tamil and
   Gujarati.
4. **Bengali transcription on a 16 GB Mac:** IndicConformer 600M, with the same measurements.
5. **Bengali in the cloud** (cents per run): speak one Bengali paragraph on each keyed voice model, and
   transcribe one Bengali clip on Scribe v2 and Whisper.
6. **The owner listens to every Bengali sample and approves the quality**, as on 2026-10-09; Whisper is too
   weak in Bengali to score them automatically. For the other Indian languages, the transcription round trip is
   the first check, and the owner decides whether to find a listener.

Results go in `docs/spikes/voice-languages-l0.md`, with a table of language × model × good / weak / no.

**Done 2026-11-13**, and the owner approved the Bengali ("Bengali is good"). A real 16 GB Mac and real Linux and
Windows runs are still open.

### L1: One language list for every screen

- A shared list in `packages/ui/src/voice/languages.ts`: code, English name and own name (`bn` → "Bengali",
  "বাংলা"). It replaces `LANGUAGE_NAMES`.
- On the engine side, one helper gives the languages of a model and of each voice, from `models.yaml` and the
  cloud catalogue, so every screen reads the same answer.
- **Fonts:** Bengali text has to draw correctly in the window, the web, subtitles and the Video Builder's
  rendered text. Check the bundled fonts, and add Noto Sans Bengali where one is missing.

**Built 2026-11-13.**
- **One list:** `wasifyai_platform_sdk/languages.py` (engine) and `packages/ui/src/voice/languages.ts` (screens).
  - Both have 35 languages: the 28 Dub knew, plus Arabic, Bengali, Hindi, Marathi, Telugu, Tamil and Gujarati.
  - Each language has its own name.
  - `test_languages.py` fails if the two lists differ.
- **Helpers:** `spoken`/`spokenCodes` for a model's languages, `supports`/`speaks`, `voice_languages` and
  `voicesFor`. A voice that names a language speaks only that one; a voice that names none speaks every language
  of its model. Engine helpers are in snake_case; the window's are in camelCase.
- **Dub uses it:** `LANGUAGE_NAMES` and `dubbing.LANGUAGES` are gone. The list shows "Bengali (বাংলা)". Dub accepts
  `bn` once a model speaks it (L5).
- **Fonts:** no font was added.
  - The window and the web use the system font stack, which falls back to the system's Bengali font.
  - The Video Builder renders only on Apple-silicon Macs (its manifest). Its Chrome headless shell drew
    Bengali, with conjuncts, and the other five scripts correctly from the Mac's own fonts (Kohinoor Bangla and
    others).
  - There are no burned-in subtitles today.
  - If the Video Builder ever renders on Linux, it needs Noto fonts (a new package, so ask first).
  - A Linux desktop window depends on the system's fonts.

### L2: Speak and Audiobook start from the language

- **Language first:** the screen opens on the last language used, English the first time. The choice filters
  the models, and the model filters its voices.
- **None speaks it:** the screen says "No model on this computer speaks Bengali", with Get one and Use a cloud
  model, the same way Dub does today.
- **Voices panel:** grouped by language, with a language filter.

**Built 2026-11-13.**
- **The language field:** `packages/ui/src/voice/LanguageField.tsx` is on Text to speech and Audiobook. Audiobook
  asks for it on its first step.
  - It remembers the last language in `wasifyai.voice.language`, shared by both screens.
  - It lists languages a ready model speaks first, then every other language.
  - The language filters the models, and the model's voices.
- **When no ready model speaks the language:**
  - the screen says "No model here speaks Bengali yet.";
  - it has a Get button for each local model that would, and a Use button for each cloud one;
  - in the window, it can open the model list (its Cloud tab).
- **Picking a model** that does not speak the language switches the screen to one it speaks.
- **Voices panel:** groups are named from the shared list ("Hindi (हिन्दी)", "American English"). The search also
  finds a voice by its language. A separate language filter in the panel was left out: the screen's language
  already filters the voices.
- **Checked:** in the real window through `ui-audit.sh` (the engine on this Mac's data, the shell polyfilled):
  - English opens with Kokoro's voices;
  - the list shows Ready to speak and Other languages;
  - Bengali shows the note, and its button opens the model list;
  - Audiobook opens on the remembered Bengali.
- **Not done:** the web, and an actual speech in a language other than English (no local model lists one until L3).
- **Found:** the window's model list is not filtered by language, and cloud models appear in the screen's list
  only after one is chosen there. L3 and L5 take this up.

### L3: Fix the model data

From the L0 results:
- Kokoro gets its 9 languages and 54 voices.
- VoxCPM2 gets the languages that passed.
- Every speech and transcription model in the cloud catalogue gets a `languages` list, drawn from the
  provider's own list plus L0.

**Built 2026-11-13.**
- **Kokoro:** 7 language codes and the 40 voices this build carries (English, Spanish, French, Hindi, Italian,
  Brazilian Portuguese), each voice with its language.
- **Cloud models** (`own_keys_voice.py`): Chatterbox and its clone get Resemble AI's 23 languages, MiniMax the 25
  `language_boost` values fal.ai accepts, Whisper every language but Bengali (L0 measured it writing Bengali badly).
  Transcription models now carry their catalogue id, so their languages are known.
- **VoxCPM2** gains Spanish and Hindi, which passed L0.

### L4: Transcribe asks for the language

- A language choice. "Detect it" stays as an option, except for languages where L0 shows detection is unsafe
  (Bengali, Hindi), for which the language is always passed.
- A language the loaded model cannot write leads to the model that can.

**Built 2026-11-13.**
- **Speech to text** has the language field, with "Find it by itself" first. With it chosen, the screen says to
  choose Bengali or Hindi, because a model finding the language by itself mixes them up. A chosen language
  filters the models and is sent; none ready shows the same note as Speak.
- **The action** `speech.transcribe` takes `language`, checked against the shared list.
- **The Indic model** (L6) must be told the language; without one the engine refuses with `language_needed`.

### L5: Bengali speech

- **Indic Parler-TTS on every platform:** an optional download on the desktop (every Mac size, Linux,
  Windows) with Aditi and Arjun and the voices of the chosen Indian languages, and on the web (see "What the
  answers change").
- **Cloud:** the cloud voices that passed L0 also show under Bengali in the picker's Cloud tab, as a second
  choice.

**Built 2026-11-13.**
- **The Indian-language speech engine:** an optional part (`indic`) in every platform's manifest, installed from
  one universal hashed lock (`services/api/src/wasifyai_api/indic_server/indic.lock.txt`, made by
  `scripts/lock-indic.sh`; parler-tts's protobuf<5 is overridden and the lock is installed without
  dependencies). It runs as a sidecar on loopback like MuseTalk (`indic_runtime.py`, `indic_server/`), offline,
  and holds the `indic` slot while it works. Settings › Optional parts and the model rows' setup step install it;
  `/desktop/indic` reports it.
- **Indic Parler-TTS** in `models.yaml`: Bengali, Hindi, Marathi, Telugu, Tamil and Gujarati, two voices each
  (Tamil one): Aditi and Arjun, Divya and Rohit, Sunita and Sanjay, Lalitha and Prakash, Jaya, Neha and Yash.
  3.8 GB with its flan-t5 tokenizer. Long text is spoken sentence by sentence (the danda ends one).
- **The web:** the engine workers run the same engine (`indic-engine` in Admin › Workers, `RemoteIndic`); see the
  ADR-0099 amendment.
- **Measured on this Mac (M-series, 64 GB):** the engine installs in 45 s, 1.2 GB. The first speech with the load
  takes 13 to 18 s; after that about 4 s for 5 s of speech (speed about 0.9x real time, peak 2.9 GB).
- **Gated:** both AI4Bharat repositories need a Hugging Face token and the person's acceptance on the model page;
  without one the download says so and points to Settings › Hugging Face token.
- **Not done:** the cloud voices as a second choice under Bengali (no cloud voice passed L0 for Bengali).
- **Left out:** Intel Macs (torch 2.15 ships no build for them). Linux and Windows are in the lock and the
  manifests (sizes estimated) but were not run.

### L6: Bengali transcription

IndicConformer on the desktop if L0 shows it fits, and Scribe v2 in the cloud if it passed.

**Built 2026-11-13.**
- **IndicConformer 600M** in `models.yaml` (2.6 GB, ONNX on the CPU, CTC, 20 s windows), the same six languages,
  in the same engine. Speed about 45x real time.
- **Not done:** Scribe v2 in the cloud (it was not added to the catalogue in this plan).

### L7: Bengali through the rest of the voice product

- **Dub into Bengali:** transcribe → translate (the chat model) → speak. `dubbing.language_code` must accept
  `bn` and "বাংলা".
- **Audiobook, Lyrics, Read aloud** (in chat and notebooks).
- **Chat actions:** `voice.speak`, `transcribe` and `dub.*` take a language argument, with help pages updated.
- **Search:** the bge-m3 index already handles Bengali, so add one Bengali row to
  `services/api/evals/search/corpus.yaml`.

**Built 2026-11-13.**
- **Dub:** `dub.script` takes `source_language`, and the Dub screen asks "It is spoken in" (find it, or a
  language). A language with no ready writer is refused with `no_model_for_language`. Reading speed per language
  for the fit: bn 13, hi 12, mr 13, te 13, ta 15, gu 12 characters a second. Dubbing into Bengali uses Parler's
  built-in voices.
- **Speak, Audiobook:** `speech.speak` and `audiobook.make` take `language` and pick a model and its first voice
  in it. Audiobook splits sentences at the danda.
- **Read aloud** (chat and notebooks) finds the script of the text (`languages.script_language`: Bengali,
  Devanagari as Hindi, Telugu, Tamil, Gujarati) and reads it with a ready model and voice of that language.
- **Help pages** for the four actions name the language argument; `make contracts` regenerated.
- **Search:** a Bengali speech and a Bengali query in `services/api/evals/search/corpus.yaml`.
- **Not done:** Lyrics in Bengali (the song models were not part of this plan).

### L8: Checks that stay

- A round-trip test per claimed language (speak, then transcribe, then compare) that runs on a fake in CI and
  for real by hand.
- One Bengali walk in the real window and on the web, graded by the listener.

**Built 2026-11-13.**
- **In CI:** `services/api/tests/test_indic_runtime.py` (20 tests on a fake server: the pins, the catalogue,
  the layout, the installer, the sidecar through the engine, a check per language).
- **By hand:** `scripts/indic_round_trip.py DATA_DIR MODELS_DIR [OUT]` speaks a sentence per voice, writes it down
  and reports the word error (limit 35%). The real run: 11 of 11 voices passed; word errors 0 except Hindi Divya
  0.09, Telugu Lalitha 0.2 (a doubled letter) and Tamil Jaya 0.1. The WAVs are for the listener to grade.
- **The window:** a Bengali walk in the real window on a fresh data folder, with the real engine: Bengali chosen,
  Aditi spoke 4 s of Bengali in 16 s with the load, Speech to text with Bengali wrote a real recording back word
  for word, and the Models page shows both Indic models on this computer.
- **Not done:** the web walk; the listener's grading of the five other languages.

## Decisions (owner, 2026-11-13)

1. **Indic Parler-TTS for Bengali on every platform and every Mac memory size.** No lighter fallback model.
2. **A few popular Indian languages beside Bengali:** Hindi, Marathi, Telugu, Tamil and Gujarati (the owner can
   change the set), each shown once it passes its check.
3. **The app's own words in Bengali go on the wish list** (below). This plan covers only the content that is
   spoken and written.
4. **The owner is the Bengali listener** and approves the quality.

## What the answers change

- **The web runs Indic Parler-TTS too.** ADR-0099 says the web runs only cloud models, so this needs either an
  amendment (our own speech service on the web, as the `embedder` service runs bge-m3 for search) or a cloud
  provider that hosts Indic Parler-TTS. L0 looks for a host. Adding a service needs the owner's yes
  (CLAUDE.md, "Ask before"). An ADR-0099 amendment goes with L5.
- **16 GB Macs:** making it fit is part of the work, not a reason to drop it (L0 item 3).
- **Transcribing Bengali:** this plan keeps IndicConformer, which measured best. It needs the same choice for
  the web as speech does.

## Wish list

- The app's own words (menus, buttons, help) in Bengali.

## Not in this plan

- Copying or designing a voice in Bengali: no local model offers it. A cloud model can, if L0 finds one.
- Lip sync works in any language, so it needs nothing here.
