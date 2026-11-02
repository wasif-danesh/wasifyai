---
action: video.keep
screen: creative
synonyms: [keep a finished video, save a made video to my videos, add a video from another product]
---
# Keep a finished video

Action: `video.keep`

## What it is for

Save a finished video that another product made, such as the cut of a Creative Studio project, to Your videos as a
new video with a poster frame. It is searchable by its title.

## Steps in the app

1. In **Creative Studio**, a project's **Make the video** uses this. The video then shows in **Your videos**.

## Fields

- `from_kind`: The kind of creation whose video it is, such as `creative_project`.
- `from_id`: Its id.
- `title`: What the video is called.

## Limits

- Up to 2 GB.
- It is always a new video; nothing kept before is replaced.

## Needs

- A finished video in that creation. For a Creative Studio project, its cut made with `creative.cut`.

## Examples

- Keep the music video in my videos.

## Problems

- *There is no finished video there yet.* Make the video first.
- *That is not a video that can be played.* The file could not be read as a video.
