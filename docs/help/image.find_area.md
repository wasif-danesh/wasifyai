---
action: image.find_area
screen: images.inpaint
synonyms: [where is the sky, find the sofa in this picture, which part is his shirt]
---
# Find an area of a picture

Action: `image.find_area`

## What it is for

Find one thing in a picture of your library, such as the sky, the sofa or a shirt, and get the rectangle around it, so
**Change part of a picture** can change only that. The chat does this by itself when you name the area in words.

## Steps in the app

1. In the chat, ask to change part of a picture in words ("make only the sky a sunset").
2. The chat finds the area and shows it as a box on the picture in its card. Drag across the picture to draw another.

On **Images › Inpaint** you paint the area yourself.

## Fields

- `image_id`: The picture to look in.
- `area`: What to find, in words.

## Limits

- One thing at a time. The box is a little larger than what was found, so the change blends in.
- How well it finds things depends on the model that reads pictures.

## Needs

- A model that can read pictures (Select chat model).

## Examples

- Find the sky in my beach photo.

## Problems

- **"…" was not found in that picture** Draw a box on the picture instead.
- **Choose a model that can read pictures first** Choose one, or draw the box yourself.
