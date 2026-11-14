# Coding agent, stage C2: a session that changes files, with undo

Written 2026-11-14 on the owner's Mac (M5 Pro, macOS 27.0). The stage is piece 5 of
`docs/v2-coding-agent-start-plan.md`, section 9. What is built is described in `docs/desktop/coding.md`; the
decisions are the amendments of 2026-11-14 to ADR-0101, ADR-0102 and ADR-0103.

## The owner's answers behind it (2026-11-14)

| Asked | Answer |
|---|---|
| The three open points of undo (ADR-0103, decision 13) | "Yes to the undo questions": undo restores the person's own git (`HEAD`, the index); ignored files are left out, and the app says so |
| May the approval card reuse the stream's `interrupt` kind, and `code_state` gain `changed`? | "Reuse interrupt" |
| May the coding API gain `mode`, a turn's changes, undo, the answer to a card and the project's allowances? | "Yes, add them" |
| May "Ask me" ask before changing a file Undo cannot put back? | "Yes, add that kind" |
| The gate's model | "Sonnet 5.5 too, limit $8" (the local Qwen 27B first) |

## The gate

The gate of piece 5 is: every change in the evaluation can be undone exactly, and the loop's unit tests pass.
It was measured with `products/wasifyai-code/evals/run_eval.py --data` on the real coding engine in its
sandbox (1.62.0, the throwaway data folder `~/Library/Application Support/ai.wasifyai.coding-c1b`), each task
in a session that may change files, opened the way the product opens a project. Before the agent's turn the
task's folder is kept; after the hidden check it is undone and compared, then brought back and compared: every
file's bytes and permissions, every link, every folder, no file more and none less.

| Gate | Result | How it was measured |
|---|---|---|
| Every change in the evaluation is undone exactly, Claude Sonnet 5.5 | **Passed: 36 of 36 undone exactly, 36 of 36 brought back exactly** (31 tasks changed files; the 4 questions and one miss changed none) | `run_eval.py --data ... --model claude-sonnet-5-5 --app-keys --limit-usd 8` |
| The same on the local Qwen 27B (Ollama) | **Passed: 36 of 36 and 36 of 36** (32 tasks changed files), in both of two full runs | The same with `--model qwen-27b-ollama` |
| The loop's unit tests | **Passed: 29** (`tests/test_loop.py`), with the 48 of `test_checks.py` and the 16 of `test_checkpoints.py` | `make test` |
| Tasks solved without a terminal, Claude Sonnet 5.5 | **35 of 36** in 11 minutes, median 16.5 s a task. The one miss (`feat-intervals`) was a fault of the runner, not of the model or the product (below); after the fix that task passes | The same run; then the one task again |
| Tasks solved without a terminal, local Qwen 27B | **31 of 36** in 38 minutes, median 44 s a task (bug 7 of 8, feature 7 of 8, hard 4 of 6, tests 1 of 2, the rest all). Missed: `bug-duration`, `feat-roman`, `tests-write`, `hard-kv-store`, `hard-cli`. The first full run, before the runner was fixed, had 27 of 36 | The same run |
| A real session through the window: a change, the card (yes, no, "Allow for this project", Stop), the Changes tab, undo and "Bring it back" | **Passed**, each checked on the project's files on disk. A change with no question: 26 to 33 s. The card: about 5 s after the request. After a no the turn ended in 8 to 13 s. Stop while the card waited: 0.34 s. `home.html` was byte for byte what it was after undo; the ignored `.env` was never touched by undo; the project got no `.git` | `ui-audit.sh light code-edit`, local Qwen 27B, four full runs |
| `make test-coding` | **43 passed** (30 hostile tests of C1a, 9 of C1b, 4 new: a session that edits waits and a yes lets it run, a no, Stop while a change waits, nothing outside the project and the checkpoint store out of reach) | The real server in its sandbox, a scripted model |
| `make test`, `make lint` | **Passed** on the final tree: ruff, the format check, pyright (0 errors), Biome and the TypeScript check; 3,666 Python tests passed and 486 skipped; 1,275 TypeScript tests (178 client, 220 web, 108 desktop, 769 screens) | The full chains, run while no coding engine was running |

