---
action: code.session.send
synonyms: [ask the coding agent, analyse this codebase, explain my code, map of the project, where is this in the code, plan a change, code question, read my project, how does this code work]
---
# Ask the coding agent

Action: `code.session.send`

## What it is for

Send a message to a coding session and get the agent's answer. Use it to understand a project ("analyse
this codebase", "where are the prices worked out?") or to get a plan for a change. The agent finds and
reads the files it needs. It changes nothing.

## Steps in the app

The coding screens are not built yet. Until they are, ask the assistant in the chat, for example "Ask the
coding session to analyse this codebase". The assistant shows a card first, because the agent reads your
files and, with a cloud model, sends what it reads to that model's provider.

## Fields

- `session_id`: The coding session, from `code.session.start`.
- `text`: What to ask, in plain words.

## Limits

- One message at a time per session. A second message while the agent works is refused: stop the turn or
  wait for it.
- A turn stops after 60 tool steps and says so.
- With a cloud model, the parts of files the agent reads leave this computer and go to the model's
  provider. The model's key never reaches the coding engine.
- The session's cost is counted call by call. At the session's limit the turn stops and says so.
- When the model declines a request, the turn ends with the model's own words. It is not an error.
- After the app has been closed and opened again, the agent does not remember the session's earlier
  messages; the turn says so.

## Needs

- A coding session, and the coding engine set up (Settings, under Optional parts).
- For Claude Sonnet 5.5: your own Anthropic key, saved in Settings under Your keys.

## Examples

- Ask the coding session: analyse this codebase.
- Ask it where the opening hours are shown, and what would have to change to say "Closed today" on Mondays.

## Problems

- **The agent is still working on the last message** Stop it or wait for it to end.
- **This session reached its cost limit** Start a session with a higher limit.
- **The model declined this request** Ask in another way, or ask something else.
- **The coding engine stopped answering** Send the message again. If it happens again, repair the coding
  engine in Settings, under Optional parts.
