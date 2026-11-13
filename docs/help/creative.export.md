---
action: creative.export
screen: creative
synonyms: [export the music video, save the music video, keep the video, save to my videos, export as mp4, save a copy of the video]
---
# Keep a music video in Your videos

Action: `creative.export`

## What it is for

Save a project's finished video to Your videos, where it is a video like any other: it can be played, renamed,
searched, saved as a file or deleted there. If the cut changed since the last video was made, it is made first.

## Steps in the app

1. Open **Creative Studio**, open a project and go to **Cut**.
2. Choose **Make the video** at the top right. It is saved to Your videos when it is done.
3. **Save a copy** writes the last one kept as an MP4 file, where you choose to keep it if asked.

## Fields

- `project_id`: The project.
- `title`: What the video is called. Left out, the project's name.

## Limits

- Every time is a new video; the ones kept before stay in Your videos.
- The same sizes and times as `creative.cut`.

## Needs

- A project with at least one still.

## Examples

- Export the music video.
- Save it to my videos as "Dawn drive".

## Problems

- *The video could not be kept.* There may be no room left on the disk. Free some space and try again.
