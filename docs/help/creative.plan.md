---
action: creative.plan
screen: creative
synonyms: [music video, plan a music video, video for my song, shot list, storyboard, plan shots, cut to the beat, make a video from a song, creative studio]
---
# Plan a music video

Action: `creative.plan`

## What it is for

Turn a song and an idea into a plan you can change: the cuts follow the beats, and each shot says what
is seen, who is in it, where, how the camera moves and whether it holds or moves. Only words are made at
this stage, no pictures or clips. Your typed lyrics stay exactly as you wrote them.

## Steps in the app

1. Open **Creative Studio**.
2. Choose **New project**. Pick a song from Your music, say what the video is about, and add the look,
   the people and the places. Type the song's words if you have them. Choose the shape and how fast it
   cuts.
3. Choose **Plan it**. You can stop at any time and go on later from where it stopped.
4. Read the plan, then change it: see `creative.edit_plan`.

## Fields

- `brief.track_id`: The song in Your music.
- `brief.idea`: What the video is about.
- `brief.style`: The look, in your own words.
- `brief.cast`: The people, each with a `name`, fixed words for how they look (`look`) and
  `photos_only` when they are only ever seen in photographs.
- `brief.places`: The places, in the order the story visits them.
- `brief.lyrics`: The words of the song, typed.
- `brief.shape`: landscape, portrait or square.
- `brief.cut_speed`: From -2 (few long shots) to 2 (many short ones). 0 is the middle.
- `title`: A name for the project.

## Limits

- The time depends on the chat model you chose. Measured on an M5 Pro with Qwen3-8B: 44 s for a 3-minute
  song, 31 to 49 s for a 90 second one. A 27B model on Ollama took about 9 minutes for 90 seconds.
- The writing is a first draft. Details can drift from shot to shot, and some lines cannot be filmed;
  expect to change some of them. A shot the model could not write gets plain words and a mark, so you
  can see which ones to rewrite.
- Changing how fast it cuts means planning again.
- At this stage nothing is drawn. Shots and the cut come in later stages.
- Desktop only for now.

## Needs

- Music analysis set up (about 970 MB, shown before it starts).
- A language model, chosen with the model button.
- A song in Your music.

## Examples

- Plan a music video for my song "Drive home": a woman drives home along the coast at dawn.
- Make a shot list for this track, vertical, with fast cuts.

## Problems

- **The plan stopped when the app closed** It keeps what it had. Open the project and choose **Go on**.
- **Choose a language model first** The plan is written by the model you chose.
- **It is very slow** Choose a smaller chat model with the model button; 8B is the size it was measured on.
- **Some shots are marked plain** The model's sentence did not pass the checks, so the shot says what the
  beat says. Rewrite it, or choose **Try another idea** on that part.
- **A plan is already being made** One plan at a time. Wait for it or stop it.
