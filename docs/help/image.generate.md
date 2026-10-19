---
action: image.generate
screen: images.create
synonyms: [draw, paint, generate an image, text to image, make a picture]
---
# Make a picture

Action: `image.generate`

## What it is for

Make a new picture from a description and keep it in your library.

## Steps in the app

1. Open **Images › Create**.
2. Describe the picture in the text box.
3. Choose a shape (square, landscape, portrait, wide or tall).
4. Choose Create and wait: it shows progress.

## Fields

- `prompt`: A clear, concrete description, in English works best.
- `size`: square, landscape, portrait, wide or tall.

## Limits

- 500 characters.
- Safeguards may refuse some descriptions; the reason is shown.

## Needs

- The image engine to be set up (Models).

## Examples

- A red teapot on a wooden table.
- A cat dressed as an astronaut on the moon, wide.

## Problems

- **It says the image engine is not set up** Open **Models** and set up image generation first.
- **Refused** The description was not allowed; change it.
