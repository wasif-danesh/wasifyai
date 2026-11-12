---
action: notebook.add_source
screen: notebook.list
synonyms: [add a source, add a note, add text, add this file to my notebook]
---
# Add a note to a notebook

Action: `notebook.add_source`

## What it is for

Add a text note, or a document you attached in the chat, as a source of a notebook. Web pages are added in the app.

## Steps in the app

1. Open **Notebook › View notebooks** and choose the notebook.
2. Add a source and choose a note.

## Fields

- `notebook_id`: The notebook.
- `title`: A name for the note; for an attached document, its first line when left out.
- `content`: The text.
- `attachment_id`: Instead of `content`, a document attached in the chat.

## Limits

- Up to 1,000,000 characters per note. An attached document gives the words the chat read from it (up to 200,000
  characters); for a whole long PDF with its pages, add the file in the notebook itself.

## Needs

- Notebooks to be set up.

## Examples

- Add my budget numbers as a note.

## Problems

- **Still being read** Wait a moment before asking about it.
