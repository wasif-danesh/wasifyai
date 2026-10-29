# ADR-0075: Training a decision model: "teach the app to sort and judge things"

- **Status:** Accepted (2026-10-18, by the owner), together with the components it names. Replaces the first draft of this number,
  "Training a diffusion model beyond LoRA", which misread the owner's words (that content now lives in ADR-0076,
  section "Beyond LoRA").
- **Date:** 2026-10-18
- **Depends on:** ADR-0073 (training platform; read its revision note), ADR-0068 (action catalogue), ADR-0071 (the
  assistant), ADR-0072 (agents), ADR-0061 and ADR-0062 (how Unsloth code enters, the reuse matrix), ADR-0047.
- **Plan:** `docs/phase5-agent-training-video-builder-plan.md`, stage T5.

## Context

The owner's screenshot of **Unsloth Studio, Train > "Train as"**, shows two choices: *Language model* and *Decision
model*. The owner meant that. The text beside it in Studio (`i18n/locales/en.ts`, read 2026-10-18): "A language
model writes text. A decision model picks one of the options you give it, with a probability, and runs in the
Decision API."

What a decision model is, from the reference clone (`~/Projects/unsloth`, `studio/backend/core/systemone/`,
`routes/systemone.py`, `core/training/decision_trainer.py`):

