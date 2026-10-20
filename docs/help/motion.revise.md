---
action: motion.revise
screen: video.builder
synonyms: [change the video, fix the typo, use another look, change the lower third, edit the chart, change the colours, undo]
---
# Change a motion graphic

Action: `motion.revise`

## What it is for

Change a project you made with Video Builder and make the video again. Give only what changes: the
rest stays as it was. The new words are checked against what you typed before anything is drawn. The
earlier version is kept, and **Undo the last change** on the Video Builder screen brings it back
(the last 20 changes are kept).

## Steps in the app

1. Open **Video › Video Builder** and open the project.
2. Change the words or the look in the form.
3. Choose Make the video. Use Undo the last change if you prefer how it was.

## Fields

- `composition_id`: The project to change.
- `fields`: Only the fields that change, as for Make a motion graphic.
- `format`: mp4, webm or mov, as the template allows.
- `render`: Set to false to change the project without making the video again.

## Limits

- A change always asks you first when an assistant proposes it.
- Twenty earlier versions are kept for each project; older ones are dropped.

## Needs

- Video Builder set up and about 3 GB of free memory, to make the video again.

## Examples

- Use the forest look for the project "Launch day".
- Fix the spelling of the name in a lower third.

## Problems

- **The length must be between 3 and 12 seconds** Choose a length in the range the message names.
- **The project does not exist** It may have been deleted; open Video Builder to see what is left.
- **The words on the screen are not exactly what you wrote** The change was kept but no video was
  made; change the words and try again, or choose Undo.
