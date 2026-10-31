# ADR-0090: Creative Studio: one project that goes from an idea to a finished video (a plan, shots, a cut), built from Maestro's concepts on our own parts

- **Status:** Accepted (owner, 2026-10-24: "I'll go with your pick" on all seven questions, recorded in "Owner's answers" below). **CS0 is
  done: the owner watched the excerpts on 2026-10-31 and said go (`docs/spikes/creative-cs0.md`). Its results are written into the decisions
  below. CS1 is built (2026-10-31; "Built" below): a song becomes an editable plan on the desktop. The screen amendment was accepted the same day and its first stage is built ("The screen" under "Built"); CS2 is next.** "Creative Studio" is the owner's working name.
- **Order and shared parts:** ADR-0096 (2026-10-31): the Motion graphics editor is built first; its screen frame, media rail, Make panel and docked assistant are shared with this product. The consent, safeguard and terms parts below were removed by ADR-0094.
- **Date:** 2026-10-24
- **Asked by:** the owner, 2026-10-24: study Maestro's Creative studio, Director and video editor, **do not use its code**, and plan how to
  adopt the concept.
- **Depends on:** ADR-0056 (one engine, two shells), ADR-0037 (video product, LTX-Video 2B 0.9.5), ADR-0059 (the image engine), ADR-0066
  (speech, music and lip sync models, descriptors), ADR-0044 (lip sync, consent), ADR-0068 (the action catalogue), ADR-0041 (every
  creation is searchable), ADR-0063 (will it fit), ADR-0077 and ADR-0079 (Motion graphics: titles and captions), ADR-0073 to ADR-0076
  (Train: characters and styles), ADR-0078 (Qwen3.5-9B writes plans), ADR-0047 (safeguards), ADR-0061 (how outside ideas enter),
  ADR-0081 (design tokens), ADR-0086 (the model button, in the top bar), ADR-0087 (engine workers for the web), ADR-0088 (one job per
  person).
- **Evidence:** `docs/spikes/maestro-study.md` (what Maestro does, in my words; its source and docs were read, it was not run). No model
  was run for this ADR.
- **Earlier proposal:** a narrower "music video" proposal was withdrawn by the owner on 2026-10-24. Its ideas that survive are used
  below where they are marked; its numbers are the ones already in `docs/desktop-profile.md` and the voice spike.

## Context

Maestro (an open local app built on WanGP, release 3.2.0 of 2026-10-22) offers three modes over one library of outputs: **Studio**
(make one thing with every control), **Director** (a language model plans a music video or short film shot by shot, the app makes
pictures and clips and joins them) and **Editor** (a timeline to finish the work). It runs only on NVIDIA GPUs. The owner wants the *concept* in Wasify AI, built on
what we have: a Mac, local models, ComfyUI, the voice product, Motion graphics, the library and the action catalogue.

What we have today that a person could use to make a video by hand: Create images (klein 4B, about 13 s warm), Edit, Inpaint and
Reference (a picture as a reference for character consistency); Video (LTX-Video 2B 0.9.5: a 2 s clip 72 s, a 5 s clip 252 s at
768x512, 13 s for a small 25-frame draft, about 13 GB peak), Animate and Extend; Music (ACE-Step songs, lyrics, stems), Speech to
text with times, Text to speech and cloned voices, Lip sync (MuseTalk, a 5 s clip in about 30 s, the head stays still); Motion
graphics (titles, quotes, lower thirds, captions drawn by a sandboxed browser); Train (a character or style LoRA, on the desktop);
the bundled ffmpeg; My creations search. What is missing is **the thing that joins them**: a project that remembers the idea, the
plan, which shot is which, and the cut.

## What Maestro teaches (ideas, ranked by value to us)

| # | Idea in Maestro | Adopt? | How we would do it |
|---|---|---|---|
| 1 | **A shot plan that is a document, not text:** a model-neutral record per shot (length, goal, who is on screen, place, style, mood, action beats, camera, audio role, how it ends, how it continues, what source it wants, lines of speech), validated by code | **Adopt, smaller** | a short schema our 9B model can fill reliably (decision 4); validated by code; the person edits the same document |
| 2 | **Skills over one pipeline:** music video, short film, podcast, viral clip are planners that all produce the same plan | **Adopt two** | a *Music video* skill and a *Story* skill (decision 3); more later as data |
| 3 | **Planner, renderer, validator are separate:** the neutral plan is turned into the prompt style of each model and mode by renderers | **Adopt** | "renderers" are prompt writers per capability binding, kept as files under `products/*/prompts/` (rule 4: no model names in graphs) |
| 4 | **Song analysis drives the cuts:** beats, downbeats, sections, timed words, who sings, drum entrances; cut times scored on musical cues, snapped to the clip length limit and the video frame grid; a signed "cut speed" | **Adopt** | `music.analyse` action; a pure function lays out slots; the person moves cuts (decision 5) |
| 5 | **The whole song is planned before any shot is written:** a compact arc with a repetition check and focused repairs that keep accepted rows | **Adopt** | a two-pass plan: arc, then shots (decision 4) |
| 6 | **The code owns the facts:** cast, places, timing and who sings when come from registries; the model writes inside them | **Adopt** | a *brief* record plus a *cast and places* list the plan must use |
| 7 | **Resumable by design:** small batches, a durable checkpoint per batch, a cache key from every input and the planner's revision, an immutable copy of inputs for each run, "reuse what is done" | **Adopt** | decision 8 |
| 8 | **Review everywhere:** Auto or Manual, per-shot prompt edit, mark good or needs work, re-make one picture or clip, keep earlier takes, rejoin, open an old project as a new revision, a visible planning log | **Adopt** | decisions 6 and 9 |
| 9 | **A non-destructive timeline** with a project file, tracks, items, takes, undo, previews and an ffmpeg export, plus a "send this clip back to a tool and return it as a new take" round trip | **Adopt in two steps** | a *Cut* (one picture track, the song, a caption track) first, a fuller editor later (decision 7) |
| 10 | **Provenance links** from a timeline item to the shot that made it | **Adopt** | every clip knows its shot, its prompt and its seed (decision 2) |
| 11 | **Characters as portable entries** (a picture or video, a name, a description, a voice) used by image, video and speech | **Adopt, ours** | a *character* is reference pictures + a look in words + optionally a Train LoRA + optionally a saved voice (decision 10) |
| 12 | **Adaptive writing:** develop a short idea; keep a long script's events and exact words | **Adopt** | one rule in the plan writer's guide |
| 13 | **Honest hardware guidance:** tested, reported or estimated; memory-fit labels; an estimate corrected by the first real run | **Adopt** | ADR-0063's fit check plus a time panel (decision 9) |
| 14 | A queue of whole projects, completion sounds and push messages, a private phone tunnel | **Skip for now** | ADR-0088 gives one job per person; notifications can come later |
| 15 | Model zoo, per-model tuning knobs, NSFW modes, 50-LoRA browsers | **Skip** | out of scope; our model picker (ADR-0086) is the way |

