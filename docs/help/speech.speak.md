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
3. Choose a voice in the list: your own voices first, then the ones that come with the model. **Hear it**
   speaks a short line in a voice you have not heard yet; a voice heard before plays at once. **Make a voice**
   at the end of the list describes or copies a new one without leaving the screen.
4. Choose **Make the speech**. It plays where it appears, with its waveform, and joins Recent speech under it.
   Speed and seed are under **For experts**.

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
