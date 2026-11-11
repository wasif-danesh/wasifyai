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
3. Choose the **Shape** (as the picture, Portrait 9:16, Landscape 16:9, Square 1:1 or Social feed 4:5) and the
   **Size** (480p or 720p). Another shape crops the picture, keeping its upper part; the picture shows the crop.
4. Type the words or choose a recording.
5. Choose **Make the video**. It plays on the right; Save MP4, Rename and Delete are under it.

## Fields

- `image_id`: The picture.
- `text`: Words for the face to say.
- `source_kind`, `source_id`: Or a recording of the library (a track or a speech).
- `start`, `end`: Only that part of the recording, in seconds: a line of a song, for Creative Studio's
  sung shots. At least half a second.
- `shape`: `picture` (its own shape, the default), `9:16`, `16:9`, `1:1` or `4:5`. A picture's own shape is kept
  between 9:16 and 16:9.
- `size`: the short side of the video: `480` (480p) or `720` (720p, the default).

## Limits

- Voices of up to 60 seconds; the screen shows the limits.
- It is slow at 720p: about 2.5 minutes of work for each second of video on a 64 GB Mac from a near-square
  picture (a 10 second voice takes about 25 minutes), and about 6.7 minutes in portrait (720x1280). 480p is about
  four times quicker (estimated). The screen shows the time for the shape and size chosen.

## Needs

- The lip sync engine (Models).

## Examples

- Make this drawing say: Hello, I am your guide.

## Problems

- **The lip sync engine is not set up** Open **Model hub** and set it up.