## Where we are different (the honest limits)

* **Our video model is small.** LTX-Video 2B 0.9.5 makes 2 to 5 second clips with gentle motion, no sound, and no audio-driven singing.
  Maestro's best results lean on models (H3, LTX-2.5) that take audio and references. So **a shot here is mostly a picture with a camera move,
  sometimes a short animated clip, rarely a sung close-up** (the "motion level": Hold, Animate, Sing). The product must say so.
* **Our planner is a 9B model** (ADR-0078), not a 27B one. That makes a *smaller* schema and *more* code checks the right trade.
* **One model in memory at a time, one job per person** (ADR-0088). No overnight queue of many projects in v1; one project at a time.
* **Mac first, English only in v1** (the lyrics may be any language a person can type; timed words come from the speech model, and CS0 found English works and Bengali does not).
* **We have an assistant and an action catalogue.** Everything a person can do must also be an action (ADR-0068), so the assistant or
  an agent can say "make a music video of this song" and a person is still asked before anything costly.

## Options considered

| # | Option | Verdict |
|---|---|---|
| A | **Copy Maestro's three modes** (Director, Studio, Editor as three apps) | No. Our Studio part already exists as the Images, Video and Music screens; copying the split would duplicate them |
| B | **One project with three views over the same document: Plan, Shots, Cut** (recommended) | Yes. Each view is a step, the person can stop after any step, and every screen we already have stays the place to make a single thing |
| C | **A "Music video" button only** (a pipeline with no editable project) | No. It is the cheapest, but a person cannot change the plan or one shot, and nothing can be resumed or searched |
| D | **Wait for a better video model first** | No. Plan, still pictures, cuts and a timeline do not depend on it, and a better model later plugs in as a binding |

## Decision

1. **Build option B: Creative Studio is a project.** A project holds a *brief*, a *plan*, the *shots* with their media, and a *cut*. It has
   three views, in this order, each usable on its own: **Plan** (the idea turned into shots, nothing made yet), **Shots** (the
   pictures and clips, redo any), **Cut** (the timeline and the finished video). Not a Director/Studio/Editor split.
2. **One document, immutable revisions of the inputs.** The project is a versioned JSON document (decision 3 lists its parts) kept in
   the product's store (SQLite on the desktop, Postgres on the web later). Every shot, still, clip and cut item records **where it came
   from** (the plan revision, the shot id, the prompt as sent, the seed, the model binding). "Change the plan" after media exists creates a
   new plan revision; shots whose inputs did not change keep their media, shots whose inputs changed are marked "out of date" and are
   remade only when the person says so.
3. **The parts of the document.**
   * **Brief:** the skill (music video or story), the source (a song from Your music, a recording, or a written story), a one-line
     idea and a style, a shape (landscape, vertical, square), a target length, the cast and places the person named, the typed lyrics
     when the song has them, a language note, and the review mode (Auto or Review each step).
   * **Facts (made by code, not by the model):** for a song: length, tempo, beats, downbeats, sections with their boundaries and an energy label (no
     verse or chorus names: the tool does not give them), timed lyrics, and where each cut falls; for a story: a *story bible* of title, tone, ending, the cast and places.
   * **Plan:** *beats* (what happens, and who) and *shots*. A shot has: id, start and end (song seconds, snapped), the beat it belongs
     to, what is shown in plain words, who is in it (cast ids), the place, the camera (framing and movement), the lyric or spoken line
     it matches, the **motion level** (*Hold*, *Animate*, *Sing*), a mark when it is a plain fallback row, and a note. Only *beats* and
     *what is shown* come from the writer; code fills in the rest and the person can change any of it. Nothing about a model is in it.
     A shot kind and how a shot ends and continues are left out: they were not in the schema that worked.
   * **Shots made:** per shot, the stills (one or more takes), the clip takes, which take is chosen, and what each cost in seconds.
   * **Cut:** the timeline (decision 7) and the exports.
