---
action: video.extend
screen: video.extend
synonyms: [make a video longer, continue a video, carry on a video, longer clip]
---
# Extend a video

Action: `video.extend`

## What it is for

Make a video longer. Its last second starts a new part, and the two are joined, so the movement carries
on. About 1.7 seconds are added. The result is a new video; the original stays. The video can be one of
your library or a video file you add from your computer.

## Steps in the app

1. Open **Video › Extend video**.
2. Choose one of your videos, or choose **Add a video from this computer** and pick a file (MP4, MOV or
   WebM, up to 30 seconds). It is made to fit the model and added to Your videos; the file you picked is
   not changed.
3. Say what should keep happening. The words of a video made here are filled in from its own; change
   them if you like.
4. Choose Carry on my video.

## Fields

- `video_id`: The video to carry on.
- `prompt`: What should keep happening.

## Limits

- 500 characters.
- A video made here can be extended until it is about 4 seconds long, so a 2 second video twice. A 5
  second video made here cannot be extended. A video you added can be any length up to 30 seconds.
- An added video is made at the size the model uses (the longer side at most 768), 24 frames a second,
  without sound. It must be under 200 MB.
- The picture gets a little softer each time.
- What you write steers only weakly. The movement of the last second carries on whatever it says.
- One clip at a time.

## Needs

- The video engine (Models).

## Examples

- The fox keeps walking through the snow.

## Problems

- **Not in the library** Choose a video that still exists and is finished.
- **As long as it can get** Choose a shorter video, or make a new one.
- **Not a video this app can read** Try an MP4 or MOV file.
- **Longer than 30 seconds** Cut the video shorter first.
