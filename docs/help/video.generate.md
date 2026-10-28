---
action: video.generate
screen: video.create
synonyms: [make a video, text to video, animate a scene, clip]
---
# Make a video

Action: `video.generate`

## What it is for

Make a short video clip (5 or 8 seconds) from a description.

## Steps in the app

1. Open **Video › Create**.
2. Describe what happens.
3. Choose the length and the shape.
4. Choose **Make the video**. It takes minutes; you can leave the screen, and the clip plays where it appears
   when it is done. Under it are your recent videos; **Extend this** carries a clip on.

## My looks

If you taught the video model a look or a motion (under **Train models**, in the Video model training card), the screen shows **My looks**: choose up to two and a strength for each (1.5 is a good start; above 2 can look rough). The app adds each look's magic word to your prompt if it is missing. A look made for another model does not work here; looks are made for LTX-Video 2B only.

## Fields

- `prompt`: What happens in the clip.
- `shape`: landscape, portrait or square.
- `seconds`: 5 or 8 (5 unless you say otherwise).

## Limits

- 500 characters.
- One clip at a time.

## Needs

- The video engine (Models).

## Examples

- Waves rolling onto a beach at sunrise.

## Problems

- **You already have a video being made** Wait for it to finish.
- **Not set up** Open **Model hub** and set up the video engine.
