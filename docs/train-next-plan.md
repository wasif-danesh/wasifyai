# Train: the next three stages (data in, expert settings, the run view)

Date: 2026-10-26. Written after the gap analysis of the installed Unsloth Studio 2026.10.6 (REA on its shipped frontend,
evidence `ev_2eaffbaa...` and `ev_71f17fbe...`; what it showed is in the conversation, not repeated here). ADRs: 0073 (platform and
the simplicity rules), 0074 (language), 0076 (pictures). Nothing here changes an Accepted decision; stage 2 builds what decision 5 of
ADR-0073 and its amendment of 2026-10-24 already promise ("For experts", the closed choice).

**Order: 1, then 2, then 3.** Each stage is useful alone, ships behind no switch (rule: no feature switches), is checked with the real
engine and a real run before it counts as done, and ends with a one-line commit for the owner.

Sizes are the plans' usual S / M / L: S is under a day of work, M a day or two, L several days.

## Stage D1: data in (a file of examples, not only typing) — M

**Why first.** The first thing anyone with real data hits: 500 examples live in a spreadsheet or a `.jsonl` file, and the screen takes typed rows
and a pasted two-column block. Unsloth takes uploads, Hugging Face datasets, three chat formats, a format check and splits.

**What a person sees.** On the examples step, next to "Add an example" and "Paste from a spreadsheet": **"Add from a file"**. They choose a
CSV, TSV, JSON or JSONL file. The app reads it, says what it found in words ("1,240 rows; the first columns look like a question and an
answer") and shows the first five rows in the same two boxes. If it cannot tell which columns are which, the person chooses two from a list.
Nothing is uploaded anywhere: the file is read in the window and the rows go to the engine as the typed ones do.

**Formats (the ones people actually have).**
- CSV and TSV with a header: the two columns chosen by name, guessed from common names (`question`/`answer`, `prompt`/`response`,
  `input`/`output`, `instruction`/`output`).
- JSONL and JSON arrays: chat records (`messages` with a user and an assistant turn), `{prompt, completion}`, `{instruction, input, output}`
  (alpaca; `input` is joined to the instruction), and `{question, answer}`.
- A record with more than one exchange or a system message is **not** silently cut: it is listed as "left out: 12 rows have more than one
  exchange (multi-turn is not supported yet)". (ADR-0074: single exchanges only, for now.)
- Not in this stage: Parquet, Excel, Hugging Face datasets by name (they need a download, a token and a licence step: stage D1b, later), PDFs
  and documents (ADR-0074's "from a document", separate).

**How.**
- A pure module `products/wasifyai-training/wasifyai_training/importer.py`: `read(text or bytes, filename) -> Imported(rows, left_out,
  columns, guess)`, no model and no file system, so it is tested on fixtures and on hostile input (huge cells, wrong encodings, BOM, CRLF, a
  CSV that is really a spreadsheet export with a title row). Limits: 5 MB a file, 5,000 rows read, then the existing 2,000-example cap says
  what was kept.
- Reading happens in the window (the file is the person's; Tauri's dialog plugin is already used for Save As, an `<input type=file>` works in
  the browser pane and the web): the module is Python, so the window sends the file's text to a new route
  `POST .../writing/sets/{id}/import` with `{filename, text, columns?}` that answers the preview (not saved) and `PUT .../examples` saves, as
  today. One route, no new storage.
- The importer feeds the **existing** checks (`language.clean`, personal-data warning, split) unchanged, so a 2,000-row file gets the same
  sentences as typed rows, plus the importer's own "left out" lines.
- The window: `Writing.tsx` gains `ImportFromFile` (a chooser, the column pickers, the preview, "Add these N rows"); no new dependency. Copy
  stays generic ("What it is asked" / "What it should answer").
- Pictures' side: not in this stage (a picture set is pictures; its descriptions are already written by the app).

**Done when** (all measured, none assumed):
- Tests: the importer on a dozen fixtures (every format above, a BOM, semicolon CSV, 20,000 rows, a 30 MB file, an empty file, a file with only
  a header, binary garbage); the route; the window (choose a file, pick columns, preview, add; an error in words).
- A real run: a 1,000-row JSONL file (made from the T0 fixture and a public-domain Q and A set; not the owner's data) through the screen to a
  taught model, with the time and memory of a 1,000-row run measured for the three bases (the ADR's time estimate is for 50 rows).
- Help file and ADR-0074 "Built" section updated; the help file lists the accepted formats.

**Decisions for the owner.** (1) Is a 5 MB / 5,000-row limit right, or should a bigger set be allowed (it changes the time and memory
the screen promises)? (2) Hugging Face datasets by name (D1b): wanted, and if so is the licence step ("this dataset's licence is X") acceptable on
the main path? (3) Multi-turn: keep refusing it, or is it the next language stage?

**Risks.** Encoding and delimiter guessing (a wrong guess silently mislabels columns, so the preview is mandatory before adding, and the
columns are always shown); personal data in an imported file (the existing warning covers emails, phones, card numbers; it is a warning, not a
guarantee, and the help says so); a 2,000-row run is a different time and memory from 50 rows (measured in the "done when").

## Stage D2: expert settings, closed by default — M

**Why second.** The amendment of 2026-10-24 and decision 5 promise a collapsed "For experts"; it is not built. Unsloth exposes about thirty
settings on the main screen, which is what we decided against; it also keeps them for people who need them. D1 makes bigger runs possible, which
is when someone needs the steps, the learning rate or the sequence length.

**What a person sees.** Inside the existing closed "Choose the model and method", a second closed line, **"For experts"**, with a small number of
settings, each with its default (the recommendation) shown next to it and a "Reset" that restores it:
- **Steps or passes** (instead of Quick/Better's two numbers), **learning rate**, **batch size**, **maximum length** (tokens per example),
  **LoRA rank** (and alpha follows), **dropout**, **learning-rate schedule** (constant or cosine), **seed**.
- Warm-up and weight decay stay out until they are measured to matter.
- Each setting says in a sentence what it does and what a larger value costs ("more memory", "slower"), and the screen shows the **updated
  estimate** (time and memory) as it changes, from the measured per-base numbers.
- **Save and load a configuration** as a small file (the person's own YAML, as in decision 5), read with the same care as stage D1's files.
- Nothing here appears unless "For experts" is opened; the main path is unchanged.

**How.**
- One typed model, `LanguageSettings`, in the product (`language.py`): every field with a default, a range and a reason; the run stores the
  values it used on the model card (`card.settings` already exists). `writing_sets` gains `settings` (JSON, a migration like the earlier
  ones); absent means the recommendation, so every earlier caller works.
- The engine's `config_for` already builds the `mlx_lm.lora` config; it takes the values instead of constants. **Ranges are measured, not
  guessed**: before the screen accepts a rank or a length, a real run at the extremes on the three bases records memory and time; a value
  that would not fit is refused with the same `fit` sentence as today.
- The picture side gets its own, shorter list (steps, learning rate, rank, resolution) in the same closed line, from the measured picture
  numbers (`trainer.steps_for` and `SIDES`); it is the second half of the stage and may ship after the language half.
- Methods beyond QLoRA stay listed with their reasons (full fine-tuning is the open question of the earlier answer: a measurement on the 0.6B and
  1.7B is a task of its own and is included here as step D2.5, "measure full fine-tuning; turn the row on only if it fits comfortably").

**Done when.**
- Tests: ranges and defaults, the migration, the estimate, a refused out-of-range value with its sentence, save and load of a configuration,
  hostile configuration files.
- Real runs: each setting at its extremes on the 0.6B, 1.7B and 4B (time, peak memory, held-out loss), written into the descriptors and the
  ADR; one run through the window with a changed rank and learning rate, and its card showing them.
- The closed line is closed by default in the window (a test), and the main screen is byte-for-byte what a person without "For experts" sees today.

**Decisions for the owner.** (1) Which settings are in the first list (the one above, or fewer)? (2) May a person raise the step count past the
measured ceiling (600), with a warning, or is the ceiling firm? (3) Is saving and loading a configuration file wanted now, or after the
settings are used for a while?

**Risks.** Every exposed setting is something support has to explain, so the first list is short; a setting without a measured range is not
exposed. Overfitting is invisible to a person who changes the learning rate, so the run view of D3 (loss on the kept-back answers) is what
makes expert settings safe; **if D2 ships before D3, the "did it learn" mark is the only guard**, which is why D3 follows at once.

## Stage D3: the run view and the history — M

**Why third.** Today a run is a percentage and then a result. Unsloth shows a live loss chart, evaluation loss, GPU use and the run history.
A person who changed a setting needs to see whether it is learning, and a person who ran five times needs to compare them.

**What a person sees.**
- **While it runs:** under the progress bar, a small **loss line** (how wrong the answers are, falling) and, at each check, a second line for
  the kept-back answers; one sentence ("it is learning" / "the checks have stopped improving: more steps may not help") and the memory the run
  holds now.
- **After:** "My models" keeps its card; a new **"Runs"** list shows every run of the person's: model, kind, date, base, steps, time, the mark,
  and the two loss numbers. Opening one shows its chart, its settings and its before and after answers (already kept on the card). **Compare two
  runs** side by side (their settings and their marks); the comparison names what differed.
- **Stop and keep:** a run can be stopped and its last checkpoint kept (the picture side has pause and resume; language has stop-and-discard
  only). Stage D3 adds the language side (`mlx_lm.lora` writes a checkpoint every 25 steps and takes `--resume-adapter-file`).
- Words, not jargon: "how wrong the answers are" and "answers you kept back"; "loss" appears only in the closed expert section.

**How.**
- `mlx_lm.lora` already prints `Iter n: Train loss ..., Peak mem ...` and `Val loss`; the engine parses them today and reports only the step.
  Keep the series: a `metrics` column on `runs` (JSON: `[{step, train}, ...]`, `[{step, val}, ...]`, capped at 2,000 points, thinned at
  the end), written by the progress callback; the routes already return the run, so the chart reads it. No new endpoint for the live view;
  one `GET .../runs?kind=` filter for the list.
- The picture side: `mflux-train` writes its losses (a `loss` folder in the output and a plot frequency in the config): read the same way, in
  a second step.
- The chart is a small SVG component in `packages/ui` (**no chart library** is added; it is two polylines, axes in words and a keyboard-
  and screen-reader-readable summary line); the design tokens' colours (`pnpm design:check` must stay clean).
- Resume for language: `LanguageJob.resume`, the same `Paused` and `Stopped` types as pictures, the settings of D2 stored so a resumed run
  continues with the same ones, the learning-rate schedule restart noted honestly in the card (mlx-lm restarts it).
- GPU/memory line: `process_footprint` already samples every 5 s for the card; the same number goes to the live view.

**Done when.**
- Tests: the series parser and thinning, the migration, the routes, the chart (renders, empty, one point, thousands), the Runs list, compare,
  pause and resume of a language run with a fake engine and with the real one (stopped at step 30 of 69, resumed, finished; the resumed run's
  adapter answers like an uninterrupted one on the fixture).
- A real run on each base through the window: the chart on screen during the run, the numbers on the card equal to the engine's log (checked
  by script, not by eye).
- ADR-0074 and the help updated; the chart's text equivalent is tested with a screen-reader query.

**Decisions for the owner.** (1) Is "compare two runs" wanted, or only the list? (2) Weights & Biases and TensorBoard (Unsloth offers both):
not planned (they send run data to a service, which is against "nothing leaves"); say if you want them as an opt-in later.
(3) Run history for pictures and language in one list, or one list per card?

**Risks.** Small sets give noisy losses (a line that jumps is shown with a sentence, not interpreted); a chart invites over-reading, so the one
sentence under it says only what the numbers allow; storing the series grows the database slightly (capped).

## What each stage needs that does not exist yet

- D1: a small importer module and one route, nothing new installed.
- D2: a `settings` column, a typed settings model, and measured ranges (a batch of real runs: about an hour of machine time).
- D3: a `metrics` column, an SVG component, language resume. No dependency.
- **No new dependency in any stage** (rule: ask before adding one). If a chart library or Parquet reader is wanted later, it is asked then.

## After these three

Decision (sorting) training with a spike first (ADR-0075; Laya measured at 9 s on this Mac in T0); Hugging Face datasets by name (D1b);
vision and embedding language models; merged-model and standalone GGUF export; synthetic data (Unsloth's "data recipes"); an
OpenAI-compatible server with keys. Each is its own plan; none is started.
