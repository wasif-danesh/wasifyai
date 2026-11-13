# Voice languages L0: checks before building (2026-11-13)

Stage L0 of `docs/voice-languages-plan.md`. No product code changed. Every run was real, on an Apple M5 Pro with
64 GB. The scripts and outputs are in the session's scratch folder. The samples for listening are in
`~/Projects/wasify-voice-l0-listening/` (outside the repo; open `index.html`).

**How a sample is scored.** Each sample is spoken, then written back by a transcription model and compared with the
text: the **word error** (0.0 means every word came back). The models used to write back are:

- **Parakeet** for es, fr, it, pt and en;
- **IndicConformer 600M** (RNNT) for bn, hi, mr, te, ta and gu;
- no local model writes Chinese, Japanese or Arabic, so those samples were made but not scored.

A word error is not a quality grade; the owner still listens to every Bengali sample (item 6).

## Result

| Language | Model | Where | Result | Notes |
|---|---|---|---|---|
| Bengali | Indic Parler-TTS (Aditi, Arjun) | this computer | **good** | 0.0 on 4 of 6, 0.11 and 0.18 on two Aditi sentences (fp32); 0.0 on all 6 in fp16 and on CPU. **Owner listened and approved, 2026-11-13** |
| Bengali | ElevenLabs v4 | cloud (fal) | **good** | 0.0 |
| Bengali | Gemini 3.8 Flash TTS | cloud (fal) | **good** | 0.0 |
| Bengali | Chatterbox multilingual | cloud (fal) | **no** | English-sounding words, with or without `language: "bn"` |
| Bengali | MiniMax Speech 2.8 HD | cloud (fal) | **no** | repeats a wrong phrase; `language_boost` has no Bengali (the provider refuses it) |
| Bengali (write) | IndicConformer 600M | this computer | **good** | wrote back every good sample above exactly |
| Bengali (write) | Scribe v2 | cloud (fal) | **good** | exact, with `bn` and with detection |
| Bengali (write) | Whisper | cloud (WaveSpeed) | **weak** | about 5 of 8 words wrong, even with `bn` |
| Hindi | Indic Parler-TTS (Divya, Rohit) | this computer | **good** | 0.0 |
| Hindi | Kokoro (hf_alpha, hf_beta, hm_omega, hm_psi) | this computer | **good** | 0.0 on all 4 |
| Hindi | VoxCPM2 | this computer | **good** | 0.0 |
| Marathi | Indic Parler-TTS (Sunita, Sanjay) | this computer | **good** | 0.0 |
| Telugu | Indic Parler-TTS (Lalitha, Prakash) | this computer | **good** | 0.0; 0.2 on Lalitha is one space ("ఈరోజు") |
| Tamil | Indic Parler-TTS (Jaya) | this computer | **good** | 0.0 (RNNT), 0.1 (CTC) |
| Gujarati | Indic Parler-TTS (Neha, Yash) | this computer | **good** | 0.0 |
| Spanish | Kokoro (ef_dora, em_alex, em_santa) | this computer | **good** | 0.0 |
| Spanish | VoxCPM2 | this computer | **good** | 0.0 |
| French | Kokoro (ff_siwis) | this computer | **good** | 0.0 |
| French | VoxCPM2 | this computer | **weak** | 0.27; the clip is short (2.1 s) and may be cut |
| Italian | Kokoro (if_sara, im_nicola) | this computer | **good** | 0.0 |
| Portuguese | Kokoro (pm_alex, pm_santa) | this computer | **good** | 0.0 |
| Portuguese | Kokoro (pf_dora) | this computer | **weak** | 0.1: a stray "RKA4JL" at the start |
| Chinese | Kokoro (8 voices), VoxCPM2 | this computer | made, not scored | 0.3 to 1.6 s per sentence |
| Arabic | VoxCPM2 | this computer | made, not scored | |
| Japanese | VoxCPM2 | this computer | made, not scored | |
| Japanese | Kokoro (5 voices) | this computer | **no** | audio.cpp refuses: the GGUF lacks the UniDic dictionary; it must be re-exported with `--embed-multilingual-resources` |

