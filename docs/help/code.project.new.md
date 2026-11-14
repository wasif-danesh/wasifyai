---
action: code.project.new
screen: code.projects
synonyms: [new project, start a new app, make a web app, new coding project, start from scratch, empty folder, scaffold a project, create a website]
---
# Start a new coding project

Action: `code.project.new`

## What it is for

Make a new project in a new, empty folder, and open a coding session on it. You name the project and choose the
folder it is made in. Wasify AI writes a starter's files there, sets the project's check and its preview, and
the agent can go on from your first message.

The starter today is **a small web app**: one page with its script and its styles, tests, and a preview that
loads again when a file changes. It has no build step and nothing to install.

## Steps in the app

1. Open **Code › Projects** and choose "Start in a new, empty folder".
2. Give the project a name. It becomes the name of the new folder.
3. Choose the folder it is made in, then "Make the project".
4. The session opens. Ask for what you want built; open the Preview tab to see it run.

You can also ask the assistant in the chat: "Start a new web app called bakery-site in ~/Projects".

## Fields

- `parent`: The whole path of a folder that exists. The new project's folder is made inside it.
- `name`: The project's name: letters, digits, spaces, dots, dashes and underlines, up to 64 characters.
- `starter`: What to start from. `web` is the small web app.
- `model`: The model to work with. Left empty, the first choice is used.

## Limits

- One starter for now.
- A folder of that name that already holds files is refused. Nothing in it is changed.
- The app's own folders, your Library and hidden folders of your home folder cannot hold a project.
- The starter needs Node. If your own Node is in your home folder (nvm and the like), the agent cannot read
  it there: set up "Node for coding projects" in Settings, under Optional parts.

## Needs

- The coding engine set up (Settings, under Optional parts), and a model that is ready.
- Node for coding projects (Settings, under Optional parts), or a Node in a system folder.

## Examples

- Start a new web app called bakery-site in /Users/me/Projects.
- Make a new project named "Tax Shop" in my Projects folder.

## Problems

- **The folder already holds files** Choose another name.
- **There is no folder at that path** Choose a folder that exists to make the project in.
- **Give the project a name of letters, digits, spaces, dots, dashes or underlines** Use a plain name.
