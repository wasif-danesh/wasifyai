---
action: motion.move_scene
screen: motion
synonyms: [move a scene, reorder scenes, put this scene first, change the order]
---
# Move a scene

Action: `motion.move_scene`

## What it is for

Move one scene earlier or later in a video project.

## Steps in the app

1. Ask the assistant to move the scene.
2. Choose Make the video to see it in its new place.

## Fields

- `composition_id`: The project.
- `scene_id`: The scene.
- `position`: Where it goes, from 0.

## Limits

- A position past the end puts the scene last.

## Needs

- Nothing else: the change is only written down. Motion graphics must be set up to make the video.

## Examples

- "Put the quote first."

## Problems

- A scene or project that does not fit is refused, and the message says what to change. Nothing changes until it is right.
