---
action: motion.set_project
screen: motion
synonyms: [change the shape, make it square, make a vertical version, rename the project, write all the scenes, first version from a brief]
---
# Change the whole project

Action: `motion.set_project`

## What it is for

Change a video project's name, shape or letters, or replace all its scenes at once, as the assistant does when it turns a brief into a first version.

## Steps in the app

1. Open the project in **Motion graphics**.
2. Change the name or the shape in the bar at the top, or ask the assistant.

## Fields

- `composition_id`: The project.
- `name`: The project's name.
- `shape`: landscape, portrait or square.
- `font`: sans or serif.
- `soundtrack`: Music for the whole video: a file of the project by its id, with volume, start and loop.
- `scenes`: All the scenes in order, replacing the ones there now.

## Limits

- Up to 30 scenes and 90 seconds in all.

## Needs

- Nothing else: the change is only written down. Motion graphics must be set up to make the video.

## Examples

- "Make a square version."

## Problems

- A scene or project that does not fit is refused, and the message says what to change. Nothing changes until it is right.
