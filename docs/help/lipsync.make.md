---
action: lipsync.make
screen: voice.lipsync
synonyms: [talking picture, make a picture talk, avatar, lip sync]
---
# Lip sync

Action: `lipsync.make`

## What it is for

Make a picture talk: a video of the face saying words or a recording.

## Steps in the app

1. Open **Voice › Lip sync**.
2. Choose a picture.
3. Type the words or choose a recording.
4. Choose **Make the video**. It plays on the right; Save MP4, Rename and Delete are under it.

## Fields

- `image_id`: The picture.
- `text`: Words for the face to say.
- `source_kind`, `source_id`: Or a recording of the library (a track or a speech).
- `start`, `end`: Only that part of the recording, in seconds: a line of a song, for Creative Studio's
  sung shots. At least half a second.

## Limits

- Short pictures and voices only; the screen shows the limits.

## Needs

- The lip sync engine (Models).

## Examples

- Make this drawing say: Hello, I am your guide.

## Problems

- **The lip sync engine is not set up** Open **Model hub** and set it up.
