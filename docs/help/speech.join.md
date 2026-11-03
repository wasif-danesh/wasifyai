---
action: speech.join
screen: creative
synonyms: [join speech, put speeches together, one narration, narrate a story, join recordings, combine speech, voices one after another]
---
# Join speech

Action: `speech.join`

## What it is for

Put speeches from the library one after another, with a short pause after each, and keep them as one
recording in Your music. Each speech can be a different voice, so a story can have a narrator and
characters. It says where each part starts and ends, so pictures and captions can follow the words.
Creative Studio uses it for a story: it speaks each line, then joins them.

## Steps in the app

1. Open **Creative Studio**.
2. Choose **New project**, then **A story**, write the story and choose the voices.
3. Choose **Plan it**. The story is read aloud and joined before the plan is written.

## Fields

- `parts`: The speeches in order, each with `speech_id` and `pause` (seconds of quiet after it, 0 to 5).
- `title`: What the recording is called in Your music.
- `text`: What it says, so search finds it.

## Limits

- Up to 400 speeches. The result is one channel at 24 kHz.
- The speeches stay in the library; the joined recording is a new song in Your music.

## Needs

- Nothing to download: it only joins what is already made.

## Examples

- Join these three speeches into one narration called "The key".

## Problems

- **A speech to join is no longer there** One of the speeches was deleted. Make it again.
