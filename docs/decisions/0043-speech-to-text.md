# ADR-0043: Speech to Text

- **Status:** Accepted for the Whisper and IndicConformer slices (chunked search and an MLX server are still Proposed)
- **Update (2026-10-18):** superseded in part by ADR-0067: the speech to text product was removed and replaced by the voice product (ADR-0066).
- **Date:** 2026-10-09

## Context

The studio's home page has a "Speech to Text" card marked Coming soon. A user gives the product an audio or
video file, or records their voice in the browser, and gets a transcript. It is the second speech product. It
shares the speech runtime introduced by ADR-0042 and adds three things the platform does not have yet: **uploads
of audio and video**, **recording in the browser**, and **jobs that can take many minutes and are about the
user's own private words**. It also supplies what ADR-0044 (Lip Sync) needs: audio input and a way to read what
an uploaded audio says.

The project must be multilingual, so the engine must work in many languages. What was checked on 2026-10-09:

| Engine | Languages | Notes |
|---|---|---|
| **Whisper large-v3-turbo** | 99 | Cannot translate (trained without translation data); weaker on rare languages (Thai and Cantonese are the usual examples) than full large-v3 |
| **Whisper large-v3** | 99 | Slower and larger; better on rare languages; can translate to English |
| **Parakeet-tdt-0.6b-v3** | 25 European | Fast; far fewer languages |

Runtimes: **faster-whisper** is what the Speaches server uses; on an Apple-silicon Mac it runs on the CPU
only, and an informal benchmark measured it about 7 times slower than **mlx-whisper** or **whisper.cpp** with
Core ML (about 1 second against 7 for a short clip; one machine, one run, so only an indication). Whisper
decides the language by itself or takes a language hint.

## Decision

- **A new product, `wasifyai-stt`,** built like the video product (ADR-0037): a row exists from the moment a job
  starts (`status = working`), the user can leave the page, and the header badge and the "ready" notice work for
  it too (the badge, now named for "working" creations of any kind, is generalised from the video one). Web area
  `/speech-to-text` and `/speech-to-text/creations/{id}`.
- **Two ways in, one path.** *Upload*: choose, drag and drop, or paste an audio or video file. *Record*: a
  Record button uses the browser's `MediaRecorder` (level meter, pause, stop, play back, record again; it asks
  for the microphone and explains clearly when it is refused or missing; recording needs a secure page, which
  `localhost` and HTTPS are). A recording is sent exactly like an upload.
- **A secured media upload endpoint** (extends ADR-0035): `POST /products/{id}/uploads/media`, raw body, under
  the same identity rule. The file is never trusted:
  - read with a hard size cap while streaming (**100 MB**);
  - the container type is decided by its first bytes (WAV, MP3, Ogg, FLAC, MP4/M4A/MOV, WebM/Matroska), never
    by name or declared type; anything else is a 415;
  - it is decoded by the bundled ffmpeg in a child process with no network and no input paths (data comes on
    stdin), a time limit, a memory limit and `-vn -sn -dn -map_metadata -1`, producing a **16 kHz mono WAV**;
    the video track and every tag are gone, and the original bytes are not kept;
  - the decoded length is limited (**30 minutes** in this version; set from the measured speed, below), and the
    result is stored at `{tenant}/{product}/{user}/uploads/{id}.wav`;
  - the `uploads` table gains `kind` (`image` or `audio`) and `seconds` (migration 0013); the 24 hour sweep,
    "Remove deletes it" (ADR-0039) and the hourly limit (20 media uploads an hour) apply.
  The shared picture component (ADR-0039) is generalised into a file input that also takes audio and video.
- **Engine and runtime: the same OpenAI-compatible server pattern as ADR-0042.** The worker gets an
  `openai-transcription` runner posting to `/v1/audio/transcriptions`; the capability is `speech.transcribe`; an
  admin can point it at another server at `/admin/media`. Speaches (faster-whisper) is the default server, and a
  native Apple-silicon server (whisper.cpp or an MLX server) can be set as the address for the Mac, as Ollama and
  ComfyUI already are. The model is **Whisper large-v3-turbo**, with large-v3 as the alternative where the
  evaluation shows turbo is not good enough for a language.
- **Graph.** `check_request` (the upload is the caller's, language choice valid, quota), `start_job` (creates the
  row), `await_job` (progress is audio seconds done), `finalise` (stores the transcript, deletes the audio, writes
  a usage event `transcript.created` with the minutes).
