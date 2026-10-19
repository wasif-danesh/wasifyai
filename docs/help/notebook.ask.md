---
action: notebook.ask
screen: notebook.list
synonyms: [ask my documents, chat with a notebook, question about my sources]
---
# Ask a notebook

Action: `notebook.ask`

## What it is for

Ask one notebook a question; the answer comes from its sources only, with numbered citations.

## Steps in the app

1. Open **Notebook › View Notebooks** and choose the notebook.
2. Type the question in the chat.

## Fields

- `notebook_id`: The notebook.
- `question`: The question.
- `document_ids`: Only these sources.
- `conversation_id`: Continue a conversation.

## Limits

- 4,000 characters.

## Needs

- Ready sources and the chat model.

## Examples

- What is the budget in the Budget notebook?

## Problems

- **Sources are still being read** Try again in a moment.