## Indic Parler-TTS: memory and speed

Bengali and the five other languages, one sentence (4 to 7 s of speech) each:

| Run | Load | Peak process memory | Peak GPU memory | Speed (audio s per second of work) |
|---|---|---|---|---|
| Mac GPU (MPS), float32 | 14.8 s | 4.2 GB | 6.75 GB | 0.6 to 0.97 (most about 0.9) |
| Mac GPU (MPS), float16 | 11.5 s | 6.0 GB* | 2.94 GB | 0.58 to 1.05 |
| CPU, float32 (the Linux and Windows stand-in) | 8.9 s | 5.6 GB | – | 0.16 to 0.53 |

\* The float16 process peak includes loading in float32 before the cast. Loading straight in float16 should bring it
down; check this in L5.

- **16 GB Macs:** float16 on the GPU needs under 3 GB of GPU memory, so it fits beside the app. float32 also fits
  but leaves less room. Neither was run on a real 16 GB Mac (plan item 3), which still needs doing. Use float16 by
  default; it was as accurate as float32 here.
- **CPU:** works and is accurate. It is 2 to 6 times slower than real time on this machine, and got slower as the
  run went on (8 s, then 26 to 29 s for a sentence); probably heat or other work. A real Linux or Windows machine
  still needs a run.
- **The first sentence is slower** on the GPU (warm-up), about 0.6 times real time.
- **Download:** 3.75 GB, plus the description encoder.
- **Packages:** `parler-tts` (from git), `transformers` 4.46.1 (pinned by parler-tts), `protobuf` 5 or newer (4.25
  fails to load the tokenizer), `sentencepiece`. This set does not match the engine's own `transformers`; it needs
  its own environment, as decision training does (T5).

## IndicConformer 600M: memory and speed

- **Load:** 2.5 to 2.9 s.
- **Peak process memory:** 3.0 GB on CPU (ONNX Runtime).
- **Speed:** 0.07 to 0.18 s per 4 to 7 s clip.
- **Download:** about 2.4 GB.
- **Needs:** `onnxruntime`, `trust_remote_code`. `torchaudio` 2.9 or newer needs `torchcodec` to read files, so read
  with `soundfile` instead.
- **Fits on a 16 GB Mac.**

## Cloud costs

All the cloud runs together cost a few cents:

- 4 voices once, and 2 retried with a language;
- Scribe v2 and Whisper twice each.

## Findings for the next stages

1. **The app sends no language to the cloud voices** (`speak_request` in `own_keys_voice.py`). ElevenLabs and
   Gemini read the script well without one. Chatterbox and MiniMax cannot speak Bengali at all, so the picker must not
   list them under Bengali (L3).
2. **Scribe v2 is the cloud writer for Bengali**; Whisper must not be offered for it. Detection worked on Scribe v2
   for this clip, but L4 still passes the language for Bengali and Hindi.
3. **Kokoro speaks Hindi, Spanish, French, Italian and Portuguese well**, so L3 can add them. Japanese needs the
   GGUF re-exported first; Chinese needs a listener.
4. **VoxCPM2 speaks Hindi and Spanish well.** French is weak on one short clip and needs another look.
5. **No provider we use hosts Indic Parler-TTS.** fal.ai, WaveSpeed and Runware have none. The only hosted copy found
   is a small community model on Replicate (`ttsds/parlertts_indic`), and Replicate is not one of our providers. The
   web therefore needs our own speech service, like the `embedder`. That needs the owner's yes and an ADR-0099
   amendment.
6. **The model card now points to newer releases from the same team** (`bodhan-ai/indic-speak`, and
   `bodhan-ai/indic-transcribe-core` for IndicConformer). They were not tried; the owner chose Indic Parler-TTS.

## Owner's listening

Owner, 2026-11-13: "Bengali is good". This covers the Indic Parler-TTS samples (full and half precision) and the
ElevenLabs v4 and Gemini 3.8 Flash TTS samples on the listening page.

## Not done in L0

- A real 16 GB and 24 GB Mac, and a real Linux and Windows machine.
- Listeners for the other Indian languages.
