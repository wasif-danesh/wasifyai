---
action: code.extension.add
screen: code.extensions
synonyms: [add a skill, add an extension, import a skill, my own skill, skill from a folder, install a skill, SKILL.md]
---
# Add an extension from a folder

Action: `code.extension.add`

## What it is for

Add a skill you have in a folder of this computer. A folder is a skill when it has a file called `SKILL.md`: a few lines that name it and say what it is for, then the text for the agent. Wasify AI copies the folder in and shows you its text before it is switched on anywhere.

## Steps in the app

1. Open **Code › Extensions** and choose "Add from a folder".
2. Pick the folder. You are shown what was found and the whole text.
3. Choose whether to switch it on for the project at the top, then "Add the skill".

You can also ask the assistant in the chat.

## Fields

- `folder`: The whole path of a folder that holds a `SKILL.md`.
- `session_id`: A coding session. The skill is switched on for its project.

## Limits

- The folder is copied; your own folder is not changed, and changes you make to it later are not picked up. Remove it and add it again to bring them in.
- A folder of at most 5 MB and 200 files. Links in it are not followed.
- A plugin (a folder with `.plugin/plugin.json`, which can bring hooks and tool connections) cannot be added yet.
- Two skills cannot have the same name.

## Needs

- The coding engine set up (Settings, under Optional parts). The public skills come with it.

## Examples

- Add the skill in /Users/me/Documents/house-style.
- Add my house style folder as a skill and switch it on for the bakery site.

## Problems

- **There is no such extension** Ask for the list first; an id looks like `own:explain-in-plain-words`.
- **There is no SKILL.md in that folder** Choose the folder that holds the file itself.
- **Coding is not available** Set up the coding engine in Settings, under Optional parts.
