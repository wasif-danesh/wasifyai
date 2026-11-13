---
action: motion.add_scene
screen: motion
synonyms: [add a scene, new scene, one more scene, add an end card]
---
# Add a scene

Action: `motion.add_scene`

## What it is for

Add one scene to a video project, at the end or at a position you choose. A project made from one template becomes a project of scenes, and Undo turns it back.

## Steps in the app

1. Open the project in **Motion graphics**.
2. Under **Add**, choose what the scene is, or choose **+ Add a scene**.
3. Write its words.

## Fields

- `composition_id`: The project.
- `kind`: title, quote, chart, lower_third, end_card or captions.
- `fields`: Its words and settings.
- `name`: A short name for the scene.
- `position`: Where it goes, from 0. At the end if not given.

## Limits

- Up to 30 scenes and 90 seconds in all.

## Needs

- Nothing else: the change is only written down. Motion graphics must be set up to make the video.

## Examples

- "Add an end card that says Try Northbean."

## Problems

- A scene or project that does not fit is refused, and the message says what to change. Nothing changes until it is right.
