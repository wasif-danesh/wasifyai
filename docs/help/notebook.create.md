---
action: notebook.create
screen: notebook.create
synonyms: [new notebook, start a notebook, make a notebook from this file, notebook from these documents]
---
# Create a notebook

Action: `notebook.create`

## What it is for

Make a notebook, then add sources to it. In the chat, attach documents and ask for a notebook from them: they become
its first sources.

## Steps in the app

1. Open **Notebook › Create**.
2. Give it a name.

## Fields

- `title`: A name, up to 200 characters.
- `attachment_ids`: Up to 4 documents attached in the chat, to add as its first sources.

## Limits

- Nothing.

## Needs

- Notebooks to be set up.

## Examples

- Make a notebook called Trip to Lisbon.
- Make a notebook from these two PDFs and give me a summary.

## Problems

- **Limit reached** Delete a notebook you no longer need.
