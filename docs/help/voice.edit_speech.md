---
action: voice.edit_speech
screen: voice.edit
synonyms: [change words, fix a word, edit a recording]
---
# Edit speech

Action: `voice.edit_speech`

## What it is for

Change some of the words a recording says, keeping the voice.

## Steps in the app

1. Open **Voice › Edit speech**.
2. Choose the recording; its words are shown.
3. Change the words and choose Edit.

## Fields

- `old_text`: What it says now.
- `text`: What it should say.

## Limits

- 1,000 characters.

## Needs

- A speech-editing model (Models).

## Examples

- Change 'meet at noon' to 'meet at one'.

## Problems

- **Nothing to change** The new words must differ from the old.
