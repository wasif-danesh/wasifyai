---
action: image.inpaint
screen: images.inpaint
synonyms: [inpaint, change part of a picture, paint over, replace an area, fill an area, edit a region]
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

## Fields

- `image_id`: The picture to change.
- `prompt`: What to put in the area.
- `region`: The area, as a rectangle: `left`, `top`, `width` and `height` as shares of the picture (0 to 1). In the app you paint it.

## Limits

- 500 characters.
- The area must cover something and not nearly all of the picture.
- The picture is worked on at about one megapixel, so a larger picture comes back at that size.
- A small area is sometimes ignored by the model; a larger one works better.

## Needs

- The image engine (Models).

## Examples

- A white coffee cup with steam, in a rectangle at the lower right of a plant photo.
- A plush red velvet cushion, painted over the seat of a chair.

## Problems

- **Not in the library** Choose a picture that still exists.
- **Paint the part of the picture you want to change** The area was empty.
- **Leave part of the picture unpainted** The area covered almost everything; use Edit to change the whole picture.
- **Nothing changed** Make the area larger and describe the thing plainly.
