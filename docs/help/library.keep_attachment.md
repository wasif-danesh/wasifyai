---
action: library.keep_attachment
synonyms: [edit this photo, use the picture I attached, save this photo, keep the attachment, work on this file, dub this video, transcribe this recording, extend this clip]
---
# Keep an attached file

Action: `library.keep_attachment`

## What it is for

Save a picture, a recording or a video you attached in the chat to your library, so the chat can work on it: change a
picture, make it move, make it talk, turn it into a 3D model; write out, dub, split or change the voice of a recording;
carry on a video or dub it. The chat does this first, by itself when it is plainly needed, then proposes what you asked
for.

## Steps in the app

1. In the chat, press **+** and attach a picture, a recording or a video, then say what to do with it ("make the sky a
   sunset", "dub this into French").
2. The chat keeps the file in your **Library**: a picture with your pictures, a recording in **Your music**, a video
   with your videos (or, for dubbing and writing out, its sound in **Your music**).
3. The chat then proposes what you asked for; confirm the card.

On the screens, **Images › Edit** and the other screens have their own upload or Import button instead.

## Fields

- `attachment_id`: The attachment's id, as the chat names it.
- `title`: A name for it in the library; its file name when left out.
- `as_kind`: What to keep it as when it could be more than one: `track` (the sound of a recording or a video) or
  `video`. Left out, a picture is kept as a picture, a recording as a song and a video as a video.

## Limits

- Pictures up to 10 MB. A picture is stored again as a clean PNG without its metadata.
- Recordings up to 50 MB and 10 minutes, kept as a WAV. Videos up to 200 MB and 2 minutes, kept as a clean MP4 with
  its sound. A video kept as a video for **Extend video** may be at most 30 seconds.
- An attachment that was not used is removed after a day; attach it again then.

## Needs

- Nothing. The chat model does not need to be able to look at pictures to keep one. Recordings in other formats than
  WAV, and videos, need FFmpeg, which comes with the app.

## Examples

- Make the sky in this photo a sunset.
- Make this photo move.
- Save this photo to my library.

## Problems

- **The attachment is not there any more** Attach the file again.
- **This computer cannot keep an attached file of that kind** The product that keeps it is not installed.
