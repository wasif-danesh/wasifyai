# ADR-0042: Text to Speech

- **Status:** Accepted for the Kokoro slice (Indic Parler-TTS and Bengali are still Proposed)
- **Update (2026-10-18):** superseded in part by ADR-0067: the text to speech product was removed and replaced by the voice product (ADR-0066).
- **Date:** 2026-10-09

## Context

The studio's home page has a "Text to Speech" card marked Coming soon. A user types text, chooses a language
and a male or female voice, and gets speech to play and download. It is the first of three speech products
(ADR-0043 Speech to Text, ADR-0044 Lip Sync) and the one that introduces the speech runtime they share.

The whole project must be multilingual, so language coverage is the main design question, not an afterthought.
What the facts are (checked on 2026-10-09 from the model cards and repositories):

| Engine | Licence | Languages | Voices |
|---|---|---|---|
| **Kokoro-82M** (82M parameters) | Apache-2.0 | English (US and UK), Spanish, French, Hindi, Italian, Japanese, Portuguese (Brazil), Chinese | 54 presets in the catalog: US English 11 female and 9 male, UK English 4 and 4, Spanish 1 and 2, French **1 and 0**, Hindi 2 and 2, Italian 1 and 1, Japanese 4 and 1, Portuguese 1 and 2, Chinese 4 and 4 |
| **Chatterbox Multilingual** (0.5B) | MIT | 23: Arabic, Danish, German, Greek, English, Spanish, Finnish, French, Hebrew, Hindi, Italian, Japanese, Korean, Malay, Dutch, Norwegian, Polish, Portuguese, Russian, Swedish, Swahili, Turkish, Chinese | None built in: it speaks in the voice of a reference recording (zero-shot cloning) |
| **Indic Parler-TTS** (AI4Bharat and Hugging Face, about 0.94B parameters) | Apache-2.0 (the model is gated: access terms are accepted on Hugging Face and a token is needed to download it) | 21 officially: Assamese, **Bengali**, Bodo, Dogri, Gujarati, Hindi, Kannada, Konkani, Maithili, Malayalam, Manipuri, Marathi, Nepali, Odia, Sanskrit, Santali, Sindhi, Tamil, Telugu, Urdu and English; Chhattisgarhi, Kashmiri and Punjabi are reported as unofficial | The voice is described in words (gender, pitch, pace, style) and the card lists recommended named speakers per language (69 voices in total, per the card) |
| **Piper** | engine MIT; each voice has its own licence | many | many; per-voice licences must be read one by one |

No single engine gives "any language, male or female". **Kokoro does not support Bengali** (nor any Indic
language except Hindi), which the product needs, so **Indic Parler-TTS is added for Bengali and the other Indic
languages**. Kokoro has real male and female presets in 8 languages (and no male French voice); Chatterbox has 23
languages but no gender choice unless we supply reference recordings, which is voice cloning and needs recordings
we have the right to use. Languages that none of these cover (Arabic and Korean are in Chatterbox only; Russian
and German likewise) stay on the list of known gaps until an engine is added.

Speech takes seconds, not minutes, but it still runs a model, so it follows rule 6: it is a job for the media
worker, not a call from a graph node (ADR-0021). The worker already has a runner for OpenAI-compatible image
APIs (ADR-0032), so the same pattern fits speech.

## Decision

- **A new product, `wasifyai-tts`,** with its own tenancy, usage and quota, built like the image product (ADR-0036).
  Web area `/text-to-speech` (create) and `/text-to-speech/creations/{id}` (one result). The existing
  Coming-soon card and page stay until it is accepted and built.
- **A voice catalog, not a model name, is what the product and the user see.** `voices.yaml` lists voices as
  `{id, language, gender, label, engine, engine_voice}`. The form shows a language select (only languages with at
  least one voice), a **male / female** choice, and a voice select when more than one voice matches (the first
  is the default). A choice with no voice is disabled with a plain reason ("No male voice for French yet"), never
  silently replaced. Different engines serve different languages in one catalog, so coverage grows by adding
  engines, not by rewriting the product. **Language names are shown in their own script as well as in English**
  (for example বাংলা, Bengali).
- **Engines in this version.** `kokoro` for English (US and UK), Spanish, French, Hindi, Italian, Japanese,
  Portuguese and Chinese; **`indic-parler` for Bengali and the other Indic languages** (and Hindi, where the
  evaluation decides which engine sounds better). For Indic Parler-TTS a catalog voice is a short **description
  of the speaker**, filled in from the user's choice, for example "A female speaker with a clear Bengali voice,
  moderate pace, very clear audio", or a named speaker from the model card, so male and female need no
  recordings. Which description or speaker gives the best male and female voice per language is decided by
  listening, and recorded in `voices.yaml`.
