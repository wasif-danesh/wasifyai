# Coding agent, stage C6 with X3: Scheduled, and plugins

Written 2026-11-15 on the owner's Mac (M5 Pro, macOS 27.0). The stage is piece 9 of
`docs/v2-coding-agent-start-plan.md`, section 9, built after X2 by the owner's order ("Do X2 next, then C6 & X3,
then the browser tab, lastly v1 gate") and stacked on the X2 branch. What is built is described in
`docs/desktop/coding.md`; the decisions are ADR-0105 and ADR-0104 with their amendments of 2026-11-15.

## The gates

Section 9's gate for C6: a nightly run on a real project for a week, no missed or doubled run, no change outside
its copy. Section 7's gate for X3: a plugin with a hook is refused until approved; a schedule made from a
template runs.

**A week was not waited for.** The week's gate is measured in two compressed forms, and both are said here for
what they are: seven due times on a pretended clock, and seven due times five minutes apart on the real clock
(five minutes is the shortest a rule allows). The rules for nights, weekdays, months and the two clock-change
days are tested in `schedules.py`'s own tests on a pretended clock.

| Gate | Result | How it was measured |
|---|---|---|
| Seven due times in a row: none missed, none doubled (pretended clock) | **Passed.** Seven times five minutes apart, each a run on a copy: seven runs, seven different due times, five copies kept | `test_only_the_newest_copies_of_a_schedule_are_kept` (`products/wasifyai-code/tests/test_code_scheduled.py`), with the timer tests of ADR-0105's gate, which were already there |
| The same on the real clock, the real engine in its sandbox, a scripted model | **Passed.** Seven runs at 18:42:52, 18:47:52 ... 19:12:52 UTC: each "done" and "passed", each exactly 300 s after the one before, each started within 0.01 s of its time (ADR-0105's gate asks for two seconds). The project was byte for byte what it was, and five copies were kept. 35 min 6 s in all | `CODING_WEEK=1 ... pytest test_coding_session_real.py -k week_of_nights` (35 minutes; not part of `make test-coding`) |
| No change outside its copy | **Passed** in every form: after each run the project is read back from disk and is byte for byte what it was; the copy is inside `<app data>/coding/copies/` | The tests above, the real run below, and the walk |
| One run on the real engine: the copy, a refusal, the check, applying | **Passed.** The run deleted nothing (`rm -rf old` was refused: "1 step was refused: nobody was there to ask"), fixed the bug in its copy, the project's check passed in the copy, and the project changed only on "Apply": one file | `test_a_scheduled_run_works_alone_on_a_copy_and_the_project_is_touched_only_by_apply` |
| A schedule made from a template runs (real model) | **Passed.** "Check it every night" was chosen from the five templates, saved ("Every day at 02:00, Australia/Sydney") and run with "Run now" on the local Qwen 27B: 44 s, "Passed", "1 file changed, waiting for you". The project's three files were read back from disk unchanged. The changes dialog named `prices.py`; after "Apply to the project" the project's file held the fix, and the check file was untouched | `ui-audit.sh light code-scheduled`, steps 2 to 4 |
| A plugin with a hook is refused until approved | **Passed** on the real engine: added, it is off and cannot be switched on (`needs_approval`); a turn runs and no hook does. Approved and switched on, its hooks run: one wrote its line into the project, one read the plugin's own file through `PLUGIN_ROOT`. A hook's write outside the project failed (the sandbox), and a hook that sleeps four seconds was stopped before it wrote (the one-second rule) | `test_a_plugins_hook_runs_only_after_approval_inside_the_sandbox_and_for_a_second` |
| The same in the window, with a real model | **Passed.** A plugin with a hook was added: its row had "Look and switch on" and no switch. A turn ran (26 s) and the hook's file was not there. After "Approve what it brings" and the switch, the next turn (24 s) left `work-log.txt` with the hook's line | The walk, step 6 |
| `make test-coding` | **Passed: 54** (30 hostile tests, 24 of the sessions; 2 are new). The 35-minute run above is the one skipped there | The real server in its sandbox, a scripted model |
| `make test`, `make lint` | **Passed** on the final tree: ruff, the format check, pyright (0 errors), the design check, Biome and the TypeScript check; 3,767 Python tests passed and 498 skipped; 1,311 TypeScript tests (178 client, 220 web, 108 desktop, 805 screens). In the first full run one test failed, the assistant's help list being older than the help files; it was regenerated and that test file passed | The full chains, run while no coding engine was running |

**No paid run was made in this stage.** About 3.75 of the 25 dollars the owner allowed are used, all in stage C3.

## What is built

| Part | Where |
|---|---|
| What a run does: the checkpoint, the copy, the unattended session, the result; the schedules and their runs for the screen; applying and letting go | `products/wasifyai-code/wasifyai_code/scheduled.py` |
| A checkpoint written out as a folder | `checkpoints.py` (`CheckpointStore.copy_to`) |
| A turn with nobody to ask | `runtime.py` (`send(unattended=True)`, `_confirm`), `loop.py` (`Hooks.answers_unattended`) |
| The copy as a workspace of its own; a run's copy, its changes, what became of them | `store.py` (`workspaces.copy_of`, new columns of `schedule_runs` and `schedules`) |
| The timer started with the desktop engine | `services/api/src/wasifyai_api/assemble.py` |
| Our templates | `wasifyai_code/own/templates.json` |
| A plugin read, approved, and its hooks given to a session | `extensions.py` (`read_plugin`, `read_hooks`, `hooks_for_engine`), `store.py` (`extensions.approved_at`), `place.py` (`SessionSpec.hooks`), `client.py` (`hook_config`) |
| Routes and actions | `routes.py`; `actions.py` (`code.schedule.list`, `add`, `change`, `run`), `docs/help/` |
| The Scheduled screen and the plugin's approval card | `packages/ui/src/code/Scheduled.tsx`, `Extensions.tsx`; `apps/desktop/src/pages/Code.tsx`, `menu.ts`, `router.ts` |
| A schedule in the Library and in search | `index.py`; "Coding schedule" in `packages/ui/src/creations/`, `packages/client/src/creations.ts`; a row in `services/api/evals/search/corpus.yaml` |
| The walk of this stage | `apps/desktop/scripts/ui-audit-pictures.mjs`, scenario `code-scheduled` |

## Found on the way

1. **"Work on its own" does not ask about a delete or an install, so a run in that mode refused nothing but a
   picture.** The first real run deleted a folder in its copy without a word. The approved mockup shows a
   refused `rm -rf` in a run's history, and ADR-0105 says whatever would ask is refused. A run's steps are
   now judged as a chat in "Ask me" judges them (ADR-0105, amendment, point 2).
2. **A schedule with no model named went to the gateway's first choice**, Claude Sonnet 5.5, and failed at
   once on a computer with no key saved ("No key is saved for Claude Sonnet 5.5"). The walk found it. A
   schedule now takes the model of its project's newest session.
3. **An "every so many minutes" rule needs the moment it counts from**, and neither the screen nor the action
   gave one. The engine now counts from when the schedule is saved.
4. **Every one of the catalogue's 27 automation templates needs an integration or a webhook** (GitHub, Slack,
   Jira and others). None can run in the sandbox as it is. The templates offered are five of our own.
