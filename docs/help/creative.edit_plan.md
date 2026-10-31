---
action: creative.edit_plan
screen: creative
synonyms: [change a shot, edit the plan, rewrite a shot, move a cut, delete a shot, add a shot, change the motion, undo a plan change]
---
# Change a plan

Action: `creative.edit_plan`

## What it is for

Change the plan of a project in Creative Studio: what a shot shows, whether it holds, animates or sings,
its place or camera; remove or add a shot; move a cut by whole beats. The plan stays whole: the shots
still cover the song from start to end, and only people of the cast appear. Each change can be undone.

## Steps in the app

1. Open **Creative Studio** and open a project.
2. Change the words of a shot, its motion or its place. Use the arrows to move a cut by one beat, or
   remove or add a shot.
3. Choose **Undo** to take a change back.

Or ask in the **Ask** tab: select a shot and say what should change. The change applies at once, and its card
has its own **Undo**.

## Fields

- `project_id`: The project.
- `edits`: The changes, in order. Each has `op`: `set_shot` (with `shot_id` and the fields to change),
  `delete_shot` (`shot_id`), `add_shot` (`after`, a shot's id, and `shows`) or `move_cut` (`shot_id` and
  `by_beats`, a whole number; the cut at the end of that shot moves).

## Limits

- A change that would break the plan is refused as a whole, and nothing changes.
- Cuts move by whole beats, so they stay on the music. Dragging comes later.
- Changing how fast it cuts means planning again.

## Needs

- A project with a plan.

## Examples

- In my dawn drive project, make shot 3 animate.
- Move the cut after shot 5 one beat later and remove shot 6.

## Problems

- **That would leave a shot with no length** A cut cannot move past the next one. Move it fewer beats.
- **The last shot ends with the song** The end of the last shot cannot move.
- **There is no plan to change yet** Plan the project first.
