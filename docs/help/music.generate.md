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
2. Describe the style and mood.
3. Add lyrics if you want singing, or choose instrumental.
4. Choose the length and Create.

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

- **Model missing** Open **Models** and get a music model.
- **Takes a while** Longer pieces take minutes; it keeps working in the background.
