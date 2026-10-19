---
action: notebook.studio_output
screen: notebook.list
synonyms: [report, quiz, flashcards, slides, mind map, study guide, audio overview]
---
# Make a Studio output

Action: `notebook.studio_output`

## What it is for

Make a report, study guide, flashcards, quiz, mind map, Word or PDF file, slides, data table, audio overview or infographic from a notebook's sources.

## Steps in the app

1. Open **Notebook › View Notebooks** and choose the notebook.
2. In Studio choose the kind of output.
3. Add a focus if you want one and Make.

## Fields

- `notebook_id`: The notebook.
- `format`: The kind of output.
- `prompt`: What to focus on.

## Limits

- At least one ready source.

## Needs

- The chat model; some outputs need more models.

## Examples

- Make a quiz from my Biology notebook.

## Problems

- **Add a source first** The notebook has no sources yet.
