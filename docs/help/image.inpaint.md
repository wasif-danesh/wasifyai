---
action: image.inpaint
screen: images.inpaint
synonyms: [inpaint, change part of a picture, paint over, replace an area, fill an area, edit a region, change only the sky, replace the sofa, change his shirt]
---
# Change part of a picture

Action: `image.inpaint`

## What it is for

Change only one area of a picture and leave everything outside it exactly as it was: put a cup on the table, change a cushion's colour,
replace the animal. The original stays.

## Steps in the app

1. Open **Images › Inpaint**.
2. Choose a picture.
3. Paint the area to change, or drag a rectangle over it.
4. Say what to put there.
5. Choose Create.

In the chat, say what to change in words ("make only the sky a sunset"): the chat finds the sky with the model that
reads pictures and shows it as a box on the picture in its card; press Make it, or drag across the picture to draw
another box first. Under a picture in the chat, **Change an area** lets you draw the box yourself and say what goes
there.

## Fields

- `image_id`: The picture to change.
- `prompt`: What to put in the area.
- `region`: The area, as a rectangle: `left`, `top`, `width` and `height` as shares of the picture (0 to 1). In the app you paint it.
- `area`: Instead of `region`, the area in words ("the sky", "his shirt"); the app finds it in the picture.
- `model`: which image model makes it, by its id (for example `qwen-image-2.1`); left out, the default. A model
  that cannot do this is refused ("This model cannot ...").

## Limits

- 500 characters.
- The area must cover something and not nearly all of the picture.
- The picture is worked on at about one megapixel, so a larger picture comes back at that size.
- A small area is sometimes ignored by the model; a larger one works better.

## Needs

- The image engine (Models).
- For an area named in words, a model that can read pictures (Select chat model). Without one, draw the box.

## Examples

- A white coffee cup with steam, in a rectangle at the lower right of a plant photo.
- A plush red velvet cushion, painted over the seat of a chair.

## Problems

- **Not in the library** Choose a picture that still exists.
- **"…" was not found in that picture** Draw a box on the picture instead.
- **Choose a model that can read pictures first** Choose one, or draw a box on the picture.
- **Paint the part of the picture you want to change** The area was empty.
- **Leave part of the picture unpainted** The area covered almost everything; use Edit to change the whole picture.
- **Nothing changed** Make the area larger and describe the thing plainly.
