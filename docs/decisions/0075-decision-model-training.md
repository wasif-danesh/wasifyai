# ADR-0075: Training a decision model: "teach the app to sort and judge things"

- **Status:** Accepted (2026-10-18, by the owner), together with the components it names. Replaces the first draft of this number,
  "Training a diffusion model beyond LoRA", which misread the owner's words (that content now lives in ADR-0076,
  section "Beyond LoRA").
- **Date:** 2026-10-18
- **Depends on:** ADR-0073 (training platform; read its revision note), ADR-0068 (action catalogue), ADR-0071 (the
  assistant), ADR-0072 (agents), ADR-0061 and ADR-0062 (how Unsloth code enters, the reuse matrix), ADR-0012
  (licence check), ADR-0047.
- **Plan:** `docs/phase5-agent-training-compose-plan.md`, stage T5.

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

What we do not know and must find out (spike T0): the **licences** of the Laya checkpoints
(`convaiinnovations/laya`) and of Clef (`Cloudflare/clef-flash`), which must allow commercial use (ADR-0012);
whether **Laya trains and serves on the Mac** without Studio; how well it does against a plain classifier on
embeddings; and what serving it needs (Studio's runtime is AGPL-3.0 and in-process).

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
   and the Laya runtime, driven by our adapter. Studio's code is AGPL-3.0, so it stays a **separate, pinned
   component with its own licence notice** (ADR-0061 decision 3), not linked into our Apache-2.0 core.
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
- A dependency on Unsloth's decision models and the licences of their checkpoints, to be read before anything ships.
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

1. The licences of Laya and Clef; the commercial-use rule can end this ADR for one or both.
2. Whether Laya trains on the Mac (the trainer has an MLX path for the LLM layout; Laya's is unknown) and how fast.
3. How a sorter is served inside our engine without Studio: Laya through its own runtime (Studio vendors laya 0.3.5),
   a GGUF through our llama-server, or an MLX form; the Decision API's request shape (`noul`, `choice`, `score`) is
   kept as our action's schema so any of them can serve it.
4. Whether `score` questions need examples per level (they do for quality); the screen asks for at least five per level.
5. Image sorting (a vision LLM with a decision head): later.

## Not in v1

Clef and the LLM decision heads on the Mac; sorting images or audio; continual learning from corrections (a "that was
wrong" button feeding a retrain is the natural next step and is named in the plan, stage T5b); sharing sorters.

## Licence read (2026-10-18)

Hugging Face lists both **`convaiinnovations/laya`** (421M parameters) and **`Cloudflare/clef-flash`** (9.4B, built on
Qwen3.5-9B) as **Apache-2.0**, and Laya also carries a `commercial-use` tag. That clears open question 1 in
principle. Not yet read: the licence files and model cards themselves, and the licences of the training data the
authors used; T0 reads them before anything ships. Clef sharing Qwen3.5-9B's backbone fits ADR-0078.
