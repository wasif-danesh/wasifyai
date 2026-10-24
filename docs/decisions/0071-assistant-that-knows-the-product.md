# ADR-0071: An assistant that knows the product, guides, and runs it when the person clicks

- **Status:** Accepted (2026-10-18, by the owner), together with the new dependencies it names.
- **Date:** 2026-10-18
- **Depends on:** ADR-0068 (action catalogue, executor, approvals), ADR-0057 (the assistant; `interrupt` for costly
  actions was decided and not yet used), ADR-0056 (one slot; the local chat model), ADR-0047 (safeguards),
  ADR-0066 (voice product; models that may not be installed), ADR-0041 (search).
- **Related:** ADR-0070 (remote tools join the same loop).
- **Plan:** `docs/phase4-agent-plan.md`, stages A1 to A3.

## Context

The owner's example: a person asks "How can I do a text to speech?" The assistant should give a step-by-step
guide, and better, ask for the text, then offer a button that makes the speech file when clicked. The owner's
word was "trained on our product functionalities".

What the assistant is today (read 2026-10-18): one graph with a tool loop (`MAX_ROUNDS = 4`), a system prompt of
four sentences, four hand-written tools (`generate_image`, `make_music`, `search_creations`, `search_notebooks`),
no knowledge of the other features, and tools that **run at once**: asking for a picture makes the picture. The
recommended local model (Qwen3 4B) chose the right tool in 11 of 11 evaluation cases, with four tools.

What makes "train" the wrong word, and what makes it easy anyway:

- A model that is **fine-tuned** on our features would be wrong the day a screen changes, would need a training
  run for every release and for every model the person might pick (the chat model is the person's choice,
  ADR-0063/0064), and still invents menu names. Our features change weekly.
- The knowledge is **small and structured**: about 40 actions (ADR-0068), each with a screen, a menu path,
  requirements, limits and a known set of failures. That fits retrieval and a short fixed prompt, not weights.
- The truth about **this computer** matters as much as the manual: whether a speech model is installed, whether
  the runtime is set up, how much disk is free. A fine-tune cannot know that; a tool can.
- Small local models degrade as tools multiply, so "one tool per feature" will not scale to 40 actions plus
  remote tools (ADR-0070).

## Decision

1. **Knowledge is a help corpus plus live state, not weights.** Every action has a help file
   (`docs/help/<action id>.md`, ADR-0068 decision 1): what it is for, the steps in the app using the **exact
   labels of the menu and screens**, the fields and what they mean, limits (length, languages, sizes), what it
   needs installed, three examples, and the common problems with the fix. Files carry front matter (the action
   id, screen id, synonyms and the words people use: "read aloud", "voice over", "tts"). A test fails if a
   menu label in a help file does not exist in the shipped menu, or an action has no help file. The corpus ships
   inside the app and is **versioned with it**; v1 is English only (project rule), written so another language is
   a translation.
