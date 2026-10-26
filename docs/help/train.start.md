---
action: train.start
screen: train
synonyms: [teach it from examples, answer my way, my tone, my format, language model training, write like me, my writing style, train, teach, teach the app, make my own character, my own style, lora, fine tune, my mascot, my pet, my face, my art style, train a character, train a style, magic word, trigger word, custom model]
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

1. Open **Train models** and, under **Image model training**, choose Make my own character or style.
2. Add pictures: 15 to 25 good ones is plenty, at least 8. Each is marked Good, Too small, Blurry or Looks like
   a copy; remove what you do not want, or choose Remove the ones with a problem.
3. Say what it is (a character, a style or an object), give it a name, choose one of the three magic words (or
   type your own) and say whose it is.
4. Read the descriptions the app wrote; change any, or choose Describe again.
5. Leave **Choose the model and method** closed to use the recommendation (FLUX.2 klein base 4B, as a small
   adapter). Open it to see every model on this computer and how each can be taught, with the reason beside
   anything that cannot be used.
6. Choose Teach it. It takes about 25 minutes on a Mac and chat and image making pause. A new sample picture
   appears now and then. You can stop it; nothing is kept.
7. The result is in My models and in the library, found by its name and magic word.

## Fields

- `dataset_id`: The set of pictures to teach from. It must have at least 8 pictures, a description for each, a
  magic word and the statement of whose it is.
- `base`: Optional. The model to teach. Leave it out for the recommended one (FLUX.2 klein base 4B).
- `method`: Optional. `lora` (a small adapter, the recommended and only method for pictures), `qlora` (less
  memory, for writing models) or `full` (teach all of it, Advanced). A method the model cannot use is refused
  with the reason.

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
- **This model cannot be taught yet** Choose the recommended model, or leave the choice closed.
- **You've reached today's limit** Try again tomorrow.

---

## Teaching a language model from examples (the same action, with `set_id`)

### What it is for

Show a small language model questions and the answers you want, many times, and it learns to answer that way: a
tone, a format, a set of labels, the way you reply. It learns how to answer, not new facts (for facts, put your
documents in a notebook). It is taught on this computer and your examples are not sent anywhere. Afterwards the
screen shows the same questions answered before it learnt and after, side by side, and a mark that says whether the
answers got closer to yours.

### Steps in the app

1. Open **Train models** and, under **Language model training**, choose **Teach it from examples**.
2. The first time, the app offers to set up the trainer and a small model (about 0.4 GB, shown first); nothing
   is fetched until you press the button.
3. Choose New set of examples. Type each question and the answer you want ("What it is asked", "What it should
   answer"), or paste two columns from a spreadsheet. It saves as you type. At least 10 are needed; 50 or more is a
   good start.
4. Read the check. It leaves out empty and repeated rows, and warns about very long answers and about anything
   that looks like an email address, a phone number or a card number.
5. Say whose the examples are (you wrote them, or you have permission).
6. Choose Teach it. It takes about a minute on a Mac and chat and image making pause.
7. The result is in My models. Ask both the original and your taught model something new with Ask both.
8. To chat with it, choose **Use in chat** under the result (or under it in My models). The first time the app asks to
   download the same model in the form the chat engine runs (shown first). Choose **Back to my chat model** to
   return to the model chat used before.

To use a different model or to take more care, open **Choose the model and method** (closed by default, with the
recommendation). It lists Qwen3 0.6B (small and quick), 1.7B and 4B (they follow the examples more closely and take
longer), and Quick or Better. One that is not on this computer has **Get it** next to its name, with its size;
nothing is fetched until you press it.

### Fields

- `set_id`: Instead of `dataset_id`: the set of examples to teach a language model from. It needs at least 10
  examples and the statement of whose they are.

### Limits

- One run at a time: a run holds most of the GPU and the one big-model slot, so other models are put away.
- The models it is taught on are small (Qwen3 0.6B, 1.7B or 4B, 4-bit): they copy how the examples answer and can
  still answer wrongly about facts.
- Examples in English work best; the base model reads other languages but this has not been measured.
- Daily limits apply while the safeguards are on, the same as pictures.

### Needs

- A Mac with Apple silicon, the trainer and its small model (set up in the app), a little free disk space.

### Examples

- Teach it from the set of examples "Customer replies".

### Problems

- **Add at least 10 examples** Add more questions and answers; 50 or more is better.
- **Say whose these examples are first** Choose one of the two statements on the Check step.
- **A model is being taught** Wait for it to finish or stop it.
- **Training is not set up on this computer yet** Choose Download and set up on the Train screen.
