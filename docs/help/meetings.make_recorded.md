---
action: meetings.make_recorded
screen: meetings.record
synonyms: [record a meeting, record a call, record my call, meeting recorder, microphone and computer sound, zoom call, teams call, google meet, waiting recording, recorded meeting]
---
# Record a meeting

Action: `meetings.make_recorded`

## What it is for

Record a call or a meeting on this computer and make it into a meeting: your microphone is recorded as
You, and the computer's sound (the people on the call) as everyone else, who are then told apart as
Speaker 2, Speaker 3 and so on. The assistant cannot start a recording; you start and stop it. It can
make a meeting from a recording that is waiting.

## Steps in the app

1. Open **Meetings › Record**. Choose the language of the meeting if the model needs it.
2. Choose Start recording. The first time, your computer asks to allow the microphone and, on a Mac,
   Screen & System Audio Recording for Wasify AI.
3. While it records, the time and a meter for You and for Others are shown, and the menu bar shows a
   red dot with the time. Any problem is said in words (the microphone gives no sound, the computer's
   sound is not allowed).
4. Choose Stop, here or in the menu bar. The meeting is made and opens.
5. A recording that could not be made into a meeting (the speaker model was missing, the app was closed)
   waits under Recordings not made into a meeting: make it into one or throw it away.

## Fields

- `name`: The recording's name (`rec-….wav`). Without one, the newest waiting recording is used.
- `title`: A name for the meeting. Without one it is called Recorded meeting.
- `language`: The language spoken, when the chosen speech model needs to be told it.

## Limits

- Your side is one speaker, You, whoever speaks into the microphone.
- The computer's sound is told apart into up to four speakers.
- With speakers rather than headphones, the microphone also hears the call; words heard on both sides
  at nearly the same moment are kept only once, on the call's side.
- Recording the computer's sound needs macOS 14.2 or later, or Windows. On Linux only the microphone is
  recorded.

## Needs

- The speaker model and a speech-to-text model, both from Models, to make the meeting. Recording needs
  neither: a recording waits until they are there.

## Examples

- Make a meeting from the call I just recorded.
- Make my last recording into a meeting called Weekly sync.

## Problems

- **There is no recording waiting** Record one in Meetings › Record first.
- **The microphone gives no sound** Allow Wasify AI in System Settings › Privacy & Security ›
  Microphone, then start again.
- **The computer's sound is not allowed** Allow Wasify AI in System Settings › Privacy & Security ›
  Screen & System Audio Recording, then start again.
