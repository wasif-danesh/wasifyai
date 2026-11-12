---
action: train.make_set
screen: train
synonyms: [teach it my dog from these photos, make a training set, set of pictures, train on these photos, teach it from this spreadsheet, examples from this file, teach it to decide from this table]
---
# Make a set to teach from

Action: `train.make_set`

## What it is for

Make the set that **Teach a character or style** (`train.start`) teaches from, from the chat: "teach it my dog from these
15 photos", or "teach it to answer like this spreadsheet". It does what the Train screen does before its Teach it button,
then says whether the set is ready.

- **Pictures** (`what`: `pictures`): from pictures of your library, or photos attached in the chat (the chat keeps them in
  your library first). Each picture is checked as on the screen, the app writes a description of each and chooses a
  magic word (or takes yours).
- **Writing examples** (`what`: `writing`): from an attached table of questions and answers.
- **Texts to decide about** (`what`: `decision`): from an attached table of texts and their right answers, with the
  question asked of every text. Yes and no answers make a yes-or-no question, numbers a score, anything else categories.

## Steps in the app

1. In the chat, attach the photos (or a CSV of examples) and say what to teach it.
2. The chat proposes the set; confirm the card. The card says what is still missing, or offers **Teach it**.
3. **Teach it** proposes `train.start` on the new set.

On the screen, **Train models** makes the same sets by hand, and shows them with their checks to change.

## Fields

- `what`: `pictures` (the default), `writing` or `decision`.
- `name`: A name for the set.
- `kind`: Pictures: `character` (a pet, a person), `style` or `object`.
- `image_ids`: Pictures: the library pictures, or attached photos by their attachment id; 8 or more, 15 to 25 is best.
- `magic_word`: Pictures: a made-up word of 4 to 12 letters; left out, or a poor one, the app picks one.
- `attachment_id`: Writing or decision: the attached table, one example a row, the question or text in the first
  column and the answer in the last. Commas, semicolons or tabs; a first row naming the columns is left out.
- `question`: Decision: the question asked of every text.

## Limits

- Up to 100 pictures in a set. The descriptions are in English.
- Writing sets need at least 10 examples, decision sets at least 20 with two different answers.
- Sets for the video model are made on the screen.

## Needs

- Pictures: a model that can read pictures, to write the descriptions. Without one the set is made without them and
  the card says so.

## Examples

- Teach it my dog Marlo from these 15 photos.
- Make a set from this spreadsheet of support replies and teach a writing model.
- Teach it to decide whether each review in this file is positive.

## Problems

- **Add at least 8 pictures** Attach or choose more; 15 to 25 good ones is plenty.
- **None of those pictures is in the library** Attach them again.
- **No examples were found in that file** Put one example a row, the question first and the answer last.
