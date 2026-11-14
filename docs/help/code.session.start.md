---
action: code.session.start
synonyms: [coding session, start coding, open a project, open my code, look at my code, code agent, coding agent, read my codebase, new coding session, open a folder for the agent]
---
# Start a coding session

Action: `code.session.start`

## What it is for

Open one project's folder for the coding agent. In this version every session only reads: the agent can
find and read the files of that folder, and it cannot change a file or run a command. Starting a session
reads nothing yet and starts nothing. The agent begins when you send it a message.

## Steps in the app

The coding screens are not built yet. Until they are, a session is started by asking the assistant in the
chat, for example "Start a coding session on /Users/me/Projects/bakery-site". The assistant shows a card
first, and nothing happens before you say yes.

## Fields

- `folder`: The project's folder on this computer, as a whole path. The agent may read this folder and
  nothing else of yours.
- `title`: A name for the session. Left empty, the folder's name is used.
- `model`: The model to work with. Left empty, the first choice is used (Claude Sonnet 5.5, with your own
  Anthropic key).
- `cost_limit_usd`: The most this session may cost, in US dollars. 0 uses the usual limit of 5 dollars.

## Limits

- One folder per session. Choose a project's folder, not your whole home folder or a disk.
- Some folders cannot be opened: the app's own folders, your Library, and hidden folders at the top of
  your home folder (such as `.ssh`). They hold keys and settings the agent must never read.
- The agent cannot change or run anything in this version. Editing with undo, and running commands, come
  in later versions.
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
