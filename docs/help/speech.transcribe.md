---
action: speech.transcribe
screen: voice.transcribe
synonyms: [transcribe, write down, speech to text, captions, recording to text, words from a recording, what was said, subtitles]
---
# Speech to text

Action: `speech.transcribe`

## What it is for

Write down what a recording in your library says and keep it as a transcript.

## Steps in the app

1. Open **Voice › Speech to text**.
2. Choose the **Language** of the recording, or leave **Find it by itself**. For Bengali and Hindi choose it:
   found by itself, one is taken for the other. **IndicConformer 600M** (Models) writes down Bengali, Hindi,
   Marathi, Telugu, Tamil and Gujarati.
3. Drop a recording on the screen or choose **Choose a recording**.
4. Choose **Transcribe**. The text appears with its times, with Copy and Save (.txt, .srt or .vtt), and
   joins Recent transcripts.

## Fields

- `source_kind`: track or speech.
- `source_id`: The recording.
- `path`: For another app connected to Wasify AI: the full path of an audio or video file inside a folder that connection may read (Settings › Other apps), instead of a recording of the library.
- `title`: Optional name.
- `language`: Optional: the language of the recording (`bn`, `hi`, `de` ...). A ready model that writes it is
  chosen, and it is told the language.

## Limits

- The recording must be in your library.

## Needs

- A transcription model (Models).

## Examples

- Write down what that speech says.

## Problems

- **Recording is no longer there** Choose another one.