2. **Retrieval is local and small.** The corpus (about 100 passages) is searched by words, synonyms and the
   engine's embedder. The desktop's built-in embedder is a hashing one (`local_embedder.py`: it matches shared
   words and word pieces, not meaning), so v1 relies on the front-matter synonyms and an exact action-id and
   label index, and uses real embeddings when a search model is installed (the notebooks' bge-small, ADR-0065).
   Which one is good enough is **measured** (decision 8), not assumed.
3. **The assistant has a fixed set of meta-tools, however many actions exist.** Replacing the four hand-written
   tools (which become actions, ADR-0068):

   | Tool | Does |
   |---|---|
   | `how_to(question)` | the best three help passages and the action ids they belong to |
   | `app_status()` | what this computer can do right now: for each action `ready`, `needs_setup` (with the step) or `unavailable`; free disk; models ready; the open screen |
   | `propose_action(action_id, params)` | validates `params` against the action's schema and the product's own checks and **returns the problems in words** for the model to fix, or shows an **action card** (decision 4) |
   | `open_screen(screen_id)` | a button that opens a screen of the window |
   | `search_creations`, `search_notebooks` | as today (`read`, `private`) |
   | `external_tools`, `call_external` | ADR-0070, when connections exist |

   The tool list is the same size whether the catalogue has 12 actions or 80, which keeps small models reliable.
   `propose_action` takes the action id as a string from the catalogue listing in the system prompt (a compact
   map of ids and one-line summaries, about 600 tokens, generated from the catalogue and never typed by hand).
4. **Nothing runs until the person clicks, unless they said it may.** `propose_action` ends the model's turn with
   an **`interrupt`** (`kind: confirm_action`, the use ADR-0057 decision 4 reserved) whose payload is the card:
   the action's title; its fields **filled in from what the person said and editable** (a text box with the
   sentence to speak, a voice and a model picker, a length slider; drawn from the schema); an estimate (seconds
   on this computer, size of a download if one is needed); badges (`leaves this computer`, `uses a downloaded
   model`, `needs your word`); and, if something is missing, the step that fixes it as a button ("Get a speech
   model"). The window renders it from the schema (one renderer for every action; field types: text, long text,
   number with limits, choice, model, voice, saved voice, creation, file). **Run** resumes the run
   (`POST /runs/{id}/resume`), the executor runs the action (ADR-0068 decision 2), progress shows on the card
   (the existing `job_progress`), and the card becomes the result: a player or a picture, **Open**, **Save as...**,
   **Make another**. **Cancel** and **Edit** are always there. The person's click is the approval; the floor of
   ADR-0068 decision 4 holds (consent statements are shown on the card and need their own tick).
5. **Auto-run is a setting, not a default.** Per conversation: "ask before making things" (default), "ask only
   for things that take over a minute or leave this computer", "don't ask" (not offered for `destroy` or
   `needs_consent`). The setting is shown on the card ("Don't ask again in this chat"). The taint rule of
   ADR-0070 decision 5 overrides it after external content.
