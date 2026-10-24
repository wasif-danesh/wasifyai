---
action: video_builder.lint
screen: motion
synonyms: [check a video, is it safe, check the project]
---
# Check a video project

Action: `video_builder.lint`

## What it is for

Check that a video project reaches nothing outside its own folder: no pictures or scripts from the
internet, no files from elsewhere on the computer. Making a video runs it in a locked box and does
this check first.

## Steps in the app

1. Open **Motion graphics**.
2. Open a project.
3. Choose Check (it also runs by itself before every video is made).

## Fields

- `composition_id`: The project, as shown in the list.

## Limits

- It checks the project's own files. It is a first check, not the only protection: the render
  itself cannot reach the internet or other services on the computer.

## Needs

- Motion graphics set up (Motion graphics).

## Examples

- Check the project "Launch day".

## Problems

- **Motion graphics is not set up** Open **Motion graphics** and choose Set up.
- **That video project does not exist** It may have been deleted.
