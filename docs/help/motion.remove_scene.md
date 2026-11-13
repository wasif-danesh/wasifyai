---
action: motion.remove_scene
screen: motion
synonyms: [remove a scene, delete a scene, take out a scene, drop this scene]
---
# Remove a scene

Action: `motion.remove_scene`

## What it is for

Take one scene out of a video project. Undo brings it back.

## Steps in the app

1. Open the project in **Motion graphics** and choose the scene.
2. Choose **Remove**. Undo brings it back.

## Fields

- `composition_id`: The project.
- `scene_id`: The scene to remove.

## Limits

- A project keeps at least one scene. To delete the whole project, delete it from the Library.

## Needs

- Nothing else: the change is only written down. Motion graphics must be set up to make the video.

## Examples

- "Take out scene 3."

## Problems

- A scene or project that does not fit is refused, and the message says what to change. Nothing changes until it is right.
