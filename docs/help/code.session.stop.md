---
action: code.session.stop
screen: code.projects
synonyms: [stop the coding agent, stop coding, cancel the agent, interrupt the agent, stop the session, stop reading my code]
---
# Stop the coding agent

Action: `code.session.stop`

## What it is for

Stop what a coding session is doing. It takes effect at once, whatever the agent is doing: starting up,
waiting for the model or reading files. The session stays, and you can send it another message.

## Steps in the app

1. In **Code › Projects**, open the session that is working.
2. Choose Stop, in the box you write in.

You can also ask the assistant in the chat: "Stop the coding session".

## Fields

- `session_id`: The coding session.

## Limits

- Stopping a session that is not working does nothing.
- What the model had already been sent is not taken back, and its cost so far is counted.

## Needs

- A coding session.

## Examples

- Stop the coding session.
- Stop the agent that is looking at the bakery site.

## Problems

- **There is no such coding session** Check the session, or start a new one.
