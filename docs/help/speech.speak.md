---
action: speech.speak
screen: voice.speak
synonyms: [read aloud, voice over, tts, text to speech, speak, say this, narrate]
---
# Text to speech

Action: `speech.speak`

## What it is for

Read a text aloud in a voice and keep the recording in your library.

## Steps in the app

1. Open **Voice › Text to speech**.
2. Type or paste the text.
3. Choose a voice: one that comes with the model, or one of your saved voices.
4. Choose Speak. The recording appears under Made before.

## Fields

- `text`: What to say.
- `voice`: A built-in voice of the model.
- `saved_voice`: One of your saved voices (see `voice.list`).
- `model`: Optional: a model id.

## Limits

- 5,000 characters.
- A voice is either built-in or saved, not both.

## Needs

- A speech model (Models) and the speech runtime.

## Examples

- Hello, and welcome.
- Read this paragraph in my calm narrator voice.

## Problems

- **It says a model is missing** Open **Model hub**, get a speech model, then try again.
- **The text is too long** Split it, or use the Audiobook screen.
