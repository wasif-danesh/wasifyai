---
action: creative.make_shots
screen: creative
synonyms: [make the stills, draw the shots, make pictures for my plan, make a picture for every shot, draw the plan, see the plan as pictures, go on with the stills]
---
# Make the stills of a plan

Action: `creative.make_shots`

## What it is for

Make a picture for every shot of a plan that has none, as one job. Each picture is saved the moment it is
made and goes into your Library, tagged with the project and the shot.

## Steps in the app

1. Open **Creative Studio**, open a project and choose **Make the stills**.
2. Read what it will take: how many stills, how long, how much of the disk.
3. Keep **From reference pictures**, or choose **Plain** to go about twice as fast.
4. Choose **Start**. Choose **Stop** at any time: what was made is kept, and **Go on** makes only what is missing.

## Fields

- `project_id`: The project.
- `mode`: `reference` (the default) keeps faces steadier; `plain` takes about half the time.
- `redo_out_of_date`: Also make again the stills whose shot changed.

## Limits

- A 3-minute song has about 48 shots: about 30 minutes from reference pictures, about 15 plain, on a fast Mac.
- Reference pictures hold a face well enough for a draft, not for someone who must be recognised every time.
- A person seen only in photos is never drawn as there in person.
- A shot's Animate or Sing shows as a still until the Cut step.
- Every still is a picture in your Library. A 48-shot project adds 48 pictures.

## Needs

- A project with a plan, and a picture model. Reference pictures use a model that can take two pictures.

## Examples

- Make the stills for my dawn drive project.
- Draw every shot of this plan.

## Problems

- *Stops with "The picture model is not ready".* Choose a picture model with the model button at the top.
- *Stops after three failures in a row.* Something is wrong with the model; what was made is kept.
- *Refused for room on the disk.* Make room, then start again.
