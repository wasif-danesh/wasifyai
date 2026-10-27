---
action: library.export
screen: library
synonyms: [download, save as, export, copy out]
---
# Save a copy to a folder

Action: `library.export`

## What it is for

Put a copy of a creation in the export folder so other programs can use it. The library keeps the original. This is the only way a file leaves the library.

## Steps in the app

1. Open **Library** and choose the creation.
2. Choose Save, then pick the file type if asked.

## Fields

- `kind`: Which sort of creation.
- `id`: Its id.
- `folder`: For another app connected to Wasify AI: the full path of a folder that connection may save into (Settings › Other apps). Left out, your own export folder.

## Limits

- A copy never replaces a file: a second copy gets a number.
- Voices cannot be saved as files.

## Needs

- An export folder (the app sets one; the default is Downloads).

## Examples

- Save that picture to my folder.

## Problems

- **Saving to a folder is not available** Set the export folder in the app, then try again.
