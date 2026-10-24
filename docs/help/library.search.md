---
action: library.search
screen: library
synonyms: [find, search, where is, look for, my pictures, my songs]
---
# Search my creations

Action: `library.search`

## What it is for

Find something you made earlier by what it was about: a picture, a video, a song, a speech, a transcript, a voice or a notebook.

## Steps in the app

1. Open **Library**.
2. Type a few words about what you remember in the search box.
3. Choose a result to open it.

## Fields

- `query`: What to look for, in your own words.

## Limits

- Two or more characters.
- It searches names, prompts, titles and the start of transcripts, not the inside of documents (use `notebook.search` for that).

## Needs

- Nothing. Search by meaning works better when the search model is installed (**Model hub**).

## Examples

- Find the song I made about the rain.
- Which teapot picture did I make last week?

## Problems

- **Nothing is found** Try other words, or choose a kind to browse the newest ones instead (`library.list`).
