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

## After CE3's ids

The model is now told the ids of what an action made (`(image_id …; use it to work on the result.)`, from
`tools.ids_said`), and the chat keeps an attachment itself when a proposal names it. 31 of 74 passed: plain asks 9 of 26,
asks with an attachment 4 of 22 (8 still refused: recordings and clips are CE2), follow-ups 18 of 26 (from 8).

| Menu item | Passed | Menu item | Passed |
|---|---|---|---|
| images.create | 2/3 | voice.speak | 0/3 |
| images.edit | 1/3 | voice.transcribe | 1/3 |
| images.inpaint | 1/3 | voice.convert | 1/3 |
| images.reference | 0/3 | voice.voices | 1/3 |
| video.create | 2/2 | voice.edit | 0/3 |
| video.animate | 3/3 | voice.dub | 0/3 |
| video.extend | 1/3 | voice.audiobook | 2/3 |
| model3d | 3/3 | voice.lipsync | 0/3 |
| music.create | 2/3 | notebook.create | 1/3 |
| music.lyrics | 0/2 | notebook.list | 0/2 |
| music.separate | 1/3 | library | 3/3 |
| creative | 1/3 | train | 2/3 |
| motion | 2/3 | models | 1/2 |

What fails now: looking a guide up and answering in words on a plain ask (17), recordings and clips (8, CE2), and a
few wrong actions (`image.generate` for a reference, `motion.make_file` for a new motion video).

## After CE2

Recordings and clips are taken now. 35 of 74 passed: plain asks 9 of 26, asks with an attachment 8 of 22 (from 1 at the
baseline), follow-ups 18 of 26. New passes: Extend, Clone a voice, Change a voice and Dub straight from an attached file.
Still failing with a file: the four picture tools (the model opens the screen or answers in words), Lip sync (it
proposes `image.edit`), Transcribe, Split, Edit speech, the music video of Creative Studio (`creative.plan` without the
song) and teaching from photos (CE5).

## After CE4

`notebook.create` takes attached documents (`attachment_ids`) and `notebook.add_source` one (`attachment_id`), and the
chat is told so. The actions work end to end in the tests. On the local model the notebook cases pass 1 of 5: with two
PDFs attached it still calls `search_creations` first, and on the plain asks it looks a guide up and answers in words.
That is the small model's habit noted above; CE7 and CE8 look at it.

## After CE5

`train.make_set` makes the set `train.start` teaches from (pictures with descriptions and a magic word, or examples from
an attached table), tested end to end with the preview trainer. On the local model "Teach it my dog Rex from these
photos" still ends in words after a guide lookup, so the training cases stay at 1 of 3.

## After CE6

The inpaint follow-up ("change only the tree in that picture") now passes on the local model; the plain ask and the ask
with a photo still end in words after guide lookups. Finding an area is tested with a scripted picture reader; it has
not been tried with a real one (the local default has none), which CE8 does.

## After CE7

