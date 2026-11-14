---
action: code.session.start
screen: code.projects
synonyms: [coding session, start coding, open a project, open my code, look at my code, code agent, coding agent, read my codebase, new coding session, open a folder for the agent]
---
# Start a coding session

Action: `code.session.start`

## What it is for

Open one project's folder for the coding agent. A session has one of three modes, shown in the box you
write in:

- **Plan**: the agent only reads. It can find and read the files of that folder and cannot change one.
- **Ask me**: the agent also changes files. Before it changes a file that Undo cannot put back (one your
  project ignores, such as `.env`), it asks you. You can answer yes, no, or "Allow for this project".
- **Work on its own**: the agent changes files and does not ask.

In every mode the agent cannot leave the folder, cannot reach the internet and cannot run a command. Every
turn that changed files can be undone in the Changes tab. Starting a session reads nothing yet and starts
nothing. The agent begins when you send it a message.

## Steps in the app

1. Open **Code › Projects** and choose "Choose a folder".
2. Pick the folder of one project in the computer's folder window.
3. The session opens. Nothing is read until you ask something.

You can also ask the assistant in the chat ("Start a coding session on /Users/me/Projects/bakery-site"); it
shows a card first.

## Fields

- `folder`: The project's folder on this computer, as a whole path. The agent may read this folder and
  nothing else of yours.
- `title`: A name for the session. Left empty, the folder's name is used.
- `model`: The model to work with. Left empty, the first choice is used (Claude Sonnet 5.5, with your own
  Anthropic key).
- `cost_limit_usd`: The most this session may cost, in US dollars. 0 uses the usual limit of 5 dollars.
- `mode`: `plan`, `ask` or `own`. Asked through the assistant, a session only reads (`plan`) unless you
  say otherwise. A session you open on the Code screen starts in "Ask me".

## Limits

- One folder per session. Choose a project's folder, not your whole home folder or a disk.
- Some folders cannot be opened: the app's own folders, your Library, and hidden folders at the top of
  your home folder (such as `.ssh`). They hold keys and settings the agent must never read.
- The agent cannot run a command, a test or a program in this version, and it cannot delete a file. Running
  commands comes in a later version.
- Undo does not put back files your project ignores (such as `.env`) or changes inside a `.git` folder.
  That is why "Ask me" asks before the agent changes one.
- Only on Apple-silicon Macs for now.

## Needs

- The coding engine set up: Settings, under Optional parts, "Coding engine (OpenHands)", about 375 MB.
- For Claude Sonnet 5.5: your own Anthropic key, saved in Settings under Your keys (the key for Chat and
  writing is used).

## Examples

- Start a coding session on /Users/me/Projects/bakery-site.
- Open my project in ~/Projects/shop-api for the coding agent and call it "Checkout bug".

## Problems

- **There is no folder at that path** Give the whole path of a folder that exists.
- **Choose one project's folder, not the whole home folder or a disk** Pick the folder of one project.
- **That folder holds the app's or the system's own files** Pick another folder.
- **No key is saved for Claude Sonnet 5.5** Save an Anthropic key in Settings, under Your keys.
- **The coding engine is not set up yet** Set it up in Settings, under Optional parts.
