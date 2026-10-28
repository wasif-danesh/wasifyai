---
action: video_builder.render
screen: motion
synonyms: [make the video, render, export video, make it]
---
# Make the video

Action: `video_builder.render`

## What it is for

Make the video of a Motion graphics project. First every word on the screen is checked against what
you typed; if one is wrong the video is not made and the message says which. Then it is drawn frame
by frame in a locked box, saved as an MP4 (or WebM or MOV, which keep a clear background) and kept
in the Library. It takes seconds to a minute for a short video and only one is made at a time.

## Steps in the app

1. Open **Motion graphics**.
2. Open a project.
3. Choose a file kind if the template offers more than one, then Make the video; watch the
   progress (checking the words, then drawing), or leave the screen.
4. Choose Save a copy to keep the file, or find it in the Library.

## Fields

- `composition_id`: The project to make.
- `format`: mp4, webm or mov, as the template allows (a title, quote or chart is an MP4).

## Limits

- One video at a time. Choose Cancel to stop one that is running; nothing is kept.
- A video that asks for too much memory or takes too long is stopped, and the screen says so.

## Needs

- Motion graphics set up (Motion graphics; FFmpeg is part of it) and enough free memory (about
  3 GB).

## Examples

- Make the video of "Launch day".

## Problems

- **The words on the screen are not exactly what you wrote** Nothing was drawn. Change the words
  and try again.
- **A video is already being made** Wait for it to finish or cancel it.
- **Not enough memory** Close other apps, or choose a shorter, smaller video.
- **Motion graphics needs FFmpeg** This should not happen: FFmpeg comes with Motion graphics. If it does,
  run `brew install ffmpeg` in Terminal, then choose Check again.
- **Motion graphics is not set up** Open **Motion graphics** and choose Set up.
