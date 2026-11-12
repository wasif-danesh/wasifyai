# Everything from the chat: the measurement (CE0, 2026-11-12)

Stage CE0 of `docs/chat-does-everything-plan.md`: how well the chat does each menu item today, before any of the plan is
built, so the stages can be ordered by what fails most.

## How it was measured

- **Cases:** 74 `menu-*` cases in `products/wasifyai-assistant/evals/cases.yaml`, for the 26 menu items that make or change
  something. Each item has a plain ask ("make a picture of a fox"), and, where it makes sense, an ask with a file attached
  ("make the sky in this photo a sunset" with `beach.jpg`) and a follow-up on what the chat made just before ("now make it
  move", sent after the earlier ask, the proposal and the action's own sentence, as the app words them).
- **Runner:** `run_tool_eval.py --only menu`. Attachments are given to the model through the app's own `user_content`;
  the runner refuses what the app refuses (a recording or a clip until CE2). A case passes when the model's first action is
  the right one with the right library id or words in its params.
- **Model:** the desktop's local default, Qwen3 8B Q4_K_M, on the app's own llama-server, with no picture reader. By the
  owner's choice the work spends nothing, so Haiku 5.5 was not measured; CE8 can run it with a key.

## The baseline (before CE1)

22 of 74 passed: plain asks 13 of 26, asks with an attachment 1 of 22, follow-ups 8 of 26. Loading took 2.1 s, a case
1.5 s at the median.

| Menu item | Passed | Menu item | Passed |
|---|---|---|---|
| images.create | 2/3 | voice.speak | 0/3 |
| images.edit | 0/3 | voice.transcribe | 0/3 |
| images.inpaint | 0/3 | voice.convert | 0/3 |
| images.reference | 0/3 | voice.voices | 2/3 |
| video.create | 2/2 | voice.edit | 0/3 |
| video.animate | 1/3 | voice.dub | 0/3 |
| video.extend | 0/3 | voice.audiobook | 2/3 |
| model3d | 1/3 | voice.lipsync | 0/3 |
| music.create | 2/3 | notebook.create | 1/3 |
| music.lyrics | 1/2 | notebook.list | 0/2 |
| music.separate | 0/3 | library | 1/3 |
| creative | 1/3 | train | 2/3 |
| motion | 3/3 | models | 1/2 |

## Why cases failed

1. **Attachments could not be used (17 refused, CE1 and CE2).** A picture was refused outright for a model without its
   picture reader, and recordings and clips cannot be attached at all. Even a model that could see a picture had no way to
   hand it to an action: actions take library ids, and an attachment was not in the library and had no id the model knew.
2. **Follow-ups had no id (12, CE3).** After "make a fox", the model is given the action's sentence ("The image was made")
   but not the new picture's id, so "now make it move" got `"image": "a fox reading a book"`: a description, not an id.
3. **Invented field names.** The actions list gave only each action's id and title, so the model guessed `file`, `image`
   or `source` for fields named otherwise. Fixed with CE1: the list now gives each action's required fields
   (`image.edit(image_id, prompt)`), and says an id field takes a library id, never a name.
4. **Looking up instead of doing (13).** On plain asks the model often called `how_to` or `search_creations` and then
   answered in words. This is the small model's habit; the prompt and CE8's run on Haiku 5.5 will show how much is the
   model.

## After CE1

Same model, same cases. The runner now takes a picture for a model that cannot see it, and names every attachment by
its id. 18 of 74 passed (plain 9, attachment 2, follow-up 7). The small model mostly skipped the keep step and proposed
the action it was asked for straight away, with the attachment in the id field (`video.animate` on `portrait.jpg`).

So the chat now does that step itself (`wasifyai_assistant/keeping.py`): an id param that is exactly an attachment of the
conversation, by its id or its file name, is kept with `library.keep_attachment` and replaced by the library id before
the action runs or shows its card. The eval counts such a proposal as a pass (`kept_for` in the cases).

Plain asks went from 13 to 9 in both runs after the actions list gained its fields: for `voice.voices`,
`music.lyrics`, `notebook.create` and `motion` the model now looks a guide up and then answers in words. At
temperature 0.2 some of this is noise; CE7 and CE8 look at it again.