- **Preset voices only in this version.** No user-supplied voice, no cloning. Cloning someone's voice is an
  impersonation risk that needs its own consent design (a separate ADR). The Chatterbox route to male and female
  voices in more languages is therefore only used with reference recordings we own or that are licensed for this
  (to be sourced if the evaluation says we need it).
- **Engines are servers that speak the OpenAI speech API, behind a new worker backend.** The worker gets an
  `openai-speech` runner (like `OpenAIImagesRunner`) that posts to `/v1/audio/speech` on the server named by the
  voice's engine, from a map `engine -> address` in the backend's settings; an admin can change the addresses
  (or point an engine at a hosted server) at `/admin/media` (ADR-0032). Two servers, both new services in compose
  and Helm (adding a service needs your approval, and accepting this ADR is that approval):
  1. **`speech` = Speaches** (MIT): one container serving Kokoro and Piper for speech and faster-whisper for
     ADR-0043. Alternative: `Kokoro-FastAPI` (Apache-2.0, Kokoro only).
  2. **`speech-indic`**, a small server of our own in `services/speech-indic/`: it loads Indic Parler-TTS once
     with the `parler-tts` library (Apache-2.0) and `transformers`, and answers `/v1/audio/speech` (the input
     text, the voice description or speaker as `voice`, a WAV back). Indic Parler-TTS is not served by Speaches,
     so this adapter is needed. The model is gated: the image is built without it, and the weights are downloaded
     at first start with a `HF_TOKEN` secret (never in the repository or the image) after the access terms are
     accepted on the model's page, a step for you. On a Mac it runs in a container on the CPU, or natively if
     the evaluation shows Apple's GPU backend works; neither is measured yet.
  A Chatterbox server can be added the same way for the languages above.
- **Graph.** `check_request` (text length, language and voice exist, quota, `text.moderate` on the text),
  `start_job`, `await_job`, `finalise`: the worker returns a WAV, the API turns it into an MP3 with the bundled
  ffmpeg (ADR-0034), writes an ID3 tag saying the speech is AI-generated, stores it at
  `{id}/speech.mp3`, writes the `speeches` row (migration 0012: id, tenant, product, user, text, language, gender,
  voice, characters, seconds, audio_key, created_at) and a usage event `speech.created` (characters, seconds).
  Text longer than the engine's comfortable length (about 400 characters; the catalog sets it per engine, and
  Indic Parler-TTS's own limit is read from the model's documentation and measured) is split at sentence ends by
  the worker and the pieces are joined, so one request is one result.
- **Limits.** Text 1 to 2000 characters (about 2 to 3 minutes of speech), 30 results per user per day, and the
  worker's `job_timeout_s`. Language is chosen by the user, never guessed from the text.
- **Safety.** The same fail-closed text guardrail as the other products, with categories for hate and
  harassment, sexual content, minors, and scripts for fraud or impersonation ("this is your bank..."): the
  `moderator` alias judges the text in any language. The output has no classifier; the MP3 tag marks it as
  AI-generated.
- **Search (ADR-0041 rule).** A result is searchable: kind `speech`, indexed text = the spoken text plus the
  language name. It needs an `IndexSource`, `caps.index_creation`, `deps.unindex`, an `ids=` filter, a card in My
  creations (a waveform picture, the first words, language and voice tags) and an evaluation row.
- **UI.** A text box with a counter and per-language example sentences, the three choices, a Generate button,
  progress while the job runs, then an audio player, Download MP3, Make another and Open in My creations. Drag,
  paste and the Enhance button are not used here.

## Evaluation before this is accepted

Like ADR-0037 and ADR-0041, the engine is chosen by measuring on the development Mac (and noted for a GPU host).
`services/api/evals/speech/` holds the corpus and the script; results are written into this ADR.

1. **Coverage:** for each target language and gender, does a voice exist, and for which engine?
2. **Intelligibility, measured:** synthesise 10 sentences per language and voice, transcribe them with Whisper
   large-v3-turbo (ADR-0043), and report the word error rate (character error rate for Chinese, Japanese and the
   Indic scripts) against the source text. It is a proxy, not a listening test, and it is **weakest for Bengali and
   the other Indic languages, where Whisper itself makes more mistakes**, so for Bengali and every Indic language
   we offer a native speaker listens to a sample of each voice and notes mispronunciations, numbers, names and
   missing words. For Bengali the listening review decides.
