---
action: library.delete
screen: library
synonyms: [delete, remove, get rid of]
---
# Delete a creation

Action: `library.delete`

## What it is for

Delete one creation and its files for good. It cannot be undone, so the app always asks you first.

## Steps in the app

1. Open **Library** and choose the creation; it opens large, with what it is.
2. Choose **Delete** (under **More** when it is not shown) and confirm.
3. To delete several at once, choose **Select**, tick them, then **Delete** and confirm.

## Fields

- `kind`: Which sort of creation.
- `id`: Its id.

## Limits

- Always needs your yes in the app window. A video that is still being made cannot be deleted.

## Needs

- Nothing.

## Examples

- Delete that picture.

## Problems

- **Still being made** Wait until the video is ready, then delete it.
