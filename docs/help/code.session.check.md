---
action: code.session.check
screen: code.projects
synonyms: [run the tests, set the check, change the check command, check my project, run the project's check, test command, what is the check, try the check now]
---
# Set or run a project's check

Action: `code.session.check`

## What it is for

A project's check is one command, such as `npm test` or `python3 -m pytest`. After every turn in which the
coding agent changed files, Wasify AI runs it. If it fails, the agent gets the command, its exit code and the
end of the output, and tries again, up to three rounds. The session then says one of four words: passed,
failed, not checked, or could not check.

Use this to see which check is set, to set or change it, and to run it now.

## Steps in the app

1. In **Code › Projects**, open the session.
2. Choose the check's word in the bar at the top (for example "Not checked"), or "Change the check" on a
   check card in the chat.
3. Type the command, or choose one of the suggestions read from the project's files.
4. Choose "Try it now" to run it, then "Save the check".

You can also ask the assistant in the chat: "Set the check of the bakery site to npm test and run it".

## Fields

- `session_id`: The coding session.
- `command`: The check command. Left out, the one that is set is kept. An empty text removes the check.
- `run`: Run the check now and wait for its result. On unless you say otherwise.

## Limits

- One command for each project. Build, lint and test as separate steps are not built yet.
- The check runs inside the project's sandbox: it can write only inside the project, cannot read your other
  folders, and does not reach the internet.
- A check is stopped after 10 minutes unless you change that. A check that was stopped, that could not start
  or whose command was not found is never counted as passed.
- Not while the agent is working. Stop it or wait.
- The check is kept by Wasify AI, outside the project, where the agent cannot change it.

## Needs

- A coding session.

## Examples

- Set the check of this project to `npm test`.
- Run the check of the bakery site session now.
- What is the check for this project?

## Problems

- **Could not check** The command was not found, took too long, or crashed. Change the check, or install what
  it needs in the Terminal tab.
- **This project has no check yet** Set one first.
- **The agent is working** Stop it or wait, then try again.
