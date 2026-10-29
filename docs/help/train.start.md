---
action: train.start
screen: train
synonyms: [video model training, make my own look, my own motion, video look, train a video, video lora, teach it to decide, decision model training, teach it from examples, answer my way, my tone, my format, language model training, write like me, my writing style, train, teach, teach the app, make my own character, my own style, lora, fine tune, my mascot, my pet, my face, my art style, train a character, train a style, magic word, trigger word, custom model]
---
# Teach a character or style

Action: `train.start`

## What it is for

Teach the image model something of your own from your pictures: a character, a pet, a person, your art
style or an object. You only add pictures. The app checks each one, writes a
description of each, suggests a magic word, and teaches the model. Then writing the magic word in a prompt
draws it. The set of pictures is made on the **Train models** screen; an agent starts the run on a set that is ready.
While the trainer is a preview, the run does everything except learn, and says so.

## Steps in the app

1. Open **Train models** and, under **Image model training**, choose Make my own character or style.
2. Add pictures: 15 to 25 good ones is plenty, at least 8. Each is marked Good, Too small, Blurry or Looks like
   a copy; remove what you do not want, or choose Remove the ones with a problem.
3. Say what it is (a character, a style or an object), give it a name, choose one of the three magic words (or
   type your own).
4. Read the descriptions the app wrote; change any, or choose Describe again.
5. Leave **Choose the model and method** closed to use the recommendation (FLUX.2 klein base 4B, as a small
   adapter). Open it to see every model on this computer and how each can be taught, with the reason beside
   anything that cannot be used.
6. Choose Teach it. It takes about 25 minutes on a Mac and chat and image making pause. A new sample picture
   appears now and then. You can stop it; nothing is kept.
7. The result is in My models and in the library, found by its name and magic word.

## Fields

- `dataset_id`: The set of pictures to teach from. It must have at least 8 pictures, a description for each and a
  magic word.
- `base`: Optional. The model to teach. Leave it out for the recommended one (FLUX.2 klein base 4B).
- `method`: Optional. `lora` (a small adapter, the recommended and only method for pictures), `qlora` (less
  memory, for writing models) or `full` (teach all of it, Advanced). A method the model cannot use is refused
  with the reason.

## Limits

- One run at a time: a run holds most of the GPU and the one big-model slot, so other models are put away.
- The descriptions are in English.

## Needs

- A model that can read pictures (to write the descriptions), the training engine, enough free disk space for
  the pictures and the samples, and free memory for the run.

## On the web

The same screen, the same sets and the same limits. The teaching runs on a worker of the service, not on your computer: an admin sets each
trainer up once (Admin, Workers, Trainers), and the card says "Ask an admin" until then. Your pictures, clips, examples and the models you taught
are kept for you only; no one else can see or use them. A run cannot be paused on the web (Stop works), and **Use in chat** for a writing model is on
the desktop only for now.

## Examples

- Teach the app my mascot from the set of pictures I added.
- Start the training for the style set "Ink".

## Problems

- **Add at least 8 pictures** Add more, 15 to 25 good ones is plenty.
- **Write the descriptions first** Choose Write the descriptions on the screen.
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
5. Choose Teach it. It takes about a minute on a Mac and chat and image making pause.
6. The result is in My models. Ask both the original and your taught model something new with Ask both.
7. To chat with it, choose **Use in chat** under the result (or under it in My models). The first time the app asks to
   download the same model in the form the chat engine runs (shown first). Choose **Back to my chat model** to
   return to the model chat used before.

To use a different model or to take more care, open **Choose the model and method** (closed by default, with the
recommendation). It lists Qwen3 0.6B (small and quick), 1.7B and 4B (they follow the examples more closely and take
longer), and Quick or Better. One that is not on this computer has **Get it** next to its name, with its size;
nothing is fetched until you press it.

### Fields

- `set_id`: Instead of `dataset_id`: the set of examples to teach a language model from. It needs at least 10
  examples.

### Limits

- One run at a time: a run holds most of the GPU and the one big-model slot, so other models are put away.
- The models it is taught on are small (Qwen3 0.6B, 1.7B or 4B, 4-bit): they copy how the examples answer and can
  still answer wrongly about facts.
- Examples in English work best; the base model reads other languages but this has not been measured.

### Needs

- A Mac with Apple silicon, the trainer and its small model (set up in the app), a little free disk space.

### Examples

- Teach it from the set of examples "Customer replies".

### Problems

- **Add at least 10 examples** Add more questions and answers; 50 or more is better.
- **A model is being taught** Wait for it to finish or stop it.
- **Training is not set up on this computer yet** Choose Download and set up on the Train screen.

