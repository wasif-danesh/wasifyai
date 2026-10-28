---
action: video.animate
screen: video.animate
synonyms: [make a picture move, image to video, bring to life]
---
# Animate a picture

Action: `video.animate`

## What it is for

Turn a picture of your library into a short clip by saying what should move.

## Steps in the app

1. Open **Video › Animate an image**.
2. Choose a picture, or choose **Animate this** under a picture on an Images screen to bring it here.
3. Say what should move and the length.
4. Choose **Make the video**.

## My looks

If you taught the video model a look or a motion (under **Train models**, in the Video model training card), the screen shows **My looks**: choose up to two and a strength for each (1.5 is a good start; above 2 can look rough). The app adds each look's magic word to your prompt if it is missing. A look made for another model does not work here; looks are made for LTX-Video 2B only.

## Fields

- `image_id`: The picture.
- `prompt`: What should move.
- `seconds`: 5 or 8 (5 unless you say otherwise).

## Limits

- 500 characters.
- One clip at a time.

## Needs

- The video engine (Models).

## Examples

- The clouds drift slowly to the left.

## Problems

- **Not in the library** Choose a picture that still exists.
