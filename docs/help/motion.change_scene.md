---
action: motion.change_scene
screen: motion
synonyms: [change a scene, shorten a scene, edit scene, change the words of a scene, make it longer]
---
# Change a scene

Action: `motion.change_scene`

## What it is for

Change the words, length or look of one scene. Give only what changes; the rest of that scene and the other scenes stay as they are.

## Steps in the app

1. Open the project in **Motion graphics** and choose the scene.
2. Change it on the right. It saves by itself, and the preview follows.

## Fields

- `composition_id`: The project.
- `scene_id`: The scene.
- `fields`: Only the fields that change.
- `name`: A new name for the scene.
- `caption`: Words along the bottom of the scene.
- `transition`: How the scene starts: none, fade or slide.

## Limits

- Shape and letters are set for the whole project, not for one scene.

## Needs

- Nothing else: the change is only written down. Motion graphics must be set up to make the video.

## Examples

- "Make scene 2 four seconds long."

## Problems

- A scene or project that does not fit is refused, and the message says what to change. Nothing changes until it is right.
