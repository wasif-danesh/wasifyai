---
action: train.start
screen: train
synonyms: [train, teach, teach the app, make my own character, my own style, lora, fine tune, my mascot, my pet, my face, my art style, train a character, train a style, magic word, trigger word, custom model]
---
# Teach a character or style

Action: `train.start`

## What it is for

Teach the image model something of your own from your pictures: a character, a pet, a person (with their
agreement), your art style or an object. You only add pictures. The app checks each one, writes a
description of each, suggests a magic word, and teaches the model. Then writing the magic word in a prompt
draws it. The set of pictures is made on the **Train models** screen; an agent starts the run on a set that is ready.
While the trainer is a preview, the run does everything except learn, and says so.

## Steps in the app

1. Open **Train models** and choose Make my own character or style.
2. Add pictures: 15 to 25 good ones is plenty, at least 8. Each is marked Good, Too small, Blurry or Looks like
   a copy; remove what you do not want, or choose Remove the ones with a problem.
3. Say what it is (a character, a style or an object), give it a name, choose one of the three magic words (or
   type your own) and say whose it is.
4. Read the descriptions the app wrote; change any, or choose Describe again.
5. Choose Teach it. It takes about 25 minutes on a Mac and chat and image making pause. A new sample picture
   appears now and then. You can stop it; nothing is kept.
6. The result is in My models and in the library, found by its name and magic word.

## Fields

- `dataset_id`: The set of pictures to teach from. It must have at least 8 pictures, a description for each, a
  magic word and the statement of whose it is.

## Limits

- One run at a time: a run holds most of the GPU and the one big-model slot, so other models are put away.
- Pictures of a real person need the person's agreement: you are asked whose it is, and the answer is kept with
  the model.
- The descriptions are in English. Pictures are checked by the safeguards when they are on, and a picture they
  refuse is not kept.
- Daily limits apply while the safeguards are on: 3 runs and 200 pictures a day.

## Needs

- A model that can read pictures (to write the descriptions), the training engine, enough free disk space for
  the pictures and the samples, and free memory for the run.

## Examples

- Teach the app my mascot from the set of pictures I added.
- Start the training for the style set "Ink".

## Problems

- **Add at least 8 pictures** Add more, 15 to 25 good ones is plenty.
- **Write the descriptions first** Choose Write the descriptions on the screen.
- **Say whose it is first** Choose one of the statements on the Check step.
- **A model is being taught** Wait for it to finish or stop it.
- **You've reached today's limit** Try again tomorrow.