3. **Speed:** seconds to synthesise 10 and 60 seconds of speech on the Mac (CPU in a container) and, if
   available, on a GPU.
4. **Licences:** each voice file's licence, recorded in the catalog.

Acceptance needs Bengali and the languages the home page promises (decided with you after the coverage table),
a male and a female voice for each language we list (a gap is shown, not hidden), and an error rate that is not
worse than the engine's own English figure by a margin we state, with the table in this ADR.

## Results of the Kokoro slice (2026-10-09, development Mac, CPU in a container)

- **Built and working end to end:** the `speech` service (Speaches, Whisper with int8), the worker runner, the
  product `wasifyai-tts`, `voices.yaml` (41 voices in 7 languages), the web area and My creations with search.
  A real request takes about 7 seconds.
- **Round trip with Whisper large-v3-turbo** (five sentences per voice, numbers avoided because Whisper writes
  digits): English (US and UK), Spanish and Italian are at or near 0 to 2 percent word error; French about 2
  percent (one voice); Hindi 25 to 28 percent, which is mostly Whisper's own weakness in Devanagari, so a native
  listener must decide. The run did not finish for every language (see below), so this is a partial table.
- **Not possible with this server:** Japanese came back as empty audio and Chinese failed (the phonemiser has no
  Chinese). They were removed from the catalog, and the worker now fails a job whose audio is silent instead of
  saving it. They return with another engine.
- **Gaps:** no male French voice; Spanish and Portuguese voices are graded F by the Kokoro model card and are
  shown as limited; Bengali and the other Indic languages wait for the Indic Parler-TTS slice, which needs you to
  accept the model terms on Hugging Face, an `HF_TOKEN`, and a native Bengali listener; no `/admin/media` entry
  for the speech address yet (it is the `SPEECH_SERVERS` variable); the speed and listening checks are not done.

## Results of the Indic Parler-TTS slice (Bengali, 2026-10-09)

- **Built:** `services/speech-indic` (our adapter, `POST /v1/audio/speech`, WAV out), the `speech-indic` compose
  service on port 8101, the `indic-parler` engine and the Bengali voices Aditi (female) and Arjun (male), the two
  speakers the model card recommends. The weights (3.5 GB) download on first use with `HF_TOKEN`; the token is
  passed to that one container only.
- **Speed on the Mac (CPU, container):** 5 seconds of speech take about 28 to 30 seconds in 32-bit precision
  (about 5 times slower than real time). 16-bit precision halves the memory but is about 4 times slower again
  (122 seconds), so 32-bit is the default. A 111-character story took 66 seconds end to end. A GPU host would be
  far faster.
- **Memory:** 32-bit needs about 4.5 GB, so with the Kokoro server also running the 6 GB Podman VM runs out
  (the kernel killed the Bengali server twice). The Podman VM needs about 12 GB (the host has 64 GB); this is a
  machine setting for you to change.
- **Quality:** a native Bengali listener reviewed six samples (three sentences, a female and a male voice) on
  2026-10-09 and found all of them good, so the voices are graded B and no longer shown as limited. Whisper is
  too weak in Bengali to score them automatically, so this listening review is the acceptance check. The model
  runs at about 5 times slower than real time on a CPU.
- **Found on the way:** the daily limit counted characters instead of speeches (it refused the second request
  of a user). It now counts one per result; the characters are kept in the event's details.

## Consequences

- New: the `speech` service (Speaches) and the `speech-indic` service, the `openai-speech` backend with its engine
  map and admin entry, a `speech` media family and `speech.synthesize` capability, the product, `voices.yaml`,
  migration 0012, the web area, the library card and the index source.
- The catalog shows plainly which languages are missing; the roadmap lists them as known gaps (for example no
  male French voice with Kokoro; no Arabic, German, Russian or Korean until Chatterbox or another engine is added).
- Indic Parler-TTS is a larger model (about 0.94B parameters, against 82M for Kokoro), so it needs more memory and
  time per second of speech, and its first request after a start waits for the model to load. The page says how
  long it takes.
- The speech server image adds size and, on a Mac, runs on the CPU in a container. Kokoro is small enough for
  that; a native server is an option for larger engines.
- The shared pieces (the speech server, the worker runner, the voice catalog format and the AI-generated tag) are
  reused by ADR-0043 and ADR-0044.

## Not in this version

Voice cloning, choosing emotion or style, speed and pitch controls, SSML, long-form text with chapters, streaming
playback while it is being made, and translating the text into another language before speaking.
