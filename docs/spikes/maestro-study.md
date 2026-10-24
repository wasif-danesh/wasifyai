# Study: how Maestro builds its Director, Studio and Editor (read for ADR-0090)

Date: 2026-10-24. Source read: `~/Projects/Maestro` (release v3.2.0, git `6e6d8aa`, 89 MB, about 657,000 lines of Python and
TypeScript including vendored models). Method: the README and 14 of its docs, then the code of the Director (`app/services/director*`,
`director_pipeline.py`, `audio_analysis.py`, `director_music_timing.py`), the Editor (`app/services/editor_projects.py`,
`ui/src/editor/*`, `ui/src/types`), the character library, the recipes, the enhancement guides and the Dashboard.

**What this is not.** Maestro was not run: it needs an NVIDIA GPU and its licence (WanGP Non-Commercial Evaluation License 1.1)
forbids using it in a paid product, a hosted service or an integration. The owner allowed reading it for research (2026-10-20). **No
code, prompt text, guide text or schema was copied.** Everything below is described in my own words, at the level of ideas, and the
numbers are the ones its own docs and code state. What Maestro's output looks like was not seen; nothing here says it is good.

## The shape of the product

Maestro has three modes over one set of output folders ("workspaces"):

| Mode | What the person does | What it is underneath |
|---|---|---|
| **Studio** | Pick a model and a workflow (frames, references, avatar, extend, blend, retake, upscale, image, audio) and make one thing with every knob | a front for the WanGP generation engine; recipes (a model, its LoRAs by pointer, tuned settings, an example prompt) as one-click presets |
| **Director** | Give a song or a story; a local language model plans every shot; the app makes start pictures, then clips, then joins them | a pipeline thread with phases, a saved state file per project, and a render queue of whole projects |
| **Editor** | Finish on a timeline | a non-destructive project file plus an ffmpeg render graph |

The three are joined by **provenance**: a clip made by Director carries (in its saved settings and in the Editor item) which project
and which shot it came from, so it can be sent back, re-made, and returned to the same place on the timeline as another *take*.

## What Director does, step by step

1. **Brief.** Inputs: an audio track (a music video), or a story / dialogue audio (a short film); optional characters (reference
   picture or video, a name, a description, optionally a saved voice); a visual concept in plain words; the video model, a
   resolution, a target length; **Auto** (run everything) or **Manual** (stop at each step to review). Setup also shows the
   hardware-aware limit on how long one generated clip may be, and says whether that guidance is "tested", "reported" or "estimated".
2. **Analyse the song (music video).** Beats and downbeats, a loudness (onset) curve, sections with an energy label, a transcript with
   times, optionally who sings each line (diarization) and a separated vocal track, plus cheap estimates of when a sustained drum
   passage starts. Progress is reported in phases because the first run downloads models.
3. **Lay out the cuts.** A small scoring routine puts each candidate cut time on a scale: downbeats and strong beats score a little,
   section changes more, lyric-line starts and ends more, performer changes and drum entrances more. It then picks cut times that
   respect the model's longest clip, snaps them to beats and to the video model's frame grid, and renders a slightly longer clip when
   needed and trims the tail so the song's timing never drifts. A signed **cut speed** (-2 to +2) says whether cuts should be fewer and
   longer or shorter and more frequent; the result is a list of timed slots called clips.
4. **Plan the whole song first** (four or more clips). A compact *arc* of at most 48 rows: for each slot a visual beat, its purpose,
   an environment and a camera. Code checks it: it rejects filler phrases ("various cinematic shots that match the song"), copies of
   the global brief, and verbatim repeats unless the planner marked a reprise as deliberate and gave a reason. A second, small
   review pass can ask for repairs; **repairs touch only the bad rows and keep the accepted ones.**
5. **Write each shot.** The planner fills a model-neutral *shot plan*: duration, the shot's goal, who is on screen and what they wear,
   where they are placed, environment, style, lighting, mood, action beats, a camera plan (framing, angle, movement and how strong),
   an audio plan (is the soundtrack leading; is lip sync critical; who is audibly singing in this slice), how the shot ends, how it
   continues from the last one (independent, continuous, or extend the previous), what source mode it wants (text to video, picture
   to video, audio to video, retake, extend), dialogue lines with a speaker and a delivery, and constraints. Shots are written in
   small batches; each batch is saved as a durable checkpoint; each row is validated and, if it fails, repaired a bounded number of
   times, with a plain fallback if repair fails. The planner's output must be JSON that follows a schema the app hands to the model.
6. **Compile prompts per model.** *Renderers* turn the neutral shot plan into the exact prompt style of one generation mode of one
   model family (text-to-video, picture-to-video, audio-to-video, retake, extend, image generation). A separate *polish* pass, driven
   by per-model and per-LoRA guide files, rewrites for the model's quirks. A prompt checker and a compressor keep prompts inside the
   model's budget without cutting off an action or the end state of a shot.
