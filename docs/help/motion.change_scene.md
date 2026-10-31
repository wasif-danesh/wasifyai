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
3. To move its words, choose **Arrange** above the preview and drag them, or use **Where the words go**.

## Fields

- `composition_id`: The project.
- `scene_id`: The scene.
- `fields`: Only the fields that change.
- `name`: A new name for the scene.
- `caption`: Words along the bottom of the scene.
- `transition`: How the scene starts: none, fade or slide.
- `arrange`: Where its parts go: for each part, x, y and w as percent of the picture, and scale. Empty puts them back as designed.

## Limits

- Shape and letters are set for the whole project, not for one scene.
- Keep words inside the dashed line when arranging, or the video will not be made.

## Needs

- Nothing else: the change is only written down. Motion graphics must be set up to make the video.

## Examples

- "Make scene 2 four seconds long."

## Problems

- A scene or project that does not fit is refused, and the message says what to change. Nothing changes until it is right.