- **Language.** "Detect the language" is the default (see the results: detection uses large-v3 on the first 30 seconds); the user can choose one from the list of Whisper's
  languages to fix a wrong guess. The detected language is stored and shown.
- **The result.** Text with timestamps per segment, the language and the length. Views and downloads: plain
  text, **SRT**, **VTT** and JSON. Copy to clipboard. Table `transcripts` (migration 0014: id, tenant, product,
  user, status, title, language, seconds, text, segments, error, created_at); the title is the first words of
  the transcript (the file name is ignored and never stored, like images). **The audio is deleted when the
  transcript is made** (it is private and large); keeping it with the transcript is a later option, and so is
  clicking a line to jump in the audio.
- **Quota and limits.** 120 minutes of audio per user per day (counted from usage events), one transcription
  working at a time, the upload limits above.
- **Safety and privacy.** A transcript is the user's own content, not generated content, so there is no
  moderation of what is said. Instead: access is scoped to the user in every query, transcripts and audio are
  never written to logs, and the product says what is kept. Output is plain text, shown as text (never as HTML).
- **Search (ADR-0041 rule).** A transcript is searchable: kind `transcript`, with its title, language and text.
  A transcript can be far longer than the 6000 characters the index embeds today, so the index changes: **one
  item can have several chunks** (a `chunk` column, migration 0015, unique on tenant, product, item and chunk;
  about 1500 characters per chunk, with overlap), search groups results by item and shows the best chunk, and the
  exact-word check looks at every chunk. This also benefits long lyrics. The usual `IndexSource`,
  `caps.index_creation`, `deps.unindex`, `ids=` filter, library card and evaluation row are needed.

## Evaluation before this is accepted

`services/api/evals/transcribe/` with the results written into this ADR.

1. **Accuracy per language:** word error rate (character error rate for Chinese and Japanese) on a small set
   of clips in each target language from public corpora (Common Voice, FLEURS), for turbo and for large-v3, and the language detection hit rate.
2. **Speed:** seconds of audio per second of compute (real-time factor) on the development Mac for each
   runtime (Speaches on the CPU, whisper.cpp with Core ML, MLX), and on a GPU if one is available. The upload
   length limit and the job timeout are set from this.
3. **Upload hardening:** the decoder is tried on malformed, truncated, huge-duration and mislabelled files
   (a text file named `.mp3`, a video with no audio, a zip bomb of silence) and must refuse or finish within the
   limits.

## Results of the Whisper evaluation (2026-10-09, development Mac)

Method: 100 real recordings, 10 for each of 10 languages (the first ten clips of each FLEURS test split, read
speech with a reference text; FLEURS, Conneau et al. 2022), transcribed by each model with the
language detected and with the language given. Script: `services/api/evals/transcribe/`, raw outputs in its
`results/` folder. Error is the word error rate (character error rate for Chinese and Japanese) over all the
clips of a language. This is read speech with a clean reference, so it is the **best case**: phone audio, noise
and two speakers will be worse, and a test on real recordings of that kind is still to do.

| Language | turbo, language given | large-v3, language given (5 clips) | turbo, same 5 clips | language detected: turbo | language detected: large-v3 |
|---|---|---|---|---|---|
| Bengali | **0.80** | **0.67** | 0.76 | 2 of 10 right (the rest read as Hindi) | 5 of 5 |
| Hindi | 0.29 | 0.29 | 0.33 | 7 of 10 | 4 of 5 |
| English | 0.06 | 0.05 | 0.05 | 10 of 10 | 5 of 5 |
| Spanish | 0.02 | 0.02 | 0.02 | 10 of 10 | 5 of 5 |
| French | 0.10 | 0.11 | 0.11 | 10 of 10 | 5 of 5 |
| German | 0.03 | 0.04 | 0.04 | 10 of 10 | 5 of 5 |
| Arabic | 0.19 | 0.15 | 0.15 | 10 of 10 | 5 of 5 |
| Russian | 0.03 | 0.00 | 0.00 | 10 of 10 | 5 of 5 |
| Japanese | 0.07 | 0.06 | 0.08 | 10 of 10 | 5 of 5 |
| Chinese | 0.08 | 0.04 | 0.05 | 10 of 10 | 5 of 5 |

**Speed** (seconds of compute per second of audio, 20 minutes of audio; lower is faster):

| Runtime | Real-time factor | A 30-minute upload takes |
|---|---|---|
| faster-whisper turbo, CPU in a container (Speaches) | 0.4 to 0.7 | 12 to 21 minutes |
| faster-whisper large-v3, CPU in a container | 0.7 to 1.2 (Bengali 1.3 to 2.9) | 20 to 36 minutes |
| **mlx-whisper turbo, Apple GPU** | **0.02 to 0.05 (about 30 times faster than real time)** | about 1 minute |