4. **Planning works like this, because the model is small.** (a) Code lays out the **slots** (decision 5). (b) Code sets the order of places, the
   camera (a repeating cycle of framings, each with its own instruction) and the motion level (about 1 shot in 6 Animate). The writer
   answers two questions, with array lengths set by the code: the **beats** for the whole song first
   (`{"beats":[{"what","who"}]}`), then **one sentence per shot** in small batches (`{"shots":["..."]}`). The engine's schema support is
   required: without it all 24 rows fell back in CS0. Letting the writer fill every field stayed valid but read as repetitive, stuck in one
   place and ahead of the story. (c) Code checks each row: times cover the song with no gap, cast and places exist, no filler phrases, no verbatim repeats unless the
   writer marked a repeat on purpose with a reason, an action stays in one place. (d) A bad row is repaired a bounded number of times
   and otherwise replaced by a plain fallback row the person can see is plain. (e) Every batch is a **checkpoint**; a crash resumes
   at the first unfinished batch. (f) The **planning log** (what was asked, what came back) is shown, because it is how a person
   understands a bad plan. CS1 runs Qwen3.5-9B and Qwen3-8B again and chooses: on one run each in CS0, 8B
   did at least as well (a plan for 24 shots in about 25 s on either).
5. **Cuts come from the music, and the person can move them.** A pure, tested function takes the analysis (beats, downbeats, sections,
   timed words, optionally who sings) and the video model's longest clip, and returns slots: cut times scored on musical cues,
   snapped to beats and to the video frame grid, with a **cut speed** control from -2 (few, longer) to +2 (many, shorter). A slot
   longer than a clip can be is split at a beat. A clip is made a little longer when needed and trimmed, so the music never drifts.
   **Analysis is beat_this (CS1 tries the small checkpoint first) with librosa for sections**, chosen by CS0; allin1 would not build. It
   needs PyTorch, about 900 MB, so **it enters the dependencies only with the owner's yes**, CLAUDE.md "Ask before". **Typed lyrics are the
   text**; speech gives only their timing, because misheard words leaked into shots in CS0. A song without typed lyrics in a language
   the speech model cannot follow is cut on beats and sections alone.
6. **Draft first, motion later, always honest.** The order is cheapest first and the person can stop after any step:
   *Plan → Look (stills for every shot) → Preview (the stills cut on the beats over the song with ffmpeg camera moves) → Draft excerpt
   (animate a chosen stretch at the small setting) → Make it better (animate or sing chosen shots at the final setting)*.
   Before each **Start** the screen says in words: how many shots at each motion level, the time as a range ("about"), corrected
   after the first shot (CS0's starting figures for a 3-minute song: preview about 15 minutes with plain stills and about 30 with
   reference pictures, draft motion about 40 minutes more, final motion about 2.4 hours more), the disk it will use, the model still to download (with size), and whether it fits (`fits`,
   `tight`, `too_big`, ADR-0063). A step that cannot fit is not offered. Nothing is downloaded without the usual click.
7. **Cut is a small, real timeline, not a full editor in v1.** One picture track (the shots in order, each with the chosen take), one
   audio track (the song), one caption track (lyrics or text, drawn with Motion graphics). The person can reorder, trim, split, swap a
   take, set a transition (cut or fade), move a caption, undo and redo, preview, and export H.264 MP4 in the three shapes the video
   product has. The project file is non-destructive (it refers to media), and **export always writes a new file** and records it.
   A fuller editor (more tracks, speed, opacity, transforms, linked items, markers) and the *send a clip back and return it as a new
   take* round trip are stage CS6, after the owner has used the small one.
8. **Everything long is a job with child jobs, and resumable.** A project run is one job (CLAUDE.md rule 6: nothing waits on the GPU)
   with one child job per shot step. Each finished still and clip is saved at once. **Cancel keeps finished work.** Restart resumes and
   redoes only what is missing or out of date. One run per person at a time (ADR-0088); it takes the one big-model slot in turn with
   chat and the other products. A **disk preflight** refuses to start a run that cannot finish.
9. **Review is a first-class mode.** *Auto* runs plan, looks, preview in one go; *Review each step* stops after each. In every view the
   person can edit a sentence, change a length, change a motion level, **redo this shot** (one still or one clip, keeping the old
   take), mark a shot *good* or *needs work*, delete or add a shot, or ask the writer to **try another idea for this part** (only
   that part is rewritten; accepted shots stay).
10. **Characters keep a face and a voice across shots.** A *character* (a shared library, not only this project) is: a name, a look in
    words (including clothes, repeated exactly in every prompt), one to three reference pictures, optionally a **Train** LoRA, and
    optionally a saved voice. Shots that show a character use the *Reference* mode of the image product with that character's pictures,
    and a *Sing* shot uses the voice. Reference is the default and plain stills are the faster choice: plain holds hair and clothes but
    the face varies. **Objects and places get fixed words too**, repeated in every prompt, because the car changed from shot to shot in
    CS0. A cast member can be **seen only in photos**, so the picture prompt never draws them as present. The code, not the model, decides which shots a character appears in (it comes from the plan).
    A picture of a real person asks the same "who is this" question as lip sync does today (ADR-0044); a made-up character asks nothing.