---

## Teaching it to decide (the same action, with `decision_set_id`)

### What it is for

Show a model texts with the right answer to one question about them, and it learns to answer that question about
new texts, and to say how sure it is. The answer is yes or no, one of your categories, or a score. It is taught on
this computer and your texts are not sent anywhere. Afterwards the screen reports how often it was right on texts
it had not seen, beside a plain word counter, where it went wrong, and whether its confidence can be trusted.

### Steps in the app

1. Open **Train models** and, under **Decision model training**, choose **Teach it to decide**.
2. The first time, the app offers to set up the trainer and a small model (about 1 GB, shown first); nothing is
   fetched until you press the button.
3. Choose New set of examples. Write the question and choose yes or no, a category or a score. Add a text and the
   right answer for each, or paste two columns from a spreadsheet. At least 20 are needed; 60 or more is a good start.
4. Read the check: it leaves out empty and repeated rows and rows whose answer is not one of the options, and warns
   about thin or lopsided answers, texts that appear twice with different answers, long texts and personal data.
5. Choose Teach it. It takes a minute or two on a Mac; chat and image making pause.
6. Read the report, then choose **Try it** or **Sort a list**. The model is kept in My models, about 840 MB.

To use the model for many languages or to take more care, open **Choose the model and method** (closed by default).
All of the model is taught; it is not taught as a small adapter.

### Fields

- `decision_set_id`: Instead of `dataset_id`: the set of texts and answers to teach a decision model from. It needs the
  question and at least 20 examples with at least two different answers.

### Limits

- One run at a time, and not while a picture or writing model is being taught.
- A run needs about 13 GB of free memory. Each model it makes takes about 840 MB on disk.
- Only English (or the many-languages model) is read; texts are read up to about 2,000 characters.

### Needs

- A Mac with Apple silicon, the trainer (PyTorch and Laya, set up in the app) and about 3 GB of free disk space.

### Examples

- Teach it to decide from the set "Support messages".

### Problems

- **Add at least 20 examples** Add more texts with their answers; 60 or more is better.
- **Every example has the same answer** Add examples with the other answers too.
- **A model is being taught** Wait for it to finish or stop it.

---

## Teaching the video model a look or a motion (the same action, with a video set)

### What it is for

Teach the video model a character, a style or a motion of your own from pictures and short clips. You only add
them: the app checks each one, writes a description of each, suggests a magic word and teaches the model, on this
computer. Afterwards the result is a **look**: choose it under **My looks** on a Make a video, Animate a picture or
Extend a video screen, and write its magic word in the prompt. A person's likeness is only partly kept, so do not
expect a face to come back exactly; a style or a motion works best.

### Steps in the app

1. Open **Train models** and, under **Video model training**, choose **Make my own look or motion for video**.
2. The first time, the app offers to set up the video trainer (about 180 MB, shown first); nothing is fetched until
   you press the button. The video model itself (the one the Video screens use, about 16 GB) must already be on this
   computer: if it is not, the screen says so and where to get it (**Select video model** on a Video screen).
3. Add pictures and short clips: a few pictures and 5 to 15 clips of 2 to 10 seconds is plenty, at least 8 in all.
   Each is marked Good, Too short, Too small, Too dark, Blurry, Still or Looks like a copy.
4. Say what it is, give it a name, choose the magic word, and read the descriptions.
5. Choose Teach it. It takes about half an hour on a Mac with 64 GB, and chat, image and video making pause.
6. The result is in My models. Choose it on a Video screen under **My looks** (up to two at once, each with its own
   strength; 1.5 is a good start).

### Fields

- `dataset_id`: The set made for video. It must have at least 8 pictures or clips, a description for each and a
  magic word. `base` and `method` can be left out (LTX-Video 2B, as a small adapter).

### Limits

- One run at a time, across every kind of model.
- The video model taught is LTX-Video 2B 0.9.5 only: a look made for it does not work with another video model.
- A run needs about 10 GB of free memory for clips at 768 by 512; a Mac with 16 GB has not been tried.
- The descriptions are in English.

### Needs

- A Mac with Apple silicon, the video trainer (PyTorch with diffusers, set up in the app), the video model and its text
  encoder on this computer, and about 3 GB of free disk space for the trainer and the result.

### Examples

- Teach the video model my character from the video set "Ena".

### Problems

- **The video model is not on this computer yet** Choose Select video model on a Video screen.
- **That set is for the video model, not the picture model** The set was made for video; start it from the video card.
- **Add at least 8 pictures or clips** Add more.
