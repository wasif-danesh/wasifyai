---
action: code.extension.switch
screen: code.extensions
synonyms: [switch a skill on, enable a skill, turn off a skill, disable an extension, enable code review, use a skill]
---
# Switch an extension on or off

Action: `code.extension.switch`

## What it is for

Switch a skill on or off for one coding project. A skill that is on is offered to the agent in that project, and its text is used when your message is about it.

## Steps in the app

1. Open **Code › Extensions** and choose the project at the top.
2. Use the switch on a row. Or choose "Details" to read its text first; the same switch is there for each of your projects.

You can also ask the assistant in the chat.

## Fields

- `session_id`: A coding session of the project.
- `extension_id`: The extension's id, from `code.extension.list`.
- `on`: True switches it on, false off.

## Limits

- A change holds from a session's next message. A turn that is running keeps the skills it started with.
- When the skills of a project change, the agent begins a new conversation with the next message and is given the last answer to go on from.
- A skill is text. It can steer how the agent works; it cannot widen what the agent may do.

## Needs

- The coding engine set up (Settings, under Optional parts). The public skills come with it.

## Examples

- Switch the code review skill on for the bakery site.
- Turn off "Explain in plain words" for this project.

## Problems

- **There is no such extension** Ask for the list first; an id looks like `own:explain-in-plain-words`.
- **There is no SKILL.md in that folder** Choose the folder that holds the file itself.
- **Coding is not available** Set up the coding engine in Settings, under Optional parts.
