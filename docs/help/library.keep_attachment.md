---
action: library.keep_attachment
synonyms: [edit this photo, use the picture I attached, save this photo, keep the attachment, work on this file]
---
# Keep an attached file

Action: `library.keep_attachment`

## What it is for

Save a picture you attached in the chat to your library, so the chat can work on it: change it, make it move, make it
talk, turn it into a 3D model, use it as a reference. The chat does this first, then proposes what you asked for.

## Steps in the app

1. In the chat, press **+** and attach a picture, then say what to do with it ("make the sky a sunset").
2. The chat proposes keeping the picture; confirm the card. It shows in **Library** with your other pictures.
3. The chat then proposes the change itself; confirm that card too.

On the screens, **Images › Edit** and the other screens have their own upload or Import button instead.

## Fields

- `attachment_id`: The attachment's id, as the chat names it.
- `title`: A name for it in the library; its file name when left out.

## Limits

- Pictures up to 10 MB. A picture is stored again as a clean PNG without its metadata.
- An attachment that was not used is removed after a day; attach it again then.

## Needs

- Nothing. The chat model does not need to be able to look at pictures to keep one.

## Examples

- Make the sky in this photo a sunset.
- Make this photo move.
- Save this photo to my library.

## Problems

- **The attachment is not there any more** Attach the file again.
- **This computer cannot keep an attached file of that kind** The product that keeps it is not installed.