Each guide `how_to` returns now begins with how to do it from the chat (`From the chat: propose_action image.edit(image_id,
prompt). If the person asked you to do this, propose it now`). Four chain cases were added (the second step of Dub,
Audiobook, Creative Studio and Train, given the first step's result). 47 of 78 passed: plain asks 16 of 26 and the
chains 4 of 4 (20 of 30 together), asks with an attachment 11 of 22, follow-ups 16 of 26.

| Menu item | Passed | Menu item | Passed |
|---|---|---|---|
| images.create | 2/3 | voice.speak | 1/3 |
| images.edit | 2/3 | voice.transcribe | 1/3 |
| images.inpaint | 3/3 | voice.convert | 1/3 |
| images.reference | 0/3 | voice.voices | 2/3 |
| video.create | 2/2 | voice.edit | 2/3 |
| video.animate | 3/3 | voice.dub | 2/4 |
| video.extend | 2/3 | voice.audiobook | 3/4 |
| model3d | 3/3 | voice.lipsync | 0/3 |
| music.create | 2/3 | notebook.create | 3/3 |
| music.lyrics | 1/2 | notebook.list | 0/2 |
| music.separate | 2/3 | library | 3/3 |
| creative | 1/4 | train | 2/4 |
| motion | 3/3 | models | 1/2 |

Still failing: Make a picture from two pictures (the model makes a new picture instead), Lip sync (it proposes a picture),
the notebooks list (it answers in words), and some asks that still end in words after a lookup.

## CE8: the table again, and what is left (2026-11-12)

Two more fixes first: an attachment named inside an object is kept too (Creative Studio's song is `brief.track_id`), and
the lip sync guide is titled "Lip sync: make a picture say words out loud". Then the whole table on the local default:
**50 of 78** (22 of 74 at the baseline): plain asks and chains 18 of 30, asks with an attachment 14 of 22 (1 at the
baseline), follow-ups 18 of 26 (8). Runs differ by two or three cases at temperature 0.2.

| Menu item | Passed | Menu item | Passed |
|---|---|---|---|
| images.create | 2/3 | voice.speak | 1/3 |
| images.edit | 2/3 | voice.transcribe | 1/3 |
| images.inpaint | 2/3 | voice.convert | 2/3 |
| images.reference | 0/3 | voice.voices | 2/3 |
| video.create | 2/2 | voice.edit | 2/3 |
| video.animate | 3/3 | voice.dub | 2/4 |
| video.extend | 2/3 | voice.audiobook | 4/4 |
| model3d | 3/3 | voice.lipsync | 1/3 |
| music.create | 3/3 | notebook.create | 2/3 |
| music.lyrics | 1/2 | notebook.list | 0/2 |
| music.separate | 2/3 | library | 3/3 |
| creative | 2/4 | train | 2/4 |
| motion | 3/3 | models | 1/2 |

### The gaps, row by row

Every action the menu items need can now be proposed from the chat with what it needs (attachments kept first, ids
told, areas found, sets made). What fails is the local 8B model's choice:

- **Answers in words after a lookup** (12 cases: edit, inpaint, reference, extend, transcribe, voices, convert, dub,
  notebooks list, creative, train with photos, models). The guide now says to propose; the small model still
  sometimes explains. Haiku 5.5 is expected to do better; not measured (the owner's $0 rule).
- **The wrong action**: two pictures become `image.generate` instead of `image.reference` (3); "make this face say …"
  becomes `image.edit` instead of `lipsync.make` (2); a follow-up dub starts at `dub.make` without a script, speech
  edits use invented ids (`speech.edit_speech`), a split runs `music.analyse`, a sketch becomes a new picture.
- **Outside tools** for a recording (`call_external`): the model reached for an outside server once.
- **Lost details**: the lyrics follow-up drops the lyrics; a trained look is named as `style_id` without its magic word.

### Not walked here

The web walk and a run of this table on Haiku 5.5 were not done: both cost money (the owner chose $0 for this work).

## The walk in the real window (2026-11-13)

The desktop window (the app's own Vite build, Playwright with the Tauri bridge filled in), the engine of this branch
on the owner's real data folder (the owner's app closed), real local models: Qwen3.8 27B (MLX) for chat, FLUX.2 klein
for pictures, LTX-Video for clips, EchoMimic v3 for lip sync. Each ask was typed into the chat alone; a card was
answered **Make it** and nothing else was touched.

**It found real faults the table could not**, because the table's attachments and ids never went through a sent
message or the real search. Fixed on the branch, each with a test:

- **No document, recording or video could be attached in the window.** The upload says the file's name in an
  `x-file-name` header, and the engine's cross-origin rule did not allow it, so the browser refused every such
  upload (only pictures went through). The header is allowed now.
- **No action could use a file of a sent message.** Sending the message takes the upload (it is kept with the
  conversation), and the actions looked for an unused upload, so keeping an attachment, a notebook's sources,
  a training set from a table, transcribe and dub all said "no longer there". They read the person's own chat
  file now (`helpers.attached_file`: the id must be a UUID; the storage is the person's own).
- **A message sent while a saved chat was opening** went in as a second version of its first message (the box saw no
  messages and so no parent). It now waits for the chat and goes under the end of its branch.
- **The model was told titles without ids.** `library.list` and `search_creations` said "- image: a red fox", so the
  model passed the title as the id, or gave up ("I have its title but not its id"). Both say the id now.
- **Chats pushed creations out of search.** The chats are indexed too and match first ("red fox" is in the chat that
  made the fox); the chat's search drops them after taking six, so the fox was not found. It looks further now.
  A found video had no words at all (no describer); it is described by its prompt, as a picture is.
- **A call of an action by its id** (`library.list(kind)` as a tool) was "no such tool"; it is taken as the proposal
  it meant. `open_screen` takes an action's id for its screen (`image.edit` opens Images › Edit).
- **Small refusals the model could not mend**: a dub's language as a name ("Spanish" is `es` now); a recording kept for
  `source_id` keeps the kind the model guessed (it is a track); a voice to design needs no name (the start of its
  description); a library kind in everyday words ("music" is `track`); Creative Studio's brief as a line of words
  (it is the idea, and the model is told the song is missing); a notebook made from a document is named after it.
- **Open on a result** went nowhere for a clip, a lip sync, a speech or a transcript; it opens that item in the
  Library now (lip sync results say `clip_id`; every result's `wasify://creation/…` address is read).

**What the walk did, after the fixes** (each in a new chat unless said):

| Menu item | Ask | Result |
|---|---|---|
| images.create | a red fox reading under an oak | done: the picture, one card |
| images.inpaint | (in that chat) change only the leaves to autumn orange | done: area found by the picture reader, leaves changed, fox kept |
| images.edit | my red fox picture as a watercolour | done: found by search, one card, a real watercolour |
| video.create | 5 s of waves at sunset | done after one field the model mended (`duration`) |
| video.animate | my red fox picture, the leaves fall | done: a 5 s clip |
| video.extend | my waves video longer: the sun sinks into the sea | done: found by search (by its prompt now), one card, 10 s |
| voice.lipsync | my red fox picture says a line | done: a 3 s talking clip (about 8 minutes); Open shows it in the Library |
| voice.speak | a welcome line in a warm voice | done |
| voice.transcribe | an attached recording | done: the words exactly as said |
| voice.dub | an attached recording into Spanish | the chain runs (kept, script asked); refused honestly: no voice model here speaks Spanish |
| voice.voices | a calm older narrator | done: a designed voice |
| voice.convert | an attached recording in my narrator voice | asked which saved voice; a designed voice cannot be used (convert takes a copied one) |
| voice.audiobook | a two-sentence story | done |
| music.create | 30 s of upbeat pop | done |
| music.lyrics | a sad country song | done |
| music.separate | my summer road trip song | done: four parts |
| notebook.create | from an attached document, who leads design | done: the notebook holds it, the answer is right |
| notebook.list | my notebooks | done |
| library | my latest pictures | done: the 20 latest |
| motion | a title card | done |
| creative | a music video for my summer road trip song | not done: the model asks which song instead of searching (the guide says to search) |
| train | a set from my fox pictures | answered honestly: one fox picture, a set needs 15 to 25 |
| models | which picture models | listed; "in use" is chosen per screen on the desktop |
| model3d | the fox as a 3D model | needs the 9 GB setup (not downloaded: ask first) |
| images.reference | | not walked (needs two pictures of the same person) |

**19 of 25 done from the chat alone**; 3 refused honestly for what this computer lacks (a Spanish voice, enough fox
pictures, the 3D setup); 2 not done by the model's choice (Creative Studio, convert); 1 not walked (reference).

Still open from the walk:

- **The model's choice**, not the app: Creative Studio asks which song though search would find it; convert asks for a
  voice. A bigger model (Haiku 5.5) is expected to do better; not measured ($0).
- **Speech and lip sync results** show a result card with Open, not a player in the chat.
- **A notebook's card** does not show which attached documents it will use (a list field has no place on a card).
- **The model catalogue** says Kokoro (this build) and VoxCPM2 speak only English, though VoxCPM2's note says
  30 languages; a Spanish dub is refused for that. Check the catalogue against the models.
- **An attached recording kept by the chat** is titled "attached", not its file name.