- It answers **typed questions about a text**. Three types: **`noul`** (yes or no, with a probability), **`choice`**
  (one of several named options, each described, with a probability per option) and **`score`** (a level from 1
  to 10, lowest first). One request can ask up to 64 questions about the same text ("Is it urgent? Which
  department? How angry is the tone?").
- Three **layouts**: **Laya** (an encoder model on ModernBERT or mmBERT; about 0.7 to 0.85 GB; English, or 100+
  languages with a 1,024-token context), **Clef** (Cloudflare's models on a Qwen3.5 backbone with a schema head,
  9B or 27B, **GPU only**), and **an LLM trained with a decision head** (text or vision, trained with QLoRA).
- **Training data** is rows with the text (`state`), the questions, and the right answers (`gold` or `answers`).
  Studio trains from a CSV, JSON, JSONL or Parquet file or a Hugging Face dataset; the trainer has an Apple
  silicon (MLX) path, and decision models export to GGUF for llama.cpp's server or have an MLX form for serving.
- Studio serves them on `POST /v1/systemone` (the Decision API) and as an MCP tool `decide`.

Why this is good for the app's goal (non-technical people): it is the **easiest thing to teach** and the most
visible win. A person can say "sort my support emails into billing, bug, other" or "tell me if this review is
positive" from a spreadsheet of examples, get a small, fast, private model with **honest confidences**, and use
it from anywhere in the app. It needs little memory (Laya is under 1 GB), trains in minutes, and its quality is
measurable on a held-out set. It is not what a chat model is good at (a chat model gives uncalibrated, slow,
sometimes inconsistent labels).

What we do not know and must find out (spike T0): whether **Laya trains and serves on the Mac** without Studio;
how well it does against a plain classifier on embeddings; and what serving it needs (Studio's runtime is
in-process).

## Decision

1. **Offer it as "Sorter"** (screen name: **Teach it to sort**), never as "decision model". Three kinds, in the
   person's words: **Pick a category** (`choice`), **Yes or no** (`noul`), **Score from 1 to 10** (`score`).
2. **The input is a spreadsheet.** The person drops a CSV or Excel file (or pastes rows, or picks a folder of text
   files with the label in the file name or a sub-folder) with **a text column and a label column**. The app
   builds the rows the trainer wants (`state`, `questions`, `gold`) itself. For categories, a language model drafts a
   one-line description of each from the examples and the person edits them; for scores, the person writes what a
   low and a high score mean. Nothing about columns, splits or schemas is asked.
3. **The app checks the data and says what it found,** in words: labels that differ only by case or spaces ("Urgent"
   and "urgent"), a category with fewer than 10 examples, duplicate texts with different labels, texts far over
   the model's context, an imbalance ("90 percent are 'other'"). It holds out 15 to 20 percent for evaluation
   without asking (a stratified split, a fixed seed).
4. **The model is chosen by the app.** Default: **Laya** (multilingual if the texts are not English): small, quick,
   runs on any computer in the app. "More accurate (needs a strong GPU)": Clef or an LLM with a decision head, offered
   only on an NVIDIA machine or a rented GPU (ADR-0073 tiers), and on the Mac only if the spike shows the MLX
   decision-head path works. The screen shows one recommendation and a "see other options" link.
5. **Training and serving come from Unsloth through the component** (ADR-0073 decision 4): the decision trainer
   and the Laya runtime, driven by our adapter. Studio's code stays a **separate, pinned
   component** (ADR-0061 decision 3), not linked into our core.
6. **The result is "a sorter" in My models** with its model card and **an honest report**: accuracy on the held-out
   set in plain words ("right 91 times out of 100"), how it does on each category, which categories it mixes up
   ("it often calls 'refund' 'billing'"), a calibration note ("when it says 90 percent, it is right about 90
   percent of the time" or not), and **ten examples it got wrong** with the correct answer. A baseline is shown beside
   it (a plain classifier on text embeddings, trained in seconds), so the person can see whether the teaching
   helped. A sorter that does worse than the baseline is flagged "did not pass".
7. **Using it is an action.** `decision.decide(text, question)` joins the catalogue (ADR-0068; effect `read`),
   available to the window, the assistant (ADR-0071: "sort these"), agents (ADR-0072) and MCP clients (ADR-0069).
   In the window: **Try it** (paste a text, see the answer and its probability), **Sort a folder or a
   spreadsheet** (adds a column or moves files into sub-folders, never overwrites), and later **auto-tag** new notes
   or sources. A loopback-only endpoint for other programs is an option, off by default.
8. **It runs beside the chat model.** Laya is small enough to stay loaded on demand without evicting the chat model;
   the slot manager (ADR-0056) treats it as a light owner, to be confirmed by measurement (T0). Clef-sized models
   take the slot like any other.
9. **Privacy and responsibility.** Data stays on the computer (a remote tier shows what is sent). Because a sorter
   can be pointed at decisions about people, the screen carries a short notice ("Use this to sort and flag things,
   not to decide about a person's job, credit or safety") and refuses nothing automatically.
10. **Safeguards.** The training texts pass the text moderator when the safeguards are on (ADR-0047).

## Consequences

- A second kind of trained model with a clear, measurable use and a tiny footprint. It also gives the assistant and
  agents a cheap judgement tool.
- A dependency on Unsloth's decision models.
- The spreadsheet-to-rows conversion is ours and must be exact: the trainer validates every question the way the
  Decision API does, and a mistake is a failed run.

## Alternatives considered

- **Ask the chat model to classify** (a prompt with the options). Works for one-off questions and is what people do
  today; slow, uncalibrated, and inconsistent across runs. Kept as the baseline for "is training worth it".
- **A classical classifier on embeddings** (logistic regression). Tiny and quick, and the baseline above. It does not
  give typed multi-question output or the same accuracy on subtle labels. Kept as the fallback if the Unsloth path
  fails.
- **Fine-tune a language model to emit labels** (ADR-0074). More flexible, slower and less calibrated; available to
  people who want it under language-model training.
- **Skip it.** Possible; it is the cheapest training feature to ship and the one non-technical people understand best.

## Open questions

1. Whether Laya trains on the Mac (the trainer has an MLX path for the LLM layout; Laya's is unknown) and how fast.
2. How a sorter is served inside our engine without Studio: Laya through its own runtime (Studio vendors laya 0.3.5),
   a GGUF through our llama-server, or an MLX form; the Decision API's request shape (`noul`, `choice`, `score`) is
   kept as our action's schema so any of them can serve it.
3. Whether `score` questions need examples per level (they do for quality); the screen asks for at least five per level.
4. Image sorting (a vision LLM with a decision head): later.

## Not in v1

Clef and the LLM decision heads on the Mac; sorting images or audio; continual learning from corrections (a "that was
wrong" button feeding a retrain is the natural next step and is named in the plan, stage T5b); sharing sorters.

## Amendment after spike T0 (2026-10-19; `docs/spikes/training-t0.md`)

- **Laya trains and serves on the Mac through Studio's MLX decision trainer:** 30 steps in 9.2 s of training (12.3 s
  wall), 15 ms per answer, 2.4 GB resident. Laya through its own MPS script was **not tested**.
- Clef-flash was **not run** (19 GB, not approved), and Studio's code suggests it may run on the Mac, so "GPU only"
  (decision 4) is untested rather than known.
- **Stage T5: Go.** The `decision.decide` request shape is unchanged.

## Amendment (2026-10-26, owner): the card is "Teach it to decide"

"Teach it to sort" described only one of the three kinds (a category); the model also answers yes or no and gives a score. The
card, the screen and the help are **"Teach it to decide"** (decision 1's three kinds keep their names: Yes or no, One of several,
A score). The family label stays "Decision model training" so a person looking for it finds it. The example under the title is
"Is this review positive?". Decision 1's words "Sorter" and "Teach it to sort" are replaced; the rest of the decision stands.

## Built (2026-10-26, later): stage T5, "Teach it to decide" on the desktop

Built, and run for real on the owner's Mac (M5 Pro, 64 GB), through the real routes and the real engine, with the app's own installer on a
clean data folder. What is true:

- **Engine: the `laya` package (0.4.15) on PyTorch (MPS), not Unsloth's component.** Laya ships its own trainer
  (`laya.train.finetune`: it splits off a tenth of the examples to fit how sure the model should be, trains, calibrates, and writes the
  checkpoint `laya.load` reads). Using it directly avoids Studio's component of decision 5 for this family. **Laya teaches the
  whole model** (420 million numbers), so a result is a full copy of about **846 MB**, not a small adapter, and the descriptor lists LoRA and
  QLoRA as "all of it is taught", with the reason. The spike's Studio route did the same (`docs/spikes/training-t0.md`, section 5).
- **Set up in the app (`decision_setup.py`, `decision_pins.json`):** the same shape as the writing trainer's. 35 packages from a committed
  hashed lock (`scripts/lock-decision-trainer.sh`; torch 2.14.1, transformers 5.20.2, laya 0.4.15; **168 MB** of wheels by PyPI's metadata,
  692 MB on disk) and the model's 5 files pinned by size and SHA-256 (`convaiinnovations/laya` at revision `7b928d82`, **846.2 MB**); the model
  for many languages (`multilingual/`, mmBERT, **678.2 MB**) is fetched when it is chosen. **Run for real:** on a clean folder the screen's
  offer was 1,013,795,574 bytes and the install took **66 s**, every file checked, `import laya, torch` passing from it; the multilingual model
  came through the same downloader.
- **The measurements** (real runs through `POST /train/decision/sets/{id}/runs`, texts written for these runs, so they show the pipeline works
  and what it costs, not how good a sorter is on someone's data): yes or no (128 examples, 36 steps): **41 s** in all (33 s of learning), **11.0 GB**
  peak; one of several (171 examples, 48 steps): **45 s**, 11.0 GB; a score 1 to 5 (79 examples, 24 steps): **25 s**, 10.0 GB. About **0.85 s a
  step** (a step is a batch of 8) and 9 s to load, ask before and after, and save 846 MB. Every model it made is 846 MB. Asking a taught model
  one text takes **4.3 to 5.0 s** (the model is loaded for each question) and **100 texts take 2.8 s**.
- **The report (decision 6):** `decision.report` counts, on the texts kept back (about a fifth of every answer, at least one of each, a fixed
  seed): right before the teaching (the base Laya), right after, and right for **a plain word counter** (multinomial Naive Bayes on the words,
  trained in milliseconds: the plan's "embeddings baseline" was not built, the word counter is what a person could do without this feature); per
  answer; the three most common mix-ups; whether its confidence holds ("When it said it was at least 80 percent sure, it was right 10 of 10
  times"); up to ten texts it got wrong; and the mark: **passed when it is right at least as often as the word counter and as before the
  teaching**, else "did not pass: a plain word counter did better". A score counts a level off by one as right (and says so). The three
  test sets above were easy: the word counter scored the same (100, 97 and 100 percent), so the mark said "passed" and the note says the word
  counter did as well, which is the honest result. **A case where counting words fails** (92 examples where the answer is the feeling after
  "but", so the same words are on both sides: "The camera is superb, but delivery took a month."): after teaching it was right **15 of 16**
  (94 percent) on texts it had not seen, before teaching 8 of 16, and the word counter **5 of 16** (31 percent); 25 s, 10 GB; its one mistake was
  said with full confidence, which the report's confidence line shows ("at least 80 percent sure, right 15 of 16 times"). **The model for many
  languages** (fetched through the same downloader, 678.2 MB, its first attempt cut off at 525 MB and continued from there): yes or no on
  reviews in Spanish, French, German and Bengali (81 examples, 24 steps) took **22 s**, **9.3 GB**, and was right 15 of 15 against 12 of 15 for the
  word counter; the taught model decided a Bengali review correctly where the untaught one did not (0.67 sure of the wrong answer). v1 is
  English only (the owner's rule); this is offered, labelled and measured, not promised for every language.
- **Product (`products/wasifyai-training`):** `decision.py` (the question, clean, checks in words, stratified split, steps, word counter,
  report), `decisions.py` (the run manager and `decide`), `decision_routes.py`
  (`/train/decision/status|sets|sets/{id}|sets/{id}/examples|sets/{id}/runs|models/{id}/ask|models/{id}/sort`), store tables `decision_sets`
  and `decision_examples`, model `kind = "decision"`, run `settings.family = "decision"`. One run at a time across pictures, writing and
  deciding (the picture run refuses while another is going: the slot manager would otherwise stop it). Searchable by name, kind and
  the question (ADR-0041).
- **The checks (decision 3), in words:** at least 20 examples; at least two different answers; a warning under 60, for an answer with fewer
  than 5 examples, for 90 percent or more on one answer, for the same text with different answers, for texts over 2,000 characters (the model
  reads about that much) and for what looks like personal data; labels that differ only by case or spaces are made the same and rows whose
  answer is not an option are left out, with a sentence for each.
- **Using it (decision 7):** the **action `decision.decide`** (effect `read`, up to 100 texts; the catalogue's bound is now 51 and its test says
  why) with its help file; in the window **Try it** (one text, beside the model it started from) and **Sort a list** (one text a line, a table
  that can be copied into a spreadsheet; no file is saved: the window has no download). `train.start` takes `decision_set_id` as the third
  set it can teach.
- **The screen (`Decide.tsx`):** the card is live ("Teach it to decide"); Start opens the sets; the editor has the question (yes or no, one of several
  with what each means, a score with what its ends mean), the examples (a grid with an answer list, pasted from two spreadsheet columns or
  opened from a CSV file: quoted cells, commas, semicolons and tabs, and a header row are read), the check, whose the texts are, the closed
  "Choose the model and method" line, **Teach it**, the report with three numbers side by side, and the two boxes. Nothing says encoder, loss or
  calibration.
- **Not built:** the Hugging Face dataset and JSON/JSONL imports (stage D1); the model kept warm so a first answer is not 4 s; auto-tagging
  new notes and sources and moving files into folders; the endpoint for other programs; Clef and the LLM decision heads (not run:
  19 GB and no need yet); the web (the trainer is the desktop's); sharing a sorter; "that was wrong" feedback (T5b).