What this decides:

- **Turbo is the default model.** It matches large-v3 within noise for eight of the ten languages and is about twice
  as fast, so large-v3 is not offered as a second quality tier. Whisper is fine for English, Spanish, German,
  Russian, Chinese, Japanese and French (French is the weakest of those at about 10 percent), and usable for Arabic
  (about 15 to 19 percent).
- **Bengali and Hindi are weak with every Whisper model**: Bengali words come out close in sound but misspelt (word
  error 0.67 to 0.80, even with the language given), Hindi 0.29. Whisper is not a good enough engine for Bengali,
  which the project needs, so a dedicated Indic engine was evaluated (next section).
- **"Detect the language" is not safe for Bengali with turbo**: it called eight of ten Bengali clips Hindi, and a
  transcript in the wrong language is wrong throughout. large-v3 detected all of them. So detection is done by large-v3
  on the first 30 seconds of the audio (about 35 seconds on a CPU), the full transcription is then made by turbo
  with that language given, and the detected language is shown with "Wrong language? Choose it". A user who picks a
  language skips detection.
- **On a Mac the CPU container is too slow for long files; Apple's GPU is about 15 times faster.** The product talks
  to an OpenAI-compatible server by address (see the decision above), so a native Apple-silicon server (MLX) can be set as
  that address on a Mac exactly as Ollama and ComfyUI are, and a CUDA Speaches serves a GPU host. Until an MLX server is
  set up, the CPU container with turbo is the default and the 30-minute limit means a wait of up to about 20 minutes,
  which the page says. An MLX server (for example `mlx-audio`) is a small follow-up.
- **Indian languages use IndicConformer** (next section), and Whisper handles the rest.
- **Still to do from the plan:** upload hardening tests (point 3), and a test on real recordings with noise.

### IndicConformer for Bengali and the other Indian languages

IndicConformer-600M-Multilingual (AI4Bharat, 22 Indian languages: Assamese, Bengali, Bodo, Dogri,
Gujarati, Hindi, Kannada, Konkani, Kashmiri, Maithili, Malayalam, Manipuri, Marathi, Nepali, Odia, Punjabi, Sanskrit,
Santali, Sindhi, Tamil, Telugu, Urdu) was run on the same 20 Bengali and Hindi FLEURS clips, on the CPU, with the
language given. The model is gated (accept the terms on its Hugging Face page, a token is needed to download it, as
for Indic Parler-TTS). Its repository's Python file only loads the ONNX parts and a TorchScript audio preprocessor; it
was read before running.

| Language | Whisper turbo | Whisper large-v3 | **IndicConformer, CTC** | **IndicConformer, RNN-T** |
|---|---|---|---|---|
| Bengali | 0.80 | 0.67 | **0.15** | **0.13** |
| Hindi | 0.29 | 0.29 | **0.09** | **0.07** |
| Speed on the CPU (real-time factor) | 0.4 to 0.7 | 0.7 to 2.9 | **0.02** | 0.03 |

Word error against the FLEURS reference, over 10 clips per language. Bengali improves from about 0.7 to about 0.14
and Hindi from 0.29 to 0.07 to 0.09, and the model runs about 20 times faster than Whisper on the same CPU (a
30-minute file in about a minute). Two caveats: it needs the language to be given (it does not detect it), and it
was trained on short utterances, so a long file must be cut into pieces of about 30 seconds or less (the same
splitting the text-to-speech worker does for text). The other 20 languages were not scored (there are no clips of
them in this set).

What this decides:

- **A second engine, `stt-indic`**: a small server of our own in `services/stt-indic/`, like `speech-indic`, that
  loads IndicConformer once and answers `/v1/audio/transcriptions` the way the media worker expects. Speaches does
  not serve it. The product picks the engine by the language: the 22 Indian languages go to IndicConformer, every
  other language to Whisper turbo.
- **Language choice and detection**: because IndicConformer needs the language, detection (large-v3 on the first 30
  seconds, see above) runs first when the user did not choose a language; its answer routes the file. A confident
  Indic answer goes to IndicConformer. A long file is split on silence into pieces of up to about 30 seconds.
- **Bengali and Hindi are no longer "limited"** for speech to text once this is built; the other Indic languages are
  listed as "not yet scored" until clips for them are measured.
- **Not chosen: Indic-Transcribe** (`bodhan-ai/indic-transcribe-core`, 25 languages, built on NVIDIA Canary).

