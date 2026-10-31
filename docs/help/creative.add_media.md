---
action: creative.add_media
screen: creative
synonyms: [add to the project, use this picture in the video, add from the library, put this in the project]
---
# Add to a project

Action: `creative.add_media`

## What it is for

Make a picture, clip, song, speech, lip sync, 3D model or motion graphic from the Library part of a project in Creative Studio, so it shows in that project's media rail. Nothing is copied: it stays in the Library.

## Steps in the app

1. Open the project in **Creative Studio**.
2. Select a shot, if it is meant for one.
3. Open the **Add** tab and choose the thing.

## Fields

- `project_id`: The project.
- `kind`: `image`, `video`, `track`, `speech`, `lipsync`, `model3d` or `composition`.
- `item_id`: The thing in the Library.
- `shot_id`: The shot it is meant for, if any.

## Limits

- Dropping in a file from outside the Library comes with the Shots step.
- Being in the rail does not put a thing in the video yet: the Shots and Cut steps do that.

## Needs

- The thing in your Library.

## Examples

- Add a picture of the red barn to shot 3.

## Problems

- "That is not in the library": it was deleted.