11. **Models are bindings, not code.** Planner and shot writers ask for `caps.text.chat`; stills for `caps.image.generate` or
    `caps.image.reference`; animate for `caps.video.animate` or `caps.video.extend`; sing for `caps.video.lipsync`; the song for the
    music product; analysis for a new `caps.music.analyse`; the cut for a new `caps.video.compose` (ffmpeg). The model picker (ADR-0086)
    chooses them; a better clip model later is a descriptor (ADR-0066) with no change to a project.
12. **Prompt guides are our own files.** What Maestro keeps as writing guides per model becomes `products/<id>/prompts/*.md` that **we
    write ourselves**, for our models, in our words. Nothing is copied from Maestro (the guides were
    written for other models).

## How it fits the product

### Where it lives

A new product, `wasifyai-creative` (display name **Creative Studio**, see open question 1), owns the project, plan, shots and cut. It
calls the other products only through capabilities and actions: the voice product gains `music.analyse`; the video product's clip,
extend and animate actions and the image product's create, edit and reference actions are the same ones the screens use. A new menu
item **Creative Studio** goes in the side menu (after Music, before Motion graphics; open question 1) with a screen of three tabs
(Plan, Shots, Cut) under a project list. Sentence case in every label ("Plan", "Shots", "Cut", "New project"). The model button is in
the top bar (ADR-0086), one per model the project uses.

### The screen, in words for a person who has never made a video

1. **New project.** *Pick a song* (from Your music, add a recording, or make one) or *write a story*. One line: what is it about?
   A style (chips). Who is in it? (add a character, or none). A shape and a length. **Make a plan.**
2. **Plan.** A strip of the song with its sections and a card per shot (what is seen, how long, which words, how it moves). Change a
   sentence, a length, a motion level; drag a cut; delete or add a shot; **try another idea for this part**. Cut speed slider.
   Nothing is made yet. A note says what the planning log shows.
3. **Shots.** The stills as a grid. **Redo**, replace with a picture of your own, or choose another take. This is the cheap place to
   say "no, not that". Then **Preview the whole song**, **Draft a 30 second piece** (the loudest section is pre-picked) and, later, **Make it
   better**. The honest panel before each.
4. **Cut.** The timeline and the video. Reorder, trim, swap takes, captions on or off, **Make the video**, **Save a copy**.
5. At the top of every step: **Auto / Review each step**, and a **Stop** that keeps what is done.

### Actions (ADR-0068; each with a help file, a `ui` pointer, a row in `docs/contracts/actions.json`, a test through `ActionExecutor`)

| Action | Effect | Flags | Notes |
|---|---|---|---|
| `music.analyse` (voice product) | `make` | `private` | song or recording to beats, sections, timed words, optionally speakers; kept with the song |
| `creative.plan` | `make` | `private` | brief to a plan (no media), editable |
| `creative.edit_plan` | `change` | | apply changes to a plan (assistant, MCP, and the screen use the same document) |
| `creative.make_shots` | `make` | `costly`; `needs_consent` only for a real person's picture or a voice | stills, clips, sung shots; `long=True`; one job with child jobs |
| `creative.redo_shot` | `make` | `costly` | one shot, one step |
| `creative.cut` | `make` | | assemble or re-assemble the video from the chosen takes |
| `creative.export` | `make` | | write a new file |
| `library.delete` (existing) | `destroy` | always asks | works on the new kind |

Surfaces: `assistant` and `mcp` for plan, make and redo (so "make a music video of this song" works from chat); `destroy` and
`needs_consent` always ask a person. A plan the assistant makes from lyrics that came from the web carries the taint rule (ADR-0070).

### Searchable creation and library kind (ADR-0041; part of CS1, not left to the end)

New kind **`creative_project`**. Index text: title, idea, the cast and places, every shot's description, the lyrics. Registered with
`caps.index_creation` on save and when the plan or the cut changes; `deps.unindex` on delete; an `IndexSource`; an `ids=` filter on
the project list route; a card (poster = first still, length, shot count, state) and a filter in My creations; a row in
`services/api/evals/search/corpus.yaml`. The shots' stills and clips are **not** separate library items (they live inside the project);
the exported MP4 is saved to the video library like any video.

### Deletion

Deleting a project (`destroy`) removes the document, stills, clips, cuts, exports and poster and unindexes it, and asks one question
("Also delete the song?", default keep). Deleting while a run is going cancels it first. Characters are shared and are not deleted
with a project.

### Consent and safeguards

* **Faces and voices** keep the rules already in force for lip sync (ADR-0044) and voice cloning: the "who is this" and "whose voice"
  answers are kept with the video. The lip sync mark question stays as the owner decided on 2026-10-20 (backlog D13).
* **The song:** "Only use songs you made here, or that you have the right to use." Nothing leaves the computer (local only to start;
  a hosted provider is not in this ADR). ADR-0047 safeguards apply through `await caps.safeguards_on()`.
* **Prompt injection:** lyrics and story text are data; they reach the writer inside a prompt and cannot call tools; the plan is parsed
  as JSON and validated.
