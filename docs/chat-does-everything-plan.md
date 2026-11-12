# Everything from the chat (plan, 2026-11-12)

The owner's aim: "allowing user to do all the menu items work through" the chat. A person who never opens a menu
should be able to make, change, find and teach everything the app can, by talking and attaching files, on the desktop
and on the web.

Status: under way on branch `chat-everything` (owner, 2026-11-12: every stage CE0 to CE8 without stopping for
approval, a commit per stage). Progress is in "Progress" below. Nothing here changes an Accepted ADR's decision; it adds to ADR-0068 (every feature is an
action), ADR-0071 (the assistant runs actions on click), ADR-0082 (the chat on assistant-ui) and ADR-0083 (attachments).
The amendments are written with the stage that needs them.

## Where things stand (read in the code, 2026-11-12)

- **Every menu item has an action, and every action is open to the chat.** 86 actions in
  `docs/contracts/actions.json`, all with `assistant` in their surfaces; every item of `packages/ui/src/shell/menu.ts`
  is the `ui` of at least one. Seven are `ui_exempt` (job status, web search and read, app status, outside tools).
- **Making asks first.** A `make` action shows a confirm card (`ConfirmActionCard`) unless the person chose otherwise
  ("Ask me before", ADR-0071).
- **Most actions work on something already in the library.** `image.edit`, `image.inpaint`, `image.reference`,
  `video.animate`, `video.extend`, `lipsync.make`, `model3d.generate` take an `image_id`; `music.separate`,
  `voice.convert`, `dub.script`, `dub.make` take a recording's `source_id`; `train.start` takes a set made on the Train
  screen.

## What stops "everything from the chat" today

1. **An attached file never reaches the library.** The chat takes pictures (through the hardened upload, ADR-0035) and
   documents (read to text, `services/api/src/wasifyai_api/attachments.py`), at most 4 per message. The assistant only
   *looks* at them (`products/wasifyai-assistant/wasifyai_assistant/attachments.py`): no action takes an attachment, so
   "attach a photo and say what to change" cannot be done. `video.keep` exists for videos made by another tool; nothing
   like it exists for an attached picture.
2. **The chat cannot take a recording or a clip.** Only `image` and `document` attachments exist. Transcribe, Dub,
   Split a song, Change a voice, Clone a voice and Extend video all start from a recording or a clip.
3. **A document cannot become a notebook source.** `notebook.add_source` takes a typed note only.
4. **Training sets are made only on the Train screen.** `train.start` needs a `dataset_id` (or a writing or decision
   set) that the chat cannot make.
5. **Results show as a picture in the chat only for two actions.** `Propose` in
   `packages/ui/src/chat/thread/tool-uis/index.tsx` draws `image.generate` and `music.generate` inline; every other
   result (an edited picture, a clip, speech, a 3D model, a dub) is a plain `ActionResultCard` with a link to open it.
6. **Choices made by drawing.** Inpaint takes a rectangle in pixels; the person cannot point at the picture in the chat.
7. **The evaluation covers about a quarter of the actions.** `products/wasifyai-assistant/evals/cases.yaml` has 125
   cases; 68 name an action, and those cover 25 of the 86 actions (mostly Motion graphics and Creative Studio). Edit,
   Inpaint, Animate, Lip sync, Dub, Transcribe, Train, Notebook and Library have none.
8. **Long chains are untested from the chat.** Dub (`dub.script` then `dub.make`), Audiobook (`plan` then `make`),
   Creative Studio (plan, shots, cut, export) and Train need the chat to carry ids from step to step and to wait on
   long jobs (`job.wait`, `job.status`).

Not a gap: settings and keys stay out of the chat on purpose (ADR-0092: secrets never pass through a model). The chat
opens the right Settings page instead (`open_screen`).

## The stages