**Counted cost on Claude Sonnet 5.5: $1.67** of the $8 the owner allowed ($1.64 for the 36 tasks, $0.03 for
the one task again). No other paid run was made.

**About the one miss.** The model asked for an edit and a file search in one step. The coding engine waits once
for both, and the runner said no because one of the two was not a change. The agent then said that its edit
had been refused, and no file changed. The product's own rule was right all along (`rules.decide` looks for a
kind among the steps and lets the rest through). The runner now lets through any steps among which one is a
change. Both models were run again after the fix: the one task on Sonnet 5.5, all 36 on the local model.

**Why fewer tasks are solved than in stage C1b.** There the evaluation ran with the engine's standard tools,
the terminal among them, and the local model solved 34 of 36. A session of stage C2 can read and edit and
cannot run anything, so the agent cannot try its own change. That is the honest number for this stage; the
terminal comes back, inside the sandbox, in stage C3.

## What is built

| Part | Where |
|---|---|
| The modes Plan, Ask me, Work on its own; the engine's default is Plan, the Code screen starts a project in "Ask me" | `store.py` (`MODES`), `runtime.py` (`set_mode`), `routes.py` (`PATCH /sessions/{id}`) |
| A session that edits: find, search and the file editor; no terminal | `client.py` (`EDIT_TOOLS`, `EDIT_NOTE`) |
| Every change waits in the coding engine before it runs | `services/coding-engine/wasify_rules.py`, loaded by `coding_server.py` with `--import-modules`; the policy "ask when high" on the conversation |
| Which kind a waiting step is, and whether a person is asked | `rules.py`: `classify`, `decide`; kinds `not_undoable`, `delete`, `install` |
| The approval card, its three answers, "Allow for this project", taking it back | `runtime.py` (`_confirm`, `answer`, `project`, `allow`), the stream's `interrupt`, `packages/ui/src/code/Asking.tsx` |
| A checkpoint before and after every turn that may change files, outside the project | `runtime.py` (`_before`, `_after`), `checkpoints.py` |
| A turn's changes, one file before and after, undo and "Bring it back" | `runtime.py` (`changes`, `change`, `undo`, `redo`), `packages/ui/src/code/Changes.tsx` |
| The action `code.session.undo` | `actions.py`, `docs/help/code.session.undo.md` |
| "Carry out this plan": the session leaves Plan, and the new conversation is given the plan | `Code.tsx`, `runtime.py` (`_request`) |
| The evaluation undoes every task and brings it back, and has a cost limit for the whole run | `evals/run_eval.py` |

## Found on the way

Each was found by a run on the real, pinned Agent Server (1.62.0), not by reading.

1. **The file editor cannot create a file in a folder that does not exist** ("No such file or directory"), and
   without a terminal the agent cannot make the folder. The place now makes the missing folders, inside the
   session's own project only, at the moment a "create" is let through (`client.py`, `_make_folders`).
2. **The Agent Server runs `git init` in a workspace that is not a git repository**, at the start of a
   conversation, so that its own Changes endpoint works. In stage C1b the sandbox refused it by accident (the
   folder was read-only). With a folder it may write, a person's project became a repository because it was
   opened. The sandbox profile now closes `<project>/.git` to writing when the project has none
   (`engine.sb.template`, `{{NO_WRITE}}`). There is no setting for it in the server.
3. **An interrupt does nothing to a conversation that waits for a yes or no**: it is not running, and the
   server's pause only acts on a running or resting conversation. Stop then never ended the turn. Stop now
   refuses what waits (nothing of it runs), which brings the conversation to rest, and then interrupts.
