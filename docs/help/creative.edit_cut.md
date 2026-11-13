---
action: creative.edit_cut
screen: creative
synonyms: [change the cut, move a piece, make a shot longer, shorten a shot, split a shot, fade in, take out a piece, move a caption, change the words on screen, add a title, add a lower third, turn captions off]
---
# Change a music video's cut

Action: `creative.edit_cut`

## What it is for

Change the cut of a project: the order of its pieces, how long each is, where it splits, where it fades, and the
captions and titles drawn over it. The pictures and the song are not changed: the cut only refers to them.

## Steps in the app

1. Open **Creative Studio**, open a project and go to **Cut**.
2. Choose a piece in the timeline at the bottom. Use **Longer** and **Shorter** (one beat each), **Split**, **Fade in**,
   **Move left**, **Move right** or **Take out**.
3. Choose a caption in the caption row to change its words or move it by a beat. Add titles and lower thirds from the
   **Titles** tab, and captions from the singing from the **Voice** tab.
4. **Undo** and **Redo** are next to the timeline. Keys: Z undoes, Shift+Z redoes, S splits, the arrow keys move the
   chosen piece or caption by a beat.

## Fields

- `project_id`: The project.
- `edits`: The changes, in order. Pieces: `move` (`item_id`, `to`), `length` (`item_id`, `by_beats`), `split`
  (`item_id`), `fade` (`item_id`, `fade`), `remove` (`item_id`). Captions: `caption` (`caption_id`, `text`,
  `by_beats`), `add_caption` (`kind`: line, title or lower; `text`, `start`, `end`), `remove_caption` (`caption_id`),
  `captions` (`on`).

## Limits

- A piece is at least half a second long, and lengths move on the song's beats.
- If the pieces end before the song, the rest of the video is black; the screen says how many seconds.
- One change that cannot be made refuses them all, and nothing changes.
- The last 30 changes can be undone.
- Changing the plan's shots is `creative.edit_plan`. A cut made before the plan changed keeps its pieces; the screen
  says so, and **Start again from the plan** makes the cut afresh.

## Needs

- A project with a plan.

## Examples

- Make the third shot two beats longer.
- Fade into the chorus shot.
- Add the title "Dawn drive" for the first two seconds.

## Problems

- *The video is being made.* Wait for it, or stop it, then change the cut.
- *A caption must start before it ends, inside the song.* Give it a start and end within the song's length.
