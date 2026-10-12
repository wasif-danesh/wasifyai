# wasifyai-tts

Status: **working, first slice** ([ADR-0042](../../docs/decisions/0042-text-to-speech.md)).

A signed-in user types up to 2000 characters, chooses a language and a male or female voice, and gets an MP3
to play and download. It is saved in My creations and is searchable by its words.

## Flow

`check_request` (length, voice exists, daily quota, text moderation) -> `start_job` (a `speech.synthesize` job)
-> `await_job` -> `finalise` (WAV to MP3 with the bundled ffmpeg, an ID3 tag saying it is AI-generated, the
`speeches` row, a usage event, the search index). The media worker splits long text at sentence ends in any
script, calls the speech server for each piece and joins the WAVs.

## Voices

`voices.yaml` is the catalog: language, gender, engine, engine voice, the model card grade and a default per
choice. A combination with no voice (a male French voice) is shown as unavailable, never replaced. Languages in
this version: English (US, UK), Spanish, French, Hindi, Italian, Portuguese (Brazil). Spanish and Portuguese are
graded low by the model card and are marked as limited. Japanese and Chinese are not offered because the
Speaches server cannot make them. Bengali (Aditi and Arjun) is made by Indic Parler-TTS in the `speech-indic` service: slow on a CPU (about 5 times
slower than real time); a native listener reviewed both voices and found them good. It needs `HF_TOKEN` in `.env` (read access to the
gated `ai4bharat/indic-parler-tts`) and about 4.5 GB of memory for that service alone.

## Run and test

```
podman compose up -d speech
curl -X POST localhost:8100/v1/models/speaches-ai%2FKokoro-82M-v1.0-ONNX
uv run pytest products/wasifyai-tts
uv run python services/api/evals/speech/run_speech_eval.py --per-group 2
```