4. **The server fills a missing reason with the tool's name and what it was given** (`file_editor: {"command":
   ...}`). The first walk showed that on the card as "It says". It is left out; the card shows a reason only
   when the agent gave one.
5. **"No file was changed" was said after a turn that changed only `.env`**, because an ignored file is not
   among a turn's changes. The chat now says "This turn changed only files Undo cannot put back".
6. **"Bring it back" in the wrong order would have left the rows wrong**: with two turns undone, bringing the
   older-undone one back first restores files that include a turn still marked undone. What comes back is
   always the turn undone last.
7. **The evaluation refused every change**: it answered no to every question, which was right when only a
   command could ask. It now lets a change to a file through and refuses any other question.
8. **A no said too strongly made the agent refuse later requests by itself.** The first message to the agent
   after a no ended "Do not try it again". In a real walk the local model then declined the person's next two
   requests for the same file ("the repeated requests look like a probe"). The message now says that the no
   was for this one step, and that a later request is tried as usual; in the next walk the model did the
   change when it was asked again.
9. **A model may decline by itself**, with no question of ours: asked for two changes in one message, the local
   model once changed the first file and would not touch `.env` ("I need to pause and flag a concern"). No card
   came, rightly. The walk now asks for one change in each message.

## Decided while building, for the owner to see

1. **The session's turn is still run by `runtime.py`, not by `Loop.run_turn`.** The loop's own tests pass
   (`tests/test_loop.py`, 29), and nothing calls it: no check can run until the agent, and we, can run a
   command inside the sandbox. Handing the turn to the loop is the first step of stage C3. Until then a turn
   that changed files says "Not checked".
2. **The engine's default mode stays Plan.** A session started through the assistant's action only reads
   unless `mode` is given. The Code screen starts a project in "Ask me", as the mockups say.
3. **Changing between Plan and a mode that edits begins a new conversation** in the coding engine, because a
   conversation's tools are fixed when it starts. The agent is given the last request and answer again, and the
   turn says so. Between "Ask me" and "Work on its own" nothing restarts.
4. **Steps that wait together get one answer.** The engine takes one yes or no for everything that waits. The
   card says how many changes wait.
5. **A yes is for once.** Only "Allow for this project" stops the question.

## Not measured, not built

- **The real Tauri window was not opened.** The walk drives the real window's page in a browser with the real
  engine behind it; the folder picker is answered by the walk's stand-in.
- **A large project.** A checkpoint took 3 s for this repository in the C0 spike. A project with a large
  folder it does not ignore (a `node_modules` with no `.gitignore`) was not tried, and nothing limits it.
- **Two sessions changing one project at the same time.** Each takes its own checkpoints of the whole project,
  so undoing a turn of one also puts back what the other changed since. Not prevented, not tried.
- **Dropping old checkpoints.** Nothing is dropped.
- **The approval card on other screens** (mockup `ask-elsewhere`), the dot for changed files in the Files tab,
  a project's "More" menu, "Start in a new, empty folder", and the Terminal, Browser and Preview tabs.
- **The web.** Coding is desktop only.
- **A session after the app was closed and opened again** still begins a new conversation (stage C1b's note).

## For the next stage (C3)

- Give the agent the terminal, inside the same sandbox; the kinds `delete` and `install` then come up, and
  `rules.classify` needs their patterns. The list that is asked in every mode arrives with them.
- `Sessions._turn` hands the turn to `Loop.run_turn`; the check runs in the sandbox; "Not checked" becomes one
  of the four words.
- With a terminal the agent can run `git init` itself; the `.git` rule of the profile must then tell the
  agent's own wish from the server's habit, or stay as it is and be said on the screen.
- `CLAUDE.md` lives in the main checkout only. Its row "Working on the coding agent" should say that stages
  C1b and C2 are built and merged or on branch `coding-c2`, name `docs/spikes/coding-c1b.md` and
  `docs/spikes/coding-c2.md`, `coding_gateway.py`, `coding_models.yaml`, `services/coding-engine/wasify_rules.py`,
  `wasifyai_code/rules.py`, and the tests `test_coding_gateway.py`, `test_coding_sessions.py`,
  `products/wasifyai-code/tests/test_code_edits.py` and `tests/integration/test_coding_session_real.py`; and
  that C3 (commands, and the loop switched on) is next.
