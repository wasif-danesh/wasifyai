---
action: meetings.make
screen: meetings.list
synonyms: [meeting, meeting notes, transcribe a meeting, who said what, speakers, tell the speakers apart, diarization, diarisation, call recording, interview, minutes]
---
# Make a meeting from a recording

Action: `meetings.make`

## What it is for

Turn a recording of a meeting, a call or an interview into a meeting: who spoke when, and what they
said. The speakers are told apart on this computer, and the words are written down with the
speech-to-text model you chose. The meeting is kept in Meetings and can be found in search.

## Steps in the app

1. Open **Meetings › View meetings**. The first time, open Models and get the speaker model (about
   490 MB; the size is shown before it starts), and choose a speech-to-text model if you have none.
2. Choose New meeting from a file and pick a sound or video file of the meeting.
3. It is made in the background: reading the recording, telling the speakers apart, writing it down.
   You can leave the screen.
4. Open the meeting. Choose a speaker to give them a name, choose a time to play from there, or choose
   Save as text.

## Fields

- `source_kind`: `track` (a sound you imported or made) or `speech`.
- `source_id`: The id of the recording in the library.
- `title`: A name for the meeting. Without one, the recording's name is used.
- `language`: The language spoken, when the chosen speech model needs to be told it (Bengali, Hindi
  and the other Indian languages).

## Limits

- Up to four speakers are told apart in one recording. With more people, some are joined together.
- One meeting is made at a time. A meeting of an hour takes a few minutes on a recent Mac.
- A stretch where two people talk at once goes to the one who spoke more of it.
- The speakers are called Speaker 1, Speaker 2 and so on until you name them. Names are not guessed.
- To record a meeting in the app, use Meetings › Record (`meetings.make_recorded`). People (voices it
  knows again), reports and asking questions come later.

## Needs

- The speaker model (about 490 MB) and a speech-to-text model, both from Models. Works on the
  processor; nothing is sent anywhere unless the chosen speech model is a cloud one.

## Examples

- Make a meeting from the recording of this morning's stand-up.
- Who said what in my interview recording?

## Problems

- **Get the speaker model first** Open Models and get Sortformer 4 speakers.
- **A meeting is being made** Wait for it to finish, or open it and choose Stop.
- **That recording could not be read** Use a sound or video file, or save it as a WAV file.
- **It was stopped when the app closed** Make it again from the recording.
