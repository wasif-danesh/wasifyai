---
action: dub.script
screen: voice.dub
synonyms: [dubbing, translate a recording, dub script]
---
# Write the dub script

Action: `dub.script`

## What it is for

The first step of a dub: write down what is said and translate it line by line, with times, so you can check it.

## Steps in the app

1. Open **Voice › Dub a recording**.
2. Choose the recording and the language to dub into.
3. Choose to write the script and read the lines.

## Fields

- `source_kind`: track or speech.
- `source_id`: The recording.
- `language`: For example fr, es, de.
- `background`: Separate the voice from the music first.

## Limits

- 28 languages.
- Up to 400 lines.

## Needs

- Transcription and speech models, and the chat model for translation.

## Examples

- Dub that recording into French.

## Problems

- **No voice for the language** Get a speech model that speaks it (Models).