5. **The engine takes hooks with the conversation and runs them itself**, inside its sandbox, with a time
   limit per hook that it enforces. Nothing of ours runs a hook.
6. **A workspace inside the coding engine's own folder needs no restart of the server**: the sandbox already
   lets the server write there. A run's copy therefore never cuts off a chat in the middle of its turn.

## Decided while building, for the owner to see

1. **A run is stricter than "Work on its own"** (found 1). To let a schedule delete or install, allow that
   kind for the project ("What this project may do").
2. **Five templates of ours**, in one file, the owner's to change: Check it every night; Keep the README true;
   Notes on what is unfinished; Add a missing test; A monthly tidy.
3. **Approving a plugin is for a person at the window only.** There is no action for it.
4. **A plugin's tool connections are listed and not connected.**
5. **Deleting a schedule, and applying or letting go of a run's changes, are on the screen only.**
6. **Starting at login and staying in the menu bar are moved to the Browser tab's piece.** Both are work in the
   Tauri shell that can only be judged in the real window. The Scheduled screen has no switch for them yet.
7. **The window's item Code › Scheduled is shown now.**

## Not measured, not built

- **A real week.** See the gates.
- **The real Tauri window was not opened.** The walk drives the real window's page in a browser.
- **Claude Sonnet 5.5.** The local model alone was run.
- **A missed time caught up after the app was closed**, on the real app. The timer's tests cover it on a
  pretended clock; the app was not closed and opened over a due time.
- **A run shown in the tray's "Running now"**: not looked at.
- **A plugin from the catalogue.** The plugins in the tests and the walk were written for them.
- A diff of each file before a run's changes are applied; a schedule moved to another project; waking the
  computer; a plugin's commands, agents and tool connections; the web.

## For the next stage (the Browser tab)

- The Tauri shell is opened there anyway: starting at login (a Tauri plugin, a new dependency), the menu bar
  item, and the window staying alive when closed belong with it, with the switch the mockup shows on the
  Scheduled screen.
- The Scheduled screen and the plugin card should be looked at in the real window in the same sitting.
