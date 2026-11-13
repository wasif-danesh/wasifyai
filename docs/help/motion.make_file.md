---
action: motion.make_file
screen: motion
synonyms: [make a picture for this scene, add a voiceover, narrate this scene, make background music, generate a clip for the video, word timed captions, make a voiceover with captions]
---
# Make something for a video project

Action: `motion.make_file`

## What it is for

Make a picture, a clip, a voiceover or music with the app's own models and add it to a Motion graphics project, without leaving the editor. It is also kept in your Library.

## Steps in the app

1. In the Motion graphics editor, choose Make in the tools on the left.
2. Choose Picture, Clip, Speech or Music, and say what you want.
3. For a picture, choose whether it goes behind the scene or on it. For speech, choose a voice and whether to show the words as captions.
4. Choose Make. You can keep working while it is made. It lands on the scene you had selected, or under the whole video for music, and one Undo takes it off again.

## Fields

- `composition_id`: The project.
- `what`: `picture`, `clip`, `speech` or `music`.
- `text`: For speech, the exact words to say. Otherwise, what it shows or sounds like.
- `seconds`: About how long, for a clip or music.
- `voice`: A saved voice's id, for speech.
- `use`: Where it goes: `background`, `place`, `sound`, `soundtrack`, or `none` to only add the file.
- `scene_id`: The scene it is for.
- `captions`: For speech, show the words as captions, in time with the speech.

## Limits

- Captions show the words exactly as you typed them. Speech to text only says when they were said; where no speech to text model is installed, the lines are timed by how far through the words they are.
- Timed captions belong to the scene's voiceover and go when it goes. Choose Type them instead to write your own.
- A scene grows to fit its voiceover, up to the longest that kind of scene can be. A longer voiceover is cut off when the scene ends.
- Captions from a sound you uploaded yourself are not made.
- A file already in the project can be used without making anything: use `motion.change_scene`.

## Needs

- The model for what you make: a picture model, a video model, a speech model or a music model. If one is missing, you are told which step to take.

## Examples

- "Add a voiceover to this scene saying Try it today, with captions."
- "Make a picture of a red can on marble and put it behind this scene."
- "Make some warm acoustic music for the whole video."

## Problems

- Refused: the words say why, usually that the model is not installed or is busy. Nothing is added.
- "It was made, but could not be used here": it is in your Library; the file did not pass the same checks as an upload.
