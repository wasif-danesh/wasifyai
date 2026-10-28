---
action: dub.make
screen: voice.dub
synonyms: [dub, voice over in another language]
---
# Dub a recording

Action: `dub.make`

## What it is for

The second step: speak the checked lines in the new language and mix them with the background.

## Steps in the app

1. Open **Voice › Dub a recording**.
2. Write and check the script, then choose **Next: the voice**.
3. Choose whose voice (the speaker's needs your word that you may copy it), then **Make the dub**. The dub
   plays on the right and is kept in the Library; **Change the script** goes back to the lines.

## Fields

- `segments`: The lines with start and end times and the new text.
- `voice_from`: builtin or saved.
- `saved_voice`: When voice_from is saved.

## Limits

- Needs ffmpeg for the mix.
- Copying the original speaker's voice is only offered on the screen.

## Needs

- A speech model for the language.

## Examples

- Dub it with the script I just checked.

## Problems

- **Needs ffmpeg** Install ffmpeg, then try again.
