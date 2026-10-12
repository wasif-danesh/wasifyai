# wasifyai-stt

Status: **working** (Whisper and the Indian-languages engine) ([ADR-0043](../../docs/decisions/0043-speech-to-text.md)).

A signed-in user uploads an audio or video file (or records with the microphone) and gets a transcript with
timestamps, as text, SRT, WebVTT or JSON. It is saved in My creations and is searchable by its words.

## Flow

1. **Upload.** The browser sends the file to `POST /products/wasifyai-stt/uploads/media` (raw body, up to 100 MB).
   The API decides what it is from its first bytes (WAV, MP3, Ogg, FLAC, MP4/M4A/MOV, WebM/Matroska; a text file
   named `.mp3` is a 415), decodes it with ffmpeg in a child process (time and memory limits, only the `file`
   protocol, the demuxer fixed by the sniffed type) into a **16 kHz mono WAV** with no video, subtitles or tags,
   refuses over 30 minutes, and stores only that clean copy under the user's `uploads/` prefix. The original
   bytes are never kept.
2. **Run.** `check_request` (the recording is the caller's and is audio, the language is known, one recording at
   a time, the daily 120 minutes) -> `start_job` (creates the row, status `working`, and a `speech.transcribe`
   job) -> `await_job` -> `finalise` (words, language and timed segments saved, the recording deleted, a usage
   event of the minutes, the search index).
3. **Worker.** The media worker's `OpenAITranscriptionRunner` posts the WAV to a speech server. With no
   language chosen it first sends the first 30 seconds to Whisper large-v3 only to find the language (turbo
   mistakes Bengali for Hindi). For the 22 Indian languages in `languages.yaml` it then cuts the recording
   at its quietest moments into pieces of up to 15 seconds and sends them to **`stt-indic`** (IndicConformer,
   `indic-stt=` in `SPEECH_SERVERS`): each piece is one timed segment. Every other language goes whole to
   Speaches (Whisper large-v3-turbo, `whisper=`).
4. **Result.** Page `/speech-to-text/creations/{id}`: the words or the timed lines, Copy, downloads. The user can
   leave while it works: the top bar shows "Transcribing…" and says when it is ready.

## Languages

`wasifyai_stt/languages.yaml`: 51 languages with their names in their own script and a quality from the measured
word error (ADR-0043): good (English, Spanish, French, German, Russian, Chinese, Japanese, Hindi), fair (Arabic,
Bengali), unrated for the rest. The 22 Indian languages IndicConformer serves are listed under `engines.indic`.

## Not built yet (ADR-0043)

- **Long transcripts in search**: only the first part (about 6000 characters) is indexed; several pieces per
  transcript come with a `chunk` column on the index.
- A native Apple-silicon (MLX) server for Macs: about 30 times faster than real time against about 1.4 times
  slower than real time for large-v3 on the CPU container.
- A test on real recordings with noise and several speakers.

## Run and test

```
podman compose up -d speech stt-indic   # Whisper turbo and large-v3, and IndicConformer (needs HF_TOKEN, 6 min the first time)
uv run pytest products/wasifyai-stt services/api/tests/test_media_uploads.py services/media-worker
uv run python services/api/evals/transcribe/fetch_fleurs.py OUT_DIR       # the evaluation clips
```
