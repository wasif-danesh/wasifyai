---
action: music.separate
screen: music.separate
synonyms: [stems, isolate vocals, karaoke, remove vocals]
---
# Split into parts

Action: `music.separate`

## What it is for

Split a recording into its parts (voice, drums, bass, other); each part is saved.

## Steps in the app

1. Open **Music › Split into parts**.
2. Choose a recording.
3. Choose the parts to keep.
4. Choose **Split the song**. Each part plays where it appears and is kept in the Library.

## Fields

- `source_kind`: track or speech.
- `source_id`: The recording.
- `stems`: Which parts, or all.

## Limits

- Recordings up to an hour.

## Needs

- A separation model (Models).

## Examples

- Give me just the vocals of that song.

## Problems

- **No such part** That model does not make that part; choose from the list.
