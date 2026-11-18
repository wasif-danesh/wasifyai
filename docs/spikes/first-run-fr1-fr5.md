# First run and group cards: stages FR1 to FR5 (2026-11-18)

What was built for ADR-0109, how it was checked, and what was not. FR0's measurements are in `first-run-fr0.md`;
how it works is in `docs/desktop/first-run.md`.

## FR1: what a group needs (engine)

- `GET /desktop/setup/groups`, in `setup_groups.py`, answers for all 15 groups from the real catalogues and
  components.
- The sizes match FR0's "Checked in code" table:

  | Group | Size |
  |---|---|
  | Voice | 8.98 GB |
  | Music | 6.29 GB |
  | Lip sync | 6.33 GB |
  | 3D | 8.98 GB |
  | Meetings | 3.01 GB |
  | Notebook | 1.53 GB |
  | Code | 0.43 GB |
  | Images | 20.4 GB |
  | Video | 20.4 GB |

- 14 tests cover:
  - the menu matching the groups;
  - every need resolving;
  - the parts of each item;
  - 8, 16, 24 and 64 GB Macs;
  - set-up parts not counted;
  - Creative Studio and Meetings taking in other groups;
  - unsupported parts;
  - Indian-language speech by language.
- **Different from the plan.** Model needs that the actions do not name are listed in `ITEM_ALSO` in the route's
  module, not added to the actions' `requires`. There is no test that fails when an action running a local model
  names no model.

## FR2: running a group's setup

- **Different from the plan.** There is no engine job, no `POST` route and no `setup.group` action.
  - The window runs one step per part (`setup-groups.ts`): components through `installStep`, models through
    `modelStep` (the engine's resumable download jobs), and chat through the chat choice.
  - Small parts go first. Stop aborts the steps, and pressing again carries on.
  - This follows ADR-0086 decision 9 and needs no new public API.
  - The cost: a setup does not carry on by itself after the window closes, and the chat cannot offer it.
- 8 tests in `setup-groups.test.ts`.

## FR3: the card

- `GroupSetupCard` and its words in `packages/ui/src/setup/`, with 11 tests and five states on `/design`.

## FR4: the gate

- **The walk.** `ui-audit.sh light setup-groups` was run on a fresh data folder on this Mac (64 GB, Ollama
  running). Every one of the 12 screens it opens showed its group's card with the real parts and sizes. Pictures are
  `docs/ui-audit/desktop/setup-*.png`.
- **One group set up for real.** Motion graphics' engine was set up through its card:
  - it downloaded 318 MB, which is 568 MB on disk;
  - the card went away and the screen opened. The `setup-run-*` pictures now show the Notebook run below, which
    replaced them.
- **Voice set up for real** through its card, with the owner's yes, on a fresh data folder. One press of "Set up
  Voice · 9.0 GB" took 11 minutes (21:39 to 21:51) and left 8.4 GB of models. Afterwards all seven Voice items
  opened their screens with no card, and the models in use showed ready: Text to speech (Kokoro), Speech to text,
  Voices, Change a voice, Edit speech (dots.tts Edit), Dub a recording (Qwen3-TTS 0.6B Base) and Audiobook. The
  chat line ("already on this computer") chose the Ollama model in the same press.
- **Notebook set up for real** the same way. "Set up Notebook · 1.5 GB" left the document reader (1.5 GB in
  `components`) and the search model (64 MB). The whole walk, its 12 cards included, took under 3 minutes (21:57 to
  22:00). Afterwards View notebooks and Create opened their screens. The new notebook showed the full workspace,
  with no old setup card, and its chat model (the Ollama one) ready. Its pictures are the current
  `setup-run-*.png`; Voice's were replaced by them.
- **Two faults found by the walk and fixed:**
  - A chat model already on the computer showed as "0 bytes". It now says "already on this computer".
  - Every screen that read the groups opened its own `/desktop/events` stream. With the window's few connections
    to the engine used up, the first run's model list never came back. `onComponentStatus` now shares one stream
    across the window, with a test in `components.test.ts`.
- **Different from the plan.** The old in-screen cards are kept as a fallback behind the gate (see
  `docs/desktop/first-run.md`).

## FR5: the first run

- `ui-audit.sh light first-run` was run on a fresh data folder. The Welcome's button came after 1 s and said "Uses
  qwen3.8:27b-mlx already running here · no download". Pressing it chose the Ollama model (`PUT /desktop/language`),
  and "You’re ready", then the home, followed. Pictures are `first-run-welcome`, `first-run-ready` and
  `first-run-home`.
- **A fault fixed:** the first run hid itself the moment chat was ready, so "You’re ready" was never seen. It now
  stays until the person leaves it.
- **Not done:**
  - The download way and the key way were not walked.
  - The walk drives the window in a browser against the real engine, not in the Tauri window itself.
- **Worth a look:** with two Ollama models, the button picked the 27B one (it fits on 64 GB and is listed first),
  not the smaller gemma4.
