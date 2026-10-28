---
action: lipsync.make
screen: voice.lipsync
synonyms: [talking picture, make a picture talk, avatar, lip sync]
---
# Lip sync

Action: `lipsync.make`

## What it is for

Make a picture talk: a video of the face saying words or a recording. Every video is marked AI-generated.

## Steps in the app

1. Open **Voice › Lip sync**.
2. Choose a picture and say what it is (a drawing, you, or someone who agreed).
3. Type the words or choose a recording, and say whose voice it is.
4. Choose **Make the video**. It plays on the right with what you said about the picture and the voice;
   Save MP4, Rename and Delete are under it.

## Fields

- `image_id`: The picture.
- `text`: Words for the face to say.
- `picture_is`: drawn, own or permission.
- `voice_is`: For a recording: own or permission.

## Limits

- Always needs your word in the app window.
- Short pictures and voices only; the screen shows the limits.

## Needs

- The lip sync engine (Models).

## Examples

- Make this drawing say: Hello, I am your guide.

## Problems

- **The lip sync engine is not set up** Open **Model hub** and set it up.
- **Needs your word** Approve in the app window.