Sizes: S under a week, M one to two weeks, for one person with tests. Each stage ends with something checked in the real
window and on the web, with a real model (the owner's rule: no stand-ins for what a model makes).

| Stage | What | Size | Done when |
|---|---|---|---|
| **CE0** | **Measure first.** Add eval cases for every menu item, with a pass mark per product (one plain ask, one with an attachment, one follow-up such as "now make it wider"). Run on Haiku 5.5 (the cloud default, ADR-0100) and on the desktop's local default. | S | a table of passes per product and model in `docs/spikes/chat-everything-ce0.md`; this sets the order of the stages below |
| **CE1** | **Attached pictures go to the library.** A `library.keep_attachment` action (picture now; the kinds of CE2 later) saves an attachment of this conversation as a library item and returns its id, so `image.edit`, `image.inpaint`, `image.reference`, `video.animate`, `lipsync.make` and `model3d.generate` can use it. The assistant's prompt says to keep the attachment first when an action needs a library item. It is searchable like any picture (ADR-0041). | S | "attach a photo, make the sky a sunset" and "make this photo move" work end to end on both surfaces |
| **CE2** | **Recordings and clips as attachments.** Audio and video kinds through the same hardened upload (size and length caps), kept to the library by CE1's action, so Transcribe, Dub, Split, Change a voice, Clone a voice and Extend video start from the chat. | M | each of those six from one chat message with an attachment |
| **CE3** | **Results drawn in the chat.** A card per kind of result: picture (any image action), clip, speech or track (a player), 3D model (the viewer), dub, notebook output; each with Open, Download and the follow-ups that make sense ("change this", "make it move", "make it talk"). A follow-up refers to the result by its id, so "now make it wider" works. | M | every `make` action shows its result in the chat; the follow-ups are in CE0's cases |
| **CE4** | **Documents into notebooks.** `notebook.add_source` takes an attachment as well as a note, so "make a notebook from these two PDFs and give me a summary" works. | S | that ask, end to end |
| **CE5** | **Training sets from the chat.** A `train.make_set` action builds a picture set from attached or library pictures (with the Train screen's checks and its captions), and the writing and decision sets from attached CSV or text; `train.start` then runs on it. The run's progress shows as a card. | M | "teach it my dog from these 15 photos" ends with a look used in a new picture |
| **CE6** | **Pointing at a picture.** Inpaint from words ("the sky", "his shirt"): the area found by the vision model and shown on the picture to accept or redraw; and a box drawn on a picture card in the chat. | M | the CE0 inpaint cases pass with words alone, and a drawn box works |
| **CE7** | **Long chains.** Dub, Audiobook, Creative Studio and Train driven step by step from one ask, the chat waiting on long jobs and saying where it is; stopping from the chat. | M | each chain from one ask in CE0's cases |
| **CE8** | **The walk.** Every menu item done from the chat alone, in the real window and on the web, on Haiku 5.5 and the local default; CE0's table run again. | S | every row passes, or its gap is written down |

Order: CE0, then CE1 and CE3 (they unblock the most), then CE2, CE4, CE5, CE6, CE7, and CE8 last.

## Decisions for the owner

1. **The default model for the chat on the desktop.** Small local models choose tools less well than Haiku 5.5. CE0
   measures it; if the local default fails, the chat could offer the cloud model for tool work when a key is set.
2. **Audio and video attachment caps** (CE2): the size and length a person may attach (the web pays the storage).
3. **Ask before making from the chat.** Today the default is to ask. Keep it, or let the person turn it off per kind
   (it exists as "Ask me before" in Settings)?
4. **New actions and attachment kinds change public shapes** (`library.keep_attachment`, `train.make_set`, the
   `audio` and `video` attachment kinds): the CLAUDE.md "Ask before" rule applies, so each is confirmed before its
   stage starts.

### The owner's answers (2026-11-12)

1. Keep the local model on the desktop, and offer Haiku 5.5 for tool work when a text key is saved.
2. Audio 50 MB and 10 minutes; video 200 MB and 2 minutes; the same on the desktop and the web.
3. The ask-before default stays.
4. The new action and attachment kinds are agreed with the plan. The work spends nothing: the measurements run on the
   local model only, and no paid media run is made (Haiku 5.5 is measured later, by the owner's choice).

## Progress

| Stage | State | Where |
|---|---|---|
| CE0 | done 2026-11-12: 74 menu cases, the local default passes 22 | `docs/spikes/chat-everything-ce0.md` |
| CE1 | done 2026-11-12: `library.keep_attachment`, ids named, pictures for every model | ADR-0083 amendment of 2026-11-12 |
| CE2 | done 2026-11-12: recordings (50 MB, 10 min) and clips (200 MB, 2 min) attach in the chat on both surfaces, cleaned by FFmpeg; kept as a song or a video by `library.keep_attachment`; the Import buttons of Videos and Your music share the same code | `wasifyai_api/attachments.py` (`attach_media`), `wasifyai_video/keep.py`, `wasifyai_voice/keep.py`, ADR-0083 amendment |
| CE3 | done 2026-11-12: the model is told the ids of what was made; every picture, song and clip result is drawn in the chat with Open and follow-up buttons (Make it move, Make a 3D model, Make it longer, Split the voice out, Write it out); the web chat now plays songs too. 3D and dub results keep the plain card with Open. Follow-ups pass 18 of 26 (from 8) | `tools.ids_said`, `tool-uis/ActionCards.tsx` (`FOLLOW_UPS`), `ToolCard.tsx` (`VideoPlayer`) |
| CE4 | done 2026-11-12: `notebook.create` takes up to 4 attached documents (`attachment_ids`) as its first sources, named by their first line; `notebook.add_source` takes one (`attachment_id`) instead of typed text; the chat is told how | `wasifyai_notebooks/actions.py` (`attached_text`), `keeping.py` (`TAKES_ATTACHMENT`) |
| CE5 | done 2026-11-12: `train.make_set` makes a picture set from library pictures or attached photos (kept first), with the screen's checks, descriptions and a magic word; or a writing or decision set from an attached table (CSV, semicolons or tabs; a decision question's kind from its answers). The card offers **Teach it** when the set is ready; `train.start` runs as before, with its progress card. Video sets stay on the screen | `wasifyai_training/sets.py`, `helpers.attached_document`, `ActionCards.tsx` (`set`) |
| CE6 | done 2026-11-12: `image.inpaint` takes the area in words (`area`); before the card the chat asks `image.find_area` (the model that reads pictures, a box from 0 to 1000, padded) and the card draws the box on the picture, where the person may drag another; under a picture in the chat **Change an area** draws a box and asks for the change. The card keeps a list or a rectangle it has no field for when a field is edited (a fix: an edited inpaint card lost its region). Not checked with a real picture reader yet | `wasifyai_image/area.py`, `wasifyai_assistant/locating.py`, `tool-uis/RegionPicker.tsx`, card `region` in `docs/contracts/sse-events.md` |
| CE7 | done 2026-11-12: a guide `how_to` finds now starts with how to do it from the chat (`propose_action image.edit(image_id, prompt)`, "propose it now"), which ended most of the look-it-up-and-explain answers (plain asks 9 of 26 to 16 of 26); four chain cases (Dub, Audiobook, Creative Studio, Train: the second step with the first step's ids) pass; a long step shows its progress in the chat and Stop stops it (tested). The menu cases pass 47 of 78 | `tools.do_now`, `tests/test_chains.py`, `evals/cases.yaml` (`*-chain`) |

## Not in this plan

Settings and keys from the chat (kept out on purpose), and the Motion graphics editor's drag-and-drop (the chat
already drives it through `motion.*` actions; the editor stays the place to look).
