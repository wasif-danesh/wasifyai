---
action: music.analyse
screen: creative
synonyms: [find the beats, beat detection, tempo of a song, bpm, downbeats, song sections, time the lyrics, when are the lines sung, analyse a song]
---
# Find the beats of a song

Action: `music.analyse`

## What it is for

Work out what a music video needs to know about a song in Your music: its tempo, every beat and
downbeat, where its sections start and end and how loud each one is, and when each typed line is
sung. The answer is kept with the song, so asking again is instant. Sections have no names such as
verse or chorus: the tool gives where they change and how loud they are, nothing more.

## Steps in the app

1. Open **Creative Studio**.
2. Choose **New project**, pick a song and type its words if you have them.
3. Choose **Plan it**. The song is analysed first, as the first step of the plan.

## Fields

- `track_id`: The song in Your music.
- `lyrics`: The words of the song, typed. Left out, the words the song was made with are used.
  Speech recognition only finds when they are sung. It never changes them.

## Limits

- Beat times come from beat_this on the computer's processor; a 90 second song takes a few seconds.
- A steady song gives steady beats. On a song with a loose rhythm the beats can be uneven, and nobody
  has checked them against a person tapping along.
- Line times work in the languages the speech model knows, in practice English today. Bengali gets
  its words but no times. Lines with no times still appear in the plan.

## Needs

- Music analysis set up (a download of about 970 MB, shown before it starts). Only Apple-silicon Macs
  for now.
- A speech model only for line times; without one the beats still work.

## Examples

- Find the beats of my song "Drive home".
- What is the tempo of this track, and when does the first line start?

## Problems

- **Set up music analysis first** The download has not been done. Creative Studio offers it, with its
  size.
- **The lines have no times** The speech model could not follow the words in fewer than a quarter of
  the lines. The plan still works; place the words yourself.
- **Song not found** The song was deleted, or belongs to another account.
