---
action: code.session.preview
screen: code.projects
synonyms: [preview my project, run my app, start the dev server, see the result, show the site, run the project, stop the preview, open the app]
---
# Start or stop a project's preview

Action: `code.session.preview`

## What it is for

Run a coding project on this computer and see it. The preview starts the project's own command (for example
`npm run dev`) inside the same protected area as the agent's commands, finds the port it listens on, and shows
the page in the session's Preview tab.

## Steps in the app

1. In **Code › Projects**, open the session.
2. Open the **Preview** tab and choose "Start the preview". The command is suggested from the project's files;
   "Change the command" lets you type another.
3. The page appears in the tab. Choose the phone shape to see it narrow, "Load again" to load it again, the
   arrow to open it in your own browser, and "Stop" to end it.

You can also ask the assistant in the chat: "Start the preview of the bakery site".

## Fields

- `session_id`: The coding session.
- `do`: `start` (the default), `stop`, or `state` to only say where it is.
- `command`: The command that starts the project. Left out, the one that is set, or the one the project's
  files suggest.

## Limits

- One preview for each session. Starting again stops the one that runs.
- It runs inside the project's protected area: it can write only inside the project, cannot read your other
  folders, and reaches the internet only to install packages.
- The page is served from this computer. If the program listens on every address of this computer, other
  computers on your network can open it too; the tab says so when that is the case.
- The page is loaded again when a turn changes files. A tool that reloads by itself also does.
- A preview stops when the session is deleted or the app is closed.

## Needs

- A coding session, and the tools the command uses where the protected area can find them (for Node: the
  optional part "Node for coding projects").

## Examples

- Start the preview of the bakery site session.
- Stop the preview.

## Problems

- **npm was not found** Set up "Node for coding projects" in Settings, under Optional parts.
- **Nothing in the project's files says how to start it** Give the command.
- **The preview has ended** The tab shows its exit code and the end of what it printed.
