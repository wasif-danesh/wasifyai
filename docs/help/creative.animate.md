---
action: creative.animate
screen: creative
synonyms: [animate the shots, make the shots move, draft the motion, make it better, make clips of the shots, see the motion]
---
# Animate a music video's shots

Action: `creative.animate`

## What it is for

Turn the stills of a project into short moving clips. A **draft** animates about 30 seconds of the song quickly and
softly, so you can see the motion before spending more time. **Make it better** animates the shots the plan marks
Animate at the final setting, sharp. Each clip is used for its shot, and the still stays as another version.

## Steps in the app

1. Open **Creative Studio**, open a project and go to **Shots**.
2. Under **Motion**, choose where the 30 seconds start (the loudest part is chosen for you), then **Draft 30 seconds**.
3. Watch them in the preview or the cut. Then choose **Make it better** for the shots marked Animate.
4. To make one shot's clip, select the shot and choose **Make a clip**.

## Fields

- `project_id`: The project.
- `quality`: `draft` (the default) or `final`.
- `start`: Draft only: where the 30 seconds start, in seconds. The loudest part when left out.
- `shot_id`: Only this shot, made again even when it has a clip.

## Limits

- A clip is 5 seconds; a shorter shot uses its start.
- On a Mac with 64 GB a draft clip took about 50 seconds and a final one about 3 minutes (30 seconds of song as a draft,
  about 7 minutes). The time shown before you start is corrected by the first clip made on your computer.
- Shots marked Sing are not animated: lip sync comes later.
- Only one video, set of stills or clips is made at a time. Stop keeps the clips made, and going on makes only the rest.

## Needs

- The stills of those shots, and the video model (Models).

## Examples

- Animate a bit of it so I can see the motion.
- Now make the animated shots properly.

## Problems

- *These shots have no stills yet.* Make the stills first.
- *These shots already have their clips.* Choose another start, or select a shot and make its clip again.