7. **Make pictures, then clips.** A start picture (and, for some models, keyframes) is made per shot with the characters' reference
   pictures; then each clip is generated; the soundtrack slice for that clip is cut exactly; clips are joined, sometimes with native
   continuation windows so motion carries across a cut.
8. **Review and repair.** The *Dashboard* lists every past run with its clip plans, pictures, clips and the language model's planning
   requests and responses (visible on purpose, for troubleshooting). Per shot: edit the prompt, mark "good" or "needs work",
   re-generate the picture, re-run the clip, keep earlier takes. Per project: resume from a crash (planning and pictures already
   done are reused), repair only missing clips, re-join, "open and edit" as a new revision (an immutable copy of the inputs), delete.
9. **A queue of whole projects.** Several projects can be prepared, held, reordered and run overnight; a running project is never
   changed by a later edit (a new revision is a new entry).

**Short film** is the same pipeline with a story or a dialogue track instead of a song. For long stories it first writes a *story
bible* (working title, one-line story, tone contract, ending contract, canonical cast with a starting state and continuity rules,
canonical locations), then an outline of chapters and sequences, then shots per sequence, with a registry of who and what is where, a
hand-off note from one sequence to the next, and audits that catch a character appearing in an impossible place. The code owns these
registries because a small local model cannot be trusted to remember them.

## What the Editor is

* **A project file** (versioned, saved beside the media, written atomically): a canvas (size, frame rate, background); an asset table
  (references to files, with probed duration, size and audio facts, never copies); **tracks** (video, audio, title; each with a
  mute, a lock, a volume, a z-order); **items** on a track (start, duration, where in the source it begins, speed, volume, opacity,
  fit, a position/scale/rotation transform, fade in and out, a transition at each end, a group id so linked items move together, a
  list of alternative *takes*, a short *history* of AI edits, and the Director shot it came from); markers; export settings.
* **A store with an undo stack:** every change is a command on a copy of the project; selection, playhead, snapping, ripple, copy and
  paste, split, duplicate, detach audio, link, move and trim are ordinary operations; changes are saved on a timer.
* **Previews and waveforms** are generated into a cache folder from the sources, so the browser can scrub without playing the
  original files.
* **Export** compiles the project into one ffmpeg filter graph (cuts, overlays, speed, fades, transitions, text, mixing), picks an
  available hardware encoder (H.264, H.265 or AV1), and writes a *new* file; exports are recorded.
* **The AI round trip:** select a clip, send it to a Studio tool (retake, upscale, edit), and when the job finishes the result becomes a
  new take at the same position, so the edit is not rebuilt. A Director clip can also be re-run with an edited prompt from inside the
  Editor.

## Other ideas worth noting

* **Adaptive writing:** one "enhance" action that develops a short idea but keeps a detailed script's events and exact lines;
  separate guides add craft (action choreography, conversation, camera) without becoming modes.
* **Characters as portable things:** an entry is a picture or video, a name, a description and optionally a recorded voice; it can be
  exported as one file and imported on another machine; the same entry feeds image, video and speech.
* **Honesty about hardware:** auto-tuning, memory-fit labels, recommended clip lengths per GPU class with "tested / reported /
  estimated" wording, an out-of-memory banner with a one-click fix.
* **Library and provenance:** every output keeps its settings; "Load settings" opens it in Studio again; the joined video reopens the
  whole project. Search covers original and enhanced prompts.
* **Notifications and remote access** (completion sounds, push, a private tunnel) for overnight work.

## What the project's history teaches

* **Small local models drift.** The Director code is dominated (tens of thousands of lines) by checks and repairs for things a model
  gets wrong: invented characters, an object in two places, dialogue that changes, repeated visuals, prompts that restate the brief.
  The durable lesson is *the code owns the facts* (cast, places, timing, who sings when) and the model writes within them.
* **Everything is resumable.** Nearly every fix in the change log is about a run that crashed, was cancelled, or lost its place.
  Checkpoints, immutable revisions and "reuse what is done" are not extras.
* **One engine, many models** leads to per-model special cases everywhere; the neutral shot plan with per-model renderers is how they
  contain it.
* **Documentation is the interface** for a tool with this many controls; most of its docs describe controls, not ideas.

## What does not carry over

Their licence and NVIDIA requirement; the model zoo and its tuning knobs; NSFW modes; remote phone access; a 31,000-line server file;
dependence on a model (H3, LTX-2.5) that makes audio-driven video; the "Studio" name for manual generation (we have screens for that).

## Questions this study could not answer

* How good the finished videos are: no benchmark or independent review exists; the README claims are the author's.
* Whether their planning works with a 9B model on a Mac: their guides assume models they name (a 4B writer by default, larger ones
  recommended) and a CUDA GPU.
* How much of the repair code is needed for a smaller, simpler plan: only a trial on our models can say (ADR-0090, stage CS0).
