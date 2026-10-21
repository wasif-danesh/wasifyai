---
action: video.extend
screen: video.extend
synonyms: [make a video longer, continue a video, carry on a video, longer clip]
---
# Extend a video

Action: `video.extend`

## What it is for

Make a video of your library longer. Its last second starts a new part, and the two are joined, so
the movement carries on. About 1.7 seconds are added. The result is a new video; the original stays.

## Steps in the app

1. Open **Video › Extend video**.
2. Choose one of your videos.
3. Say what should keep happening. The words are filled in from the original; change them if you like.
4. Choose Extend.

## Fields

- `video_id`: The video to carry on.
- `prompt`: What should keep happening.

## Limits

- 500 characters.
- A video can be extended until it is about 4 seconds long, so a 2 second video twice. A 5 second video
  cannot be extended.
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
