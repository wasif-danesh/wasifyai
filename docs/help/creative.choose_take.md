---
action: creative.choose_take
screen: creative
synonyms: [use the earlier picture, go back to the first take, choose a take, use this take, which picture is used]
---
# Choose which version of a shot is used

Action: `creative.choose_take`

## What it is for

Choose which still or clip of a shot is used in the preview. Nothing replaces the chosen one unless you ask.

## Steps in the app

1. Open **Creative Studio**, open a project and go to **Shots**.
2. Select a shot.
3. Choose one of the versions under its picture.

## Fields

- `project_id`: The project.
- `shot_id`: The shot.
- `take_id`: The take.

## Limits

- A shot has versions once it has been made more than once, or something was added or made for it in the panel.

## Needs

- A shot with a take.

## Examples

- Use the first picture of this shot again.

## Problems

- *The picture is gone.* It was deleted from your Library; the shot shows as having no picture.
