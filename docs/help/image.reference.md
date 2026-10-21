---
action: image.reference
screen: images.reference
synonyms: [combine pictures, two pictures, picture from pictures, use a reference, reference image]
---
# Make a picture from two pictures

Action: `image.reference`

## What it is for

Make a new picture that uses what you say from two pictures you already have: for example the cat from the first picture on the
chair from the second. The two originals stay. You choose the shape of the new picture.

## Steps in the app

1. Open **Images › Reference**.
2. Add the first picture, then the second. The order matters: you can call them "picture 1" and "picture 2" in your words.
3. Say what to make.
4. Choose a size, then Create.

## Fields

- `image_ids`: Two pictures of your library, in order.
- `prompt`: What to make from them.
- `size`: The shape of the new picture (square, landscape, portrait, wide or tall).

## Limits

- Exactly two pictures, and they must be different.
- 500 characters.
- It takes about a minute: each picture adds to the work the model does.

## Needs

- The image engine (Models).

## Examples

- The cat from picture 1 sitting on the chair from picture 2, in a sunlit room.
- The sneaker from picture 1 on a wooden table next to the plant from picture 2.

## Problems

- **Not in the library** Choose pictures that still exist.
- **The same picture twice** Choose two different pictures.
- **One subject is missing or changed** Name what to take from each picture ("the cat from picture 1"), or try another seed.