* **Maestro:** its code and guides are **not used**; its ideas are used as ideas. CS0 chose beat_this and librosa (they enter the dependencies only with the
  owner's yes).

## What exists, what is missing

| Need | We have | Missing |
|---|---|---|
| Plan writer | Qwen3.5-9B through the chat gateway | the plan schema and validators, the guides (the engine's schema support works, CS0) |
| Song analysis | Parakeet (timed words), HTDemucs (vocal stem) | beats, downbeats, sections (beat_this and librosa, waiting for the owner's yes), the cut layout function |
| Stills | klein 4B create, edit, inpaint, reference | a batch-by-shot job, consistency by reference pictures, takes |
| Clips | LTX 0.9.5 animate and extend | a per-shot job with takes; a draft setting (15 steps, 0.125 MP, about 50 s for 5 s; the product has none today); a longer clip is a trimmed one |
| Sing | MuseTalk (20 s sung in about 140 s; only the mouth moves; its 16 kHz mono sound is thrown away and the song laid over) | a per-shot job with the slice, and a rule in the plan for which shots sing |
| Titles and captions | Motion graphics (HyperFrames) | a timed caption track fed from typed lyrics and timed words: the `captions` template gives every line the same 2, 3 or 4 s, and MX6's `cues` are on opaque scenes |
| Cut | bundled ffmpeg | a timeline document, a render graph compiler, proxies and a waveform |
| Characters | Reference mode, Voices, Train | a shared character library with pictures, look, voice and LoRA |
| Project, jobs, resume | job manager patterns (3D, Motion graphics), SQLite stores | the project store, child jobs, checkpoints, revisions |
| Searchable, actions, help | the catalogue, My creations | the kind, the actions and their files |

## Staged plan (each stage ends with tests, a real run on the owner's Mac, docs and `git add`; sizes are working days of one engineer with Claude)

| Stage | What | Size | Done when |
|---|---|---|---|
| **CS0** | **Done 2026-10-31: go.** **Spike, measured, no product code in the repo.** On the owner's Mac, in a throwaway folder: (a) beat, downbeat and section tools on three songs (sung English, instrumental, another language); (b) Qwen3.5-9B plans the same songs and two stories with our smaller schema: does it stay valid JSON (with the engine's schema support), cover the timeline, stay in the cast; how many rows need repair; a person's read of the shots; (c) klein stills for 12 shots with and without character reference pictures, and the preview cut on the beats; (d) LTX clips for six of them at draft and final settings; (e) MuseTalk on a sung vocal for 20 s; (f) a 60 s ffmpeg cut with captions from Motion graphics. Downloads are deleted afterwards and the disk used is reported. The owner watches two excerpts and says whether this works as a fast, honest draft | 3 | `docs/spikes/creative-cs0.md` with a measured table, the schema that worked, a go or no-go. **No-go ends here** and the ADR is amended |
| **CS1** | Project store and document, `music.analyse` (once the owner has said yes to PyTorch), typed lyrics, the choice of 9B or 8B, the cut-layout function, the brief and **Plan** view, plan writer with checks and checkpoints, the planning log, actions, help files, **search registration and eval row**, `creative_project` kind | 7 | a song becomes an editable plan on this Mac in the CS0-measured time; a crash mid-plan resumes; the search checklist in full |
| **CS2** | **Shots** view: stills per shot, characters (pictures and look, seen only in photos), fixed words for objects and places, takes, redo, out-of-date marks, Preview cut over the song, the honest panel, one job with child jobs, cancel keeps work, disk preflight | 7 | a 3-minute preview in about the estimated time; kill and resume redoes only missing shots |
| **CS3** | **Cut** view: the small timeline, ffmpeg render graph, a timed caption track, take swap, undo, export, save a copy | 6 | the owner exports a finished video of a real song from the screens only |
| **CS4** | Motion: a draft setting for Animate, Animate at draft and final settings, the draft excerpt, Make it better, the time estimate corrected from the first shot | 4 | a 30 s draft in about the estimate; estimate within 25% of the real time |
| **CS5** | Sing: a plan rule for which shots sing, performance shots with MuseTalk and the consent answers; the Story skill (story bible, cast and places, narration or spoken lines with saved voices) | 6 | a story with two characters and a narrated voice; a song with four sung close-ups |
| **CS6** | Polish: a picture-reading checker with a redo offer, the fuller editor (tracks, speed, opacity, transforms, markers), the round trip as a new take, desktop checklist, web decision | 6 | the owner makes three videos from their own material and says whether the drafts were fast and honest enough |

Total to a usable v1 (CS1 to CS4): about 24 working days after CS0. The sizes are from before CS0 and ADR-0096's shared parts; they are worked out again at CS1.

## Built

### CS1 (2026-10-31; desktop only)

A song and an idea become an editable plan of shots, in the window and through the actions `music.analyse`, `creative.plan` and `creative.edit_plan`.

- **Song analysis** is the optional component `music-analysis`: beat_this 1.1.0 with its small checkpoint, librosa and CPU PyTorch in their own environment, from a hashed lock (`products/wasifyai-voice/analysis/`, `scripts/lock-music-analysis.sh`). 926 MB on disk. The answer is kept with the song (voice schema v6).
- **Typed lyrics are the text.** Parakeet only gives times, on the full mix with no separation, and the times are per stretch of speech, so they are rough. Under 25% of the words matched, the lines have no times (`lyric_timing.py`). Bengali gets no times, as CS0 found.
- **The product** is `products/wasifyai-creative/`: `layout.py` (the cuts), `document.py` (the brief, the checks, the edits), `writer.py`, `store.py` (projects, revisions, checkpoints, planning log), `runtime.py` (the plan as a job, search). The screen is `packages/ui/src/creative/`.
- **Who writes:** the chat model the person chose, not one fixed here. This is the answer to "9B or 8B" for now, see below.
- **A crash** marks a running plan `interrupted`, with its checkpoints kept. The person presses **Go on**; nothing is spent by itself.
- **Search:** kind `creative_project`, added to the index on every change and removed on delete, with a corpus row.

Measured on this Mac (M5 Pro, 64 GB) through a real engine on a throwaway folder, with `apps/desktop/scripts/ui-audit.sh light creative` for the window:

| Check | Result |
|---|---|
| Plan, 3-minute song, 49 shots, Qwen3-8B | **44 s**, 1 fallback row (CS0 worked out about 1 minute) |
| Plan, 90 s songs, Qwen3-8B | 36 s and 43 s (English, 25 shots), 49 s (instrumental, 45 shots), 31 s (Bengali, 27 shots) |
| Plan, 90 s song, 25 shots, **qwen3.8:27b on Ollama** (the model chosen on this Mac) | **529 s** |
| Beats and sections, 90 s song | about 4 s on the first run, kept after that; with line times about 10 s |
| Engine killed with `kill -9` at part 3 of 8 | Marked `interrupted`; **Go on** asked only parts 3 to 8, 16 s |
| Stop during a plan | Stops at once, can go on |
| Window walk: brief, plan, edit, move a cut, Undo twice, the log | Works; axe has nothing to say on the list, the brief or the plan; no sideways scroll at 390 px once the side menu is hidden |

**What the real runs changed that unit tests had not shown:**

- The search answer's list of kinds did not have the new kind, so a hit gave a 500.
- The model pasted the sung line into the shot. It is now told the line is for the mood only.
- The length limit cut sentences mid-word. It went from 150 to 180 characters, the model is told under 20 words, and a sentence cut at the limit is asked for again.
- A shot's `who` was only found by name. It now also matches the end of a phrase of how the person looks ("green jacket").
- A beat's `who` is now limited to the names in the cast.

**9B or 8B:** 8B is the size measured and it is good enough to start from. 9B was not run again: it was deleted after CS0 and is a 5.68 GB download that needs the owner's yes. The screen says the time depends on the model.

**Not done, on purpose:**

- At the end of CS1 the screen amendment was still Proposed; it is built now, under "The screen" below. Plan, Shots and Cut are at the top, the last two off.
- Cuts move by whole beats with buttons, no dragging.
- Deleting a project keeps its song, with no question about it.
- The story skill stays in CS5.

**Not checked:**

- The real Tauri window (a WKWebView stand-in was used) and the shipped app's bundle.
- Whether the beats are right, by a measure.
- Search by meaning: the desktop's index is `local-hash/v1`, which matches words, for every kind (`docs/desktop-profile.md`). So a project is found by its words, and a French search does not find an English project on the desktop.
- A fresh download: the install took 20 s because uv's cache already had the packages.

**Plan quality, read by me on the runs above:** a person can start from these and will edit them. Details still drift, some lines cannot be shot ("Mira's face shows determination"), and repeated actions are common in a long part.

### The screen (2026-10-31; desktop only)

The CS1 row of the amendment's stage table, built after the owner accepted it.

**What works:**

- **One screen for a project:** Make panel on the left, the plan as the stage in the middle, the media rail on the right. It is a new frame in `packages/ui/src/creative/` (`ProjectView`, `MakePanel`, `MediaRail`, `use-project-media`). Motion graphics' `SceneEditor` was not refactored to share it.
- **Top bar, as in the mockup:** model button, title, "Plan N · saved", Plan, Shots and Cut in the middle (the last two off), Planning log, and Make the stills (off). From 85rem wide it sits in the window's bar; below that, under it.
- **Make panel tabs:** Image, Video, Voice, Music, Titles, 3D, Add, Ask, with arrow keys. On a narrow screen it is a sheet under the stage with the tabs as a dock.
- **Ask:** the chat, docked on the project through `creative.read_project`. It sees the plan afresh before each model call, and which shot is selected. Changes apply at once. Each change's card has its own Undo, which takes back that change and any after it. The chat stays alive while another tab shows.
- **Add:** pick from the Library. The item is tagged with the project and the selected shot, not copied.
- **Media rail:** the library filtered by this project, newest first, with the song always there. A thing deleted from the Library goes from the rail too.
- **New actions:** `creative.read_project`, `creative.undo`, `creative.add_media`, `creative.remove_media` (76 in the catalogue). The assistant's docking now takes a screen's `project_id` as well as Motion graphics' `composition_id`.

**Measured and checked (on Qwen3-8B, through the real screen):** "Make this shot animate" changed the selected shot and the stage showed it. The card's Undo took it back. A question changed nothing. Axe found nothing on the plan, Add, Ask or phone-width views, and there was no sideways scroll at 390 px. The evaluation `run_tool_eval.py --only cs-` passes 11 of 11, including the step after a change.

**What the real model found (unit tests could not):**

- It first passed 4 of 10. It sent `add_shot` as the action, changed things when only asked a question, and copied the example's shot id, so it changed the wrong shot. The guide's examples now show the selected shot's own id.
- It took back its own change and reported "back to Hold" when the shot was already on Animate. An edit that changes nothing is now refused in words, the guide says never to undo unless asked, and the evaluation checks that step.
- The screen says "Shot 4" by position while ids can differ after a delete, so the plan the model reads carries both.
- The first item in Add was the project's own song. It is now marked as already added.

**Differs from the mockup:**

- "Review each step" is left out: it does nothing until there are steps to review, in CS2.
- Cut speed stays in the brief, because changing it means planning again.
- Parts keep their headings over the grid of shot cards, because "Try another idea" works per part.
- The shots' picture areas are empty, and shots are added from a button on each card instead of a last card.
- The word check's "image" count went from 28 to 30 for the Image tab and the Images menu, the names the owner approved.

**Not built, in their stages:** CS2: the Image and Video tabs, file drop in Add, the preview stage, Shots. CS3: the Music tab, Voice captions, Titles tab, timeline, Cut. CS5: the rest of Voice, Lip sync. CS6: the 3D tab, phone polish. Those tabs say which step brings them and open the screen that makes it today.

**Not checked:** the real Tauri window (a WKWebView stand-in was used). Other chat models: only 8B was evaluated, and the owner's selected 27B on Ollama was not. Qwen3.5-9B was not retested.

## Web

Desktop first, like Train. On the web the same screens would use engine workers (ADR-0087) for analysis, stills, clips and the cut, one
job per person (ADR-0088), and need the GPU host (P7). `docs/web-parity-ledger.md` gets a row when CS1 starts: **soon, desktop first
(owner)** until a web stage is planned.

## Consequences

* The video product's work changes from "one clip at a time" to "a project made of many shots", and the first time we keep a plan
  document that a model writes and a person edits. The checkpoint, revision, cancel and resume machinery built for it will also serve
  audiobooks, dubbing and long Train runs.
* The result on a Mac will be **gentler than hosted tools**: mostly pictures with camera moves, some short animated shots, a few sung
  close-ups with a still head. The screen and the help file say so.
* A timeline is a new kind of document and a new class of bugs (undo, trim, sync). Keeping it small in v1 is deliberate.
* A beat and section tool is probably a new dependency; it will be asked for.

## Risks

* **Quality may disappoint.** LTX 0.9.5 motion is gentle; faces hold reasonably with reference pictures but objects and places drift;
  MuseTalk on singing is a still portrait with a moving mouth (CS0). The owner accepted this as a draft. Mitigation: the goal is an honest
  draft and Hold is acceptable on its own.
* **A small model may not plan well enough.** CS0: with most of the plan owned by code it stays in order and uses every place, but details
  still drift ("grey car" then "red car") and some lines cannot be shot. Mitigation: a small schema, the code owns the facts, repairs touch
  only bad rows, the person is the reviewer and will edit.
* **Time.** A 3-minute song is about 15 minutes for a plain preview, about 30 with reference pictures and about 2.4 hours more for full
  motion on this Mac (worked out from CS0's measured parts, not measured end to end). 16 and 32 GB Macs are unmeasured.
* **Scope creep toward a full editor.** The decision keeps v1 to one picture track, a song and captions.
* **Copying by accident.** The rule: nothing is copied; the study records ideas only; prompts, guides and
  schemas are written fresh; a reviewer checks the diff of each stage for anything that reads like theirs.
* **Naming.** "Studio" names were avoided on purpose in this project (open question 1).
* **Real people and songs:** deepfake and copyright risk; consent answers, safeguards and local-only reduce it; terms of service are
  still missing (backlog B4) and block a public release of video features.

## Not decided here

A hosted provider for clips (a later, opt-in idea with its own ADR); an audio-driven video model such as LTX-2.5 on the Mac (a new
runtime and an amendment to ADR-0066 and ADR-0037); more skills (podcast, a short viral clip); a queue of many projects (ADR-0088
limits one job per person for now); notifications; a web stage; non-English interface text.

## Owner's answers (2026-10-24)

The owner took the recommendation on every question.

| # | Question | Answer (decided) | Where it landed |
|---|---|---|---|
| 1 | Name and place | **Creative Studio** is the menu label, after Music and before Motion graphics; the product id is `wasifyai-creative`; no "Studio" in identifiers (components say Workspace); sentence case in every label | How it fits the product; risks |
| 2 | First skill | **Music video first**, then Story (CS5) | Decision 3 of the plan; stages |
| 3 | How big is Cut in v1 | **Small**: one picture track, the song, captions; a fuller editor in CS6 | Decision 7; CS3, CS6 |
| 4 | When does CS0 start | **When the owner says**, with a disk ceiling the owner names and a yes before each download; downloads deleted afterwards | CS0 |
| 5 | Characters | **Reference pictures and a look in words in v1**; Train LoRAs and saved voices join in CS5 | Decision 10; CS5 |
| 6 | Project size | **One project at a time per person** (ADR-0088); no overnight queue in v1 | Decision 8 |
| 7 | Web | **Desktop first, the web after CS4**, as with Train | Web |

## Open questions for the owner

Answered 2026-10-31: yes to PyTorch and beat_this (about 900 MB; 926 MB as installed). CS0 answered the rest
(`docs/spikes/creative-cs0.md`).

## Amendment: the screen, and how every product plugs into it (2026-10-24, owner; **Accepted** 2026-10-31)

**Accepted 2026-10-31.** The owner: "Yes to the screen amendment with your three recommendations: Titles tab, the Plan, Shots, Cut buttons, and the mockup as it is. Build it into Creative Studio." What is built so far is under "Built" as "The screen".

**The ask.** The owner showed Maestro's Studio screen (a tool column on the left that makes things, a big preview in the middle, a rail
of everything made on the right) and asked for a similar, friendly screen that lets a person use **all of our products and tools** inside
the video editor and studio. **Mockup:** `docs/spikes/creative-studio-mockup.html` (the Cut view with the Make panel on Video, the Plan
view, and a phone; light and dark). The mockup is made of colour sketches, not real output.

**One screen, four regions**, the same in every step (Plan, Shots, Cut):

| Region | What it is | Notes |
|---|---|---|
| **Make panel** (left, 300 px) | tabs for what to make, a sub-tab per product mode, that mode's form, the honest line, **one button to make it** | the same forms as our screens, in a narrow layout; the result goes to this project |
| **Stage** (middle) | a large preview of what is selected, filters above it (All, Pictures, Clips, Voice, Music, Titles), what made it and how long it took below, actions: edit the prompt, redo, use in the cut, save a copy, mark good, delete | in Plan the stage is the plan (a strip of the song and a card per shot); in Shots a grid; in Cut the video |
| **Media rail** (right) | everything made **for this project**, newest first; click to preview, drag onto the timeline | it is the library filtered by the project, not a second copy |
| **Timeline** (bottom, Cut and Shots) | pictures, titles, voice, song; cuts snap to beats; undo, split, cut speed, zoom | CS3 builds it small; collapsible |

The three step buttons (**Plan**, **Shots**, **Cut**) sit in the middle of the top bar; the **model button of the active tab** is at its
left (ADR-0086); **Review each step**, **Save a copy** and **Make the video** are at its right. On a phone the Make panel is a sheet
under the stage with its tabs as a dock, and the timeline is one row you swipe.

**The Make panel's tabs and where each product lands** ("if applicable": a product that cannot make something that sits on a timeline is
not a tab):

| Tab | Modes (the actions we already have) | What lands in the project | When |
|---|---|---|---|
| **Image** | Create, Edit, Inpaint, Reference | a picture (a still for a shot, a character picture) | CS2 |
| **Video** | Create, Animate, Extend, Lip sync | a clip (a take of a shot) | CS2 (Lip sync CS5) |
| **Voice** | Speak, Clone and design a voice, Change a voice, Edit speech, Dub, Audiobook, Speech to text | an audio clip (a spoken line, narration) or timed words (captions) | CS3 (speech to text for captions), CS5 (the rest) |
| **Music** | Create, Lyrics, Split into parts | the song, or a stem | CS3 |
| **Titles** | the Motion graphics templates (title, quote, bar chart, lower third, captions) | an overlay with sound off, or a clip | CS3 |
| **3D** | a 3D model from a picture | later: a turn-around clip (the product does not make one yet, backlog) | CS6 |
| **Add** | pick from Library, or drop a file from this computer | any picture, clip or sound | CS2 |
| **Ask** | the assistant, with this project open ("make the last part moodier") | changes to the plan (`creative.edit_plan`) | CS1 |

Train stays its own screen (training takes long); a trained character or style is **chosen** in the Make panel (decision 10). Notebooks stay
their own screen; a person can paste their text in the brief. Models and Library stay where they are.

**How it is built, without a second copy of any product:**
1. Each product's shared workspace (`ImageWorkspace`, `VideoWorkspace`, the voice workspaces, `VideoBuilder`) gets a **panel layout**: the same
   component, one narrow column, no gallery, no library tabs, with an `onMade(asset)` callback. The full screens do not change. The forms
   and checks (consent, fit, safeguards) are the product's own, so a panel cannot do what a screen cannot.
2. What a panel makes is **saved to the library exactly as today** and tagged with the project id and, when made for a shot, the shot id. The
   media rail and the search are the library filtered by that tag. Deleting the project asks whether to keep or delete what was made for it.
3. The panel's "**Used in** Shot 7" line says where the result will go: **a new take of the selected shot**, or **unused** in the rail. The
   person decides in the timeline; nothing replaces a chosen take without a click.
4. **One job per person** (ADR-0088): while a project run is going, the panel says so and offers to wait; a single piece made by hand is a
   job like any other.
5. **Actions:** each panel button calls the product's existing action with the project and shot ids added as optional inputs, so the
   assistant, MCP and the screen all do the same thing. No new action is needed for the panels themselves.
6. **Keyboard and screen readers:** tabs are a tablist with arrow keys; the timeline items are a labelled list; space plays, S splits, the
   arrow keys nudge, Z undoes; every button has a name and a state ("Make this clip, about 1 minute 15 seconds, fits"); reduced motion is
   respected. Design tokens only (ADR-0081).

**What changes in the stages** (sizes in working days; the totals move from 24 to 28 for CS1 to CS4):

| Stage | Adds | Size |
|---|---|---|
| CS1 | the four-region shell (Plan view with the Ask tab and the empty Make panel), the media rail, the project id on library items | +0 (inside CS1's 7) |
| CS2 | the Image and Video tabs in panel layout, Add, the preview stage | +2 |
| CS3 | the Music, Voice (captions) and Titles tabs; the timeline | +2 |
| CS5 | the rest of the Voice tab and Lip sync | +1 |
| CS6 | the 3D tab (when a turn-around clip exists), the phone polish | +1 |

**Questions for the owner, answered 2026-10-31: all three as recommended.**
1. **The tab for Motion graphics is called Titles** in the mockup (the screen keeps its name, **Motion graphics**, in the side menu). OK? Recommend yes: on
   a timeline people think "titles", and the tab opens the same templates.
2. **Is the three-step button (Plan, Shots, Cut) at the top the right way to move between steps**, or do you prefer Maestro's two-mode toggle
   (a Director view and a Studio view)? Recommend the three steps: they are the order of the work, and the Make panel is in all three.
3. **Do you want to change anything in the mockup** (the regions, the tabs, the words)? Say what, and I will change the mockup before any code.
