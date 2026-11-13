---
action: music.generate
screen: music.create
synonyms: [compose, make a song, make music, music generation, sound effect]
---
# Make music

Action: `music.generate`

## What it is for

Make a piece of music, a song with words, or a sound effect and keep it in your library.

## Steps in the app

1. Open **Music › Create**.
2. Describe the style and mood; the style chips under the box add or take out a word.
3. Write or paste lyrics in the Lyrics panel (**Write them for me** uses the chat model), or tick
   **No singing (instrumental)**.
4. Choose the length and **Make the song**. Tempo, key, seed and how many are under **For experts**.
5. The song plays where it appears with its lyrics: **Save a copy**, **Make it again** (the same seed) and
   **Another take** are under it, and **Change a part**, **Split into parts**, other formats, favourites,
   **Rename** and **Delete** are in **More**. Recent music lists what you made.

## Fields

- `description`: Style and mood in a few words.
- `lyrics`: The words, with [verse] and [chorus] lines.
- `instrumental`: No singing.
- `seconds`: 5 to 120.

## Limits

- 500 characters of description, 5,000 of lyrics.
- 5 to 120 seconds.

## Needs

- A music model (Models).

## Examples

- Calm piano, rainy evening.
- Upbeat pop about summer, 60 seconds.

## Problems

- **Model missing** Open **Model hub** and get a music model.
- **Takes a while** Longer pieces take minutes; it keeps working in the background.
