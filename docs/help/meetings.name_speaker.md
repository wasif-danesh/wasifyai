---
action: meetings.name_speaker
screen: meetings.list
synonyms: [name a speaker, who is speaker 1, rename speaker, label speaker, speaker name, this is me, is this asha, suggested speaker, who is this voice]
---
# Name a speaker

Action: `meetings.name_speaker`

## What it is for

Give a speaker of a meeting their name, so the transcript says "Asha" instead of "Speaker 1". The name
is used in the transcript, in the saved text and in search. The speaker becomes that person in
**Meetings › People** (one already there with that name, or a new one) and their voice is kept, so a
later meeting suggests them.

## Steps in the app

1. Open **Meetings › View meetings** and open the meeting.
2. Under Speakers, choose the speaker. Listening from one of their lines helps to tell who it is.
3. Type their name, or choose one of the people listed, and choose Save. An empty name gives back
   Speaker N and forgets what naming them taught.
4. When the app suggests someone ("Is this Asha?"), choose Yes to name them, or No: the app remembers
   that it is not her and does not suggest her for that voice again.

## Fields

- `meeting_id`: The meeting.
- `speaker`: The speaker's key in that meeting: `S1`, `S2` and so on.
- `name`: Their name.

## Limits

- The app never names a speaker by itself, and an assistant should not guess a name from what was said.
  A suggestion is only a suggestion: voices from the same room sound alike, and in tests one person in
  four was suggested wrong from a room microphone.
- Suggestions need the voiceprint model (about 26 MB, in Models). Without it the names are kept, but no
  one is suggested.

## Needs

- A finished meeting.

## Examples

- Speaker 2 in the budget meeting is Ravi.
- Call Speaker 1 of the interview "Me".

## Problems

- **That meeting or speaker is not there** The meeting was deleted, or the key is not one of its
  speakers.
