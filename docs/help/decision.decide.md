---
action: decision.decide
screen: train
synonyms: [teach it to decide, decision model, decide, yes or no, is it positive, sort my messages, sort into categories, label my texts, classify, tag my texts, score a text, how sure is it, spam or not spam, triage, which team, rate a text]
---
# Decide with a model I taught

Action: `decision.decide`

## What it is for

Ask a model you taught under **Teach it to decide** to answer its question about one or many texts. The question was
chosen when it was taught: yes or no ("Is this review positive?"), one of several categories ("billing, bug or
other?") or a score ("how angry, 1 to 5"). Each text comes back with its answer and how sure the model is. It
runs on this computer, quickly, and nothing is sent anywhere. It is for sorting and flagging things, not for
deciding about a person's job, credit or safety.

## Steps in the app

1. Open **Train models** and, under **Decision model training**, choose **Teach it to decide**.
2. Choose New set of examples. Write the question and choose the kind of answer: yes or no, a category (name each
   one and say what it means) or a score (say what the lowest and the highest mean).
3. Add examples: a text and the right answer for each. Type them, or paste two columns from a spreadsheet. At least
   20 are needed; 60 or more is a good start, and at least 5 of each answer.
4. Read the check. Choose Teach it. It takes about a minute or two on a Mac.
5. Read the report: how often it was right on texts it had not seen, beside a plain word counter, where it went
   wrong and whether its confidence can be trusted.
6. Choose **Try it** to paste a text and see its answer and how sure it is, beside the model it started from. Choose
   **Sort a list** to paste or open many texts and see every answer.

## Fields

- `model_id`: The decision model to ask (its id is in the library).
- `texts`: The texts to decide about, up to 100. Each is answered on its own.

## Limits

- It answers the one question it was taught, in the way it was taught: a model taught to sort messages into
  billing, bug and other cannot answer a different question.
- The confidence is the model's own, checked on texts kept back when it was taught: the report says how far to trust it.
- Texts are read up to about 2,000 characters; the rest is cut.
- It cannot run while another model is being taught, because both need the one big-model slot.
- Laya reads English, or more than 100 languages with the other Laya; the choice is made when it is taught.

## Needs

- A decision model taught on this computer, the trainer's environment (set up on the Train screen) and a few
  seconds to load the model.

## Examples

- Is this review positive? "The battery lasts all day."
- Which team should handle these 30 messages?

## Problems

- **That decision model does not exist** Choose one from My models, or teach one first.
- **A model is being taught** Wait for it to finish or stop it.
- **The taught model's files are gone** The model was taken off this computer. Teach it again.
- **Training is not set up on this computer yet** Choose Download and set up on the Train screen.
