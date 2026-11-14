---
action: code.session.undo
screen: code.projects
synonyms: [undo the agent's changes, undo this turn, revert the coding agent, put my files back, roll back the agent, undo coding changes, restore my project]
---
# Undo a coding turn

Action: `code.session.undo`

## What it is for

Put a project's files back to how they were before a turn of the coding agent. Every file the turn changed
goes back, every file it added is removed, and every file it deleted returns, with the same content and the
same permissions. If your project uses git, where your branch points and what you had staged go back too.

## Steps in the app

1. In **Code › Projects**, open the session.
2. Open the **Changes** tab. It lists each turn that changed files, with every file before and after.
3. Choose "Undo this turn".

To get the changes back, choose "Bring it back" on the undone turn. You can also ask the assistant in the
chat: "Undo what the coding agent just changed".

## Fields

- `session_id`: The coding session.
- `turn_id`: The turn to undo. Left empty, the newest turn that changed files is undone.

## Limits

- One turn at a time, the newest first. To undo an earlier turn, undo the later ones first.
- Not while the agent is working. Stop it or wait.
- Files your project ignores (such as `.env`, `node_modules` or build output) are not kept and not put back.
- If you changed files yourself after the turn, those changes go back with it. "Bring it back" returns
  them. The result says when this happened.
- An undone turn can be brought back only until a later turn changes files.

## Needs

- A coding session with a turn that changed files.

## Examples

- Undo what the coding agent just changed.
- Undo the last turn of the bakery site session.

## Problems

- **Only the newest turn that changed files can be undone** Undo the later turns first.
- **The agent is working** Stop it or wait, then try again.
- **No turn of this session can be undone** No turn changed a file, or all of them are undone already.
