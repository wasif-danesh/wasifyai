---
action: audiobook.make
screen: voice.audiobook
synonyms: [audiobook, read a book, narrate a book]
---
# Make an audiobook

Action: `audiobook.make`

## What it is for

Read a long text aloud, one track per chapter, optionally one track of the whole.

## Steps in the app

1. Open **Voice › Audiobook**.
2. Paste the text and check the chapters.
3. Choose a voice.
4. Choose Make. It can take a long time and keeps each chapter as it is done.

## Fields

- `text`: The book.
- `title`: A name.
- `whole`: Also one track of everything.
- `voice`: A built-in voice.
- `saved_voice`: A saved voice.

## Limits

- Up to 400,000 characters.
- One track of the whole is for books up to about two hours.

## Needs

- A speech model (Models).

## Examples

- Read this story as an audiobook.

## Problems

- **Stopped halfway** Chapters already done are kept in your library.
