---
action: code.extension.list
screen: code.extensions
synonyms: [extensions, skills, list skills, what skills are there, coding skills, agent skills, plugins]
---
# List the coding agent's extensions

Action: `code.extension.list`

## What it is for

See which skills the coding agent can be taught and which are on for a project. A skill is a short text that tells the agent a way of working: how to explain something in plain words, how to review a change, how to write tests first. With one extension named you get the whole text it gives the agent, to read before you switch it on.

## Steps in the app

1. Open **Code › Extensions**.
2. Choose the project at the top ("For"). Each row says whether it is on for that project.
3. Choose "Details" on a row to read its text.

You can also ask the assistant in the chat.

## Fields

- `session_id`: A coding session. Says for its project whether each extension is on.
- `extension_id`: One extension, to read its whole text.

## Limits

- The list is short on purpose: Wasify AI's own, a few of the public OpenHands catalogue, and what you added.
- Everything listed is already on this computer. Nothing is fetched from the internet.

## Needs

- The coding engine set up (Settings, under Optional parts). The public skills come with it.

## Examples

- Which extensions does the coding agent have?
- Show me what the code review skill tells the agent.

## Problems

- **There is no such extension** Ask for the list first; an id looks like `own:explain-in-plain-words`.
- **There is no SKILL.md in that folder** Choose the folder that holds the file itself.
- **Coding is not available** Set up the coding engine in Settings, under Optional parts.
