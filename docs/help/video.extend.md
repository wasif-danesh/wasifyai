---
action: video.extend
screen: video.extend
synonyms: [make a video longer, continue a video, carry on a video, longer clip, too short, make it longer, extend]
---
# Extend a video

Action: `video.extend`

## What it is for

Make a video longer. Its last second starts a new part, and the two are joined, so the movement carries
on. You choose how much is added: about 5 or about 8 seconds. The result is a new video; the original
stays. The video can be one of your library or a video file you add from your computer.

## Steps in the app

1. Open **Video › Extend video**.
2. Choose one of your videos, or choose **Add a video from this computer** and pick a file (MP4, MOV or
   WebM, up to 30 seconds). It is made to fit the model and added to Your videos; the file you picked is
   not changed.
3. Say what should keep happening. The words of a video made here are filled in from its own; change
   them if you like.
4. Choose how much to add (about 5 or about 8 seconds).
5. Choose Carry on my video.

## My looks

If you taught the video model a look or a motion (under **Train models**, in the Video model training card), the screen shows **My looks**: choose up to two and a strength for each (1.5 is a good start; above 2 can look rough). The app adds each look's magic word to your prompt if it is missing. A look made for another model does not work here; looks are made for LTX-Video 2B only.

## Fields

- `video_id`: The video to carry on.
- `prompt`: What should keep happening.
- `seconds`: How much is added: 5 or 8 (5 unless you say otherwise).

## Limits

- 500 characters.
- There is no limit on the length of the video, and a video can be carried on again and again. The picture gets a
  little softer each time, so two or three rounds is a sensible stop.
- What you write steers only weakly. The movement of the last second carries on whatever it says.
- One clip at a time.
- An added video is made at the size the model uses (the longer side at most 768), 24 frames a second,
  without sound. It must be under 200 MB.
## Needs

- The video engine (Models).

## Examples

- The fox keeps walking through the snow.

## Problems

- **Not in the library** Choose a video that still exists and is finished.
- **Not a video this app can read** Try an MP4 or MOV file.
- **Longer than 30 seconds** Cut the video shorter first.