6. **Guides are grounded, and honest about this computer.** The system prompt tells the model: for "how do I"
   questions call `how_to` and `app_status`, answer from the passages only, name the screens and fields exactly
   as written, say which step this computer is missing, and offer the card ("Want me to do it? Give me the text and
   I'll make it."). It must not describe features that are not in the passages. Answers to feature questions
   cite the help file in a small link ("Text to speech guide") that opens the same text in the app.
7. **Asking for what is missing.** The model collects required fields by conversation, not by form, when a card
   would be mostly empty: for text to speech, "What should it say?" The schema's `required` list and `examples`
   drive this; the card then shows everything for a last edit. Free-form requests ("read this in a calm voice")
   map to fields through the model; the server-side checks (`check_speak` and the others) are the authority and
   their sentences are returned to the model when something is out of range.
8. **How we know it works: an evaluation, run with every change to the catalogue, the help files or the
   prompt.** `products/wasifyai-assistant/evals/` gains: **guide cases** (60 or more questions across all
   actions, with the action it must name, words the steps must contain, and facts it must not invent), **action
   cases** (the right `action_id`, parameters extracted, missing parameters asked for, refusal when the request is
   outside the catalogue), **status cases** (the model is not installed: the answer must say which step, not
   pretend), **safety cases** (an instruction hidden in a search result must not make it run an action), and
   **tool-count cases** (the same cases with 5 and with 40 remote tools present). Scored with the existing runner
   against the person's chosen model tiers: Qwen3 4B (the recommended local model), a larger local model and one
   hosted model. Acceptance for v1 is written in the plan (stage A3) before the work starts: no regression on the
   existing 11, and at least 90 percent on guide and action cases with Qwen3 4B, or the card path is offered with
   a "this model may be unreliable" note. English only.
9. **Fine-tuning is not part of v1 and has a gate.** If the evaluation shows a tier of model that fails on tool
   calling in ways prompts and retrieval cannot fix, a small supervised fine-tune (synthetic Q&A written from the
   catalogue, tested on held-out cases) becomes its own ADR. The corpus and cases built here are exactly its
   training and test data, so nothing is wasted.
10. **Where it runs, and the model rule.** The same graph on the desktop and (later) the web. The chat model is the
    person's choice (ADR-0057); an action that needs the one slot (ADR-0056) switches it as today and the card says
    so ("This will pause the chat model for about 20 seconds").
11. **Privacy.** `how_to` and `app_status` read the app's own files and the engine's state; nothing leaves. What
    the assistant reads of the person's library and notebooks is `private` and is the existing search, unchanged.
12. **Contract.** `interrupt` gains the `kind` `confirm_action` and a documented payload (a new `kind` value, not
    a new event type, so no change to the event list in `docs/contracts/sse-events.md` beyond the payload table);
    the resume value is `{approved, params}`. The generated TypeScript types and the shared chat module in
    `packages/ui` are updated together.

## Consequences

- The assistant becomes the product's front door: the answer to "how do I" is a guide and a working button.
- The help files are a new kind of artifact with owners: when a feature changes, its help file changes in the
  same commit (a rule for CLAUDE.md on acceptance, like ADR-0041's).
- The evaluation grows to a few hundred cases and takes minutes on a laptop per model; it is run on demand and in
  the release checklist, not on every commit.
- The system prompt grows (map, rules), so context use rises by about 1,000 tokens; with `MAX_ROUNDS = 4` and
  40 history messages this must still fit 8,192 tokens on the local model (measured in stage A3).
- The window gets an action card renderer, which is also the base of "do it from the library" buttons elsewhere.

## Alternatives considered

- **Fine-tune a model on the product.** Rejected for v1, with a gate (decision 9): stale on release, per model,
  and blind to this computer.
- **A static FAQ or an in-app tour.** Good and cheap, and still wanted for first run (the product tour), but it
  cannot answer free-form questions or do the work.
- **One model tool per action.** Rejected: 40 tools break small models; the meta-tools keep it constant.
- **Let the assistant run actions at once, as `generate_image` does today.** Rejected for anything that takes
  time, leaves the computer or needs a word: the card is the approval, and it also fixes the common failure of
  a wrong parameter made without the person seeing it.
- **Put the knowledge in the system prompt entirely.** A 100-passage manual does not fit the local model's context;
  retrieval plus the 600-token map does.

## Open questions

1. Retrieval quality of the hash embedder against synonyms (decision 2): measured in the first evaluation, with
   a lexical-only baseline; if poor, ship precomputed bge-small embeddings and embed the question with it.
2. Whether `propose_action` should also accept a short plan of several actions ("make the speech, then a lip
   sync"). A chain is the model calling it twice; a combined card is a later design.
3. Card field renderers for the voice screens' richer options (model-specific options come from the model's
   descriptor; the card may show only the common ones and link "More options" to the screen).
4. Keyboard and screen-reader behaviour of the card (accessible by default: the card is a form in the transcript,
   focus moves to its first field on arrival).

## Not in this version

Other languages (the help corpus is English; the model may answer in the person's language from it); voice input
and spoken answers; a visual walkthrough that highlights parts of the screen; fine-tuning; actions that change
settings; teaching the assistant by the person ("remember this"); the web deployment's assistant (it uses the same
graph later).

## Interim, built 2026-10-24: the screens in the prompt

Until A2 exists the assistant told people it could not make video, speech or 3D, because it knew only its own
tools. It now gets one sentence listing the side menu's screens and what each does ("Video › Create: make a video"),
and is told to point people there and not to claim it made things itself (it still makes pictures and music with
its tools). The list is **generated**, not typed: `wasifyai_api.assistant_features` joins the action catalogue
(`ui` and `title` of every action offered to the assistant) with `packages/ui/src/shell/menu.ts` into
`products/wasifyai-assistant/wasifyai_assistant/features.json`; a test fails when it is stale
(`uv run python -m wasifyai_api.assistant_features --write`). At run time only the screens whose actions this engine
serves are listed. About 360 tokens. A2's `how_to` and `app_status` replace it with steps and live state; the
tool-choice eval now sends this same prompt.
