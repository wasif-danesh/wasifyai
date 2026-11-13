---
action: image.edit
screen: images.edit
synonyms: [edit a picture, change an image, image to image, retouch]
---
# Change a picture

Action: `image.edit`

## What it is for

Change a picture you already have by saying what to change. The original stays.

## Steps in the app

1. Open **Images › Edit**.
2. Choose a picture from your library.
3. Say what to change.
4. Choose Create.

## Fields

- `image_id`: The picture to change.
- `prompt`: What to change.
- `model`: which image model makes it, by its id (for example `qwen-image-2.1`); left out, the default. A model
  that cannot do this is refused ("This model cannot ...").

## Limits

- 500 characters.

## Needs

- The image engine (Models).

## Examples

- Make the sky a sunset.

## Problems

- **Not in the library** Choose a picture that still exists.