## What the first slice built (2026-10-09)

- **Media upload endpoint** `POST /products/{id}/uploads/media`: raw body, 100 MB cap while it streams, the type
  from the first bytes, ffmpeg in a child process (120 s and 2 GB limits where the system allows, only the `file`
  protocol, the demuxer named, no tags, one audio stream) writing a 16 kHz mono WAV, 30 minute limit, 60 uploads an
  hour, migration 0013 (`uploads.kind`, `uploads.seconds`). Hostile files are tested: a text file called `.mp3`,
  a WAV header with junk, a picture, an empty body, an over-long recording, an over-size body.
- **The product** `wasifyai-stt`: graph, `transcripts` table (migration 0014), routes (languages, list, one, download
  in text, SRT, WebVTT and JSON, delete), the daily 120 minutes from usage events, one recording at a time.
- **Worker**: `OpenAITranscriptionRunner` with detection by large-v3 on the first 30 seconds, then transcription by turbo.
- **Web**: `/speech-to-text` with upload, drag and drop, paste and the microphone recorder (level meter, pause,
  stop, play back, record again), language choice with the quality noted, the transcript page, My creations cards
  and table, search, and the top bar's "Transcribing…" badge and notice (the badge hook is now shared with video).
- **Measured end to end** on the development Mac: a 10.6 second English clip in 18 seconds including loading, a
  16 second Bengali clip detected as Bengali (the text is poor: Whisper) in 46 seconds.

Not built yet: chunked search (the first 6000 characters of a transcript are indexed), a native MLX server and the
multi-minute noisy-recording test.

## What the second slice built: the Indian-languages engine (2026-10-09)

- **`services/stt-indic`**: a small server of our own on IndicConformer-600M, answering `POST
  /v1/audio/transcriptions` for short 16 kHz mono pieces (up to 40 seconds) with the language given. It uses only the
  CTC decoder and does **not** run the model repository's Python code: the few lines that load the ONNX parts and decode
  are in the server, so only model files come from the Hub, at one pinned revision (`2a77d30`, changed on purpose).
  The model is gated: `HF_TOKEN` is passed to that one container, and the files (about 2.5 GB, 6 minutes the first
  time) go to a volume. On the CPU it takes 0.7 seconds for 14 seconds of audio and holds about 2.7 GB.
- **Routing** (in the media worker): the language is chosen, or found by large-v3 on the first 30 seconds; if it is one
  of the 22 the product lists (`indic_languages`) and the server is configured (`indic-stt=` in `SPEECH_SERVERS`),
  the work goes there; everything else, and any Indian language when that server is not running, stays on Whisper.
- **Long recordings**: the worker cuts the recording at its quietest moments into pieces of 4 to 15 seconds (tested:
  the cuts fall inside the pauses, nothing is lost between pieces), sends each piece, and every piece becomes one
  timed segment, so the subtitles are line-sized.
- **Catalog**: the 12 Indian languages that Whisper does not know (Assamese, Nepali, Odia, Sanskrit, Sindhi, Kashmiri,
  Maithili, Dogri, Bodo, Konkani, Manipuri, Santali) are offered (51 in all). They cannot be detected by Whisper, so the
  user chooses them; they are listed as "unrated" until measured. Bengali is now "fair" (0.13 to 0.15 word error) and
  Hindi "good" (0.07 to 0.09).
- **Measured end to end through the real API** on the development Mac: a 16 second Bengali clip, language detected
  as Bengali, transcribed almost word for word in 43 seconds (30 of them are the large-v3 language check); a 14 second Hindi clip in 14 seconds. Choosing
  the language skips the check.
- Helm: `sttIndic.enabled` adds the deployment and the `indic-stt` address; CI builds and pushes both Indic images.

## Consequences

- New: the media upload endpoint and decoder, the recorder and the generalised file input, the `openai-transcription`
  runner and `speech.transcribe` capability, the product, three migrations (0013 uploads, 0014 transcripts, 0015
  index chunks), the generalised "working" badge, the library card and the index changes.
- ADR-0044 can use the audio upload, the recorder and the transcription (to moderate what an uploaded voice says).
- Speed on a Mac decides the maximum length offered; a longer limit is honest only after it is measured.
- Whisper's quality varies by language; the evaluation table is part of the product's documentation, and a
  language that does not reach the stated error rate is listed as limited, not hidden.

## Not in this version

Telling speakers apart, translating, live transcription while speaking, editing a transcript, summaries, keeping
the audio, and words in a language Whisper does not cover.
