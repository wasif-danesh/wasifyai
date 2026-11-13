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

1. Open **Video › Lip sync**.
2. Choose the model with the model button: **On this computer** (EchoMimic v3) or, once a Runware, WaveSpeed or fal.ai
   key is saved for Lip sync under Your keys in Settings, **Cloud**: Fabric 1.0 Fast, Kling Avatar v2, OmniHuman 1.5
   or InfiniteTalk. Each cloud row says its price and how long a second of video takes. On the web, until an admin
   chooses one, lip sync runs on the cheapest model the saved keys can run at 480p (Kling Avatar v2 with a Runware or
   fal.ai key, Fabric 1.0 Fast with a WaveSpeed key alone); InfiniteTalk is never the default, only chosen.
3. Choose a picture.
4. Choose the **Shape** (as the picture, Portrait 9:16, Landscape 16:9, Square 1:1 or Social feed 4:5) and the
   **Size** (480p or 720p). Another shape crops the picture, keeping its upper part; the picture shows the crop.
   In the cloud, Fabric 1.0 Fast and OmniHuman 1.5 always make a square video, so there is no shape to choose;
   Kling and InfiniteTalk keep the shape but pick the exact size, so the screen says "about" its size.
5. Type the words or choose a recording.
6. Choose **Make the video**. It plays on the right; Save MP4, Rename and Delete are under it.

## Fields

- `image_id`: The picture.
- `text`: Words for the face to say.
- `source_kind`, `source_id`: Or a recording of the library (a track or a speech).
- `start`, `end`: Only that part of the recording, in seconds: a line of a song, for Creative Studio's
  sung shots. At least half a second.
- `shape`: `picture` (its own shape, the default), `9:16`, `16:9`, `1:1` or `4:5`. A picture's own shape is kept
  between 9:16 and 16:9.
- `size`: the short side of the video: `480` (480p) or `720` (720p), as the model offers. On this computer 720p is
  the default; in the cloud 480p is, where the model has it.

## Limits

In the cloud, before Make the screen says the time and cost of this voice at the size chosen; nothing
is refused for its length below the model's limit:

| Model | Price (the cheapest provider runs it) | Time per second of video (measured) | Longest voice |
|---|---|---|---|
| Fabric 1.0 Fast | WaveSpeed $0.07 a second at 480p, $0.14 at 720p; fal.ai $0.10 and $0.20 | 5 to 25 s at 480p (two runs) | 1 minute |
| Kling Avatar v2 | Runware $0.044 a second; fal.ai $0.0562 | about 40 s | 1 minute |
| OmniHuman 1.5 | Runware $0.132 a second; fal.ai $0.16 (720p) | about 45 s | 1 minute |
| InfiniteTalk | WaveSpeed $0.03 a second at 480p, $0.06 at 720p; fal.ai $0.20 and $0.40 | about 50 s at 480p | 28 seconds |

The picture and the voice go to the provider with your key; its terms and prices apply.

On this computer:

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
