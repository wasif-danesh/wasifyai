# Coding agent, stage C3: commands, and the loop switched on

Written 2026-11-15 on the owner's Mac (M5 Pro, macOS 27.0). The stage is piece 6 of
`docs/v2-coding-agent-start-plan.md`, section 9. What is built is described in `docs/desktop/coding.md`; the
decisions are the amendments of 2026-11-15 to ADR-0101, ADR-0102 and ADR-0103.

## The owner's answers behind it (2026-11-15)

| Asked | Answer |
|---|---|
| May `xterm.js` and `portable-pty` be downloaded? | "Download them." Only `xterm.js` was needed (below) |
| Installs through a proxy that lets the sandbox reach the network for the first time | "I approve it, no need to ask." |
| A paid run for the gate | "You can use up to $25 for testing, no need to ask." |
| `git init` by the agent | "I want the agent to allow to create the files necessary for a project." |
| May the stream gain `code_check`, and `code_state` gain `round` and `needs_you`? | "Yes, add them" |
| May the coding API gain the check's routes, the terminal's routes and an action for the check? | "Yes, add them". The terminal runs in the Python engine, so `portable-pty` is not used |

## The gate

The guideline's gate for C3: bug-fix tasks pass with tests run by the agent, and the hostile test cannot write
outside. Section 6's gate for the loop has five points; each is a row below.

The evaluation is `products/wasifyai-code/evals/run_eval.py --data` on the real coding engine in its sandbox
(1.62.0, the throwaway data folder `~/Library/Application Support/ai.wasifyai.coding-c1b`): each of the 36
tasks in a new session that may change files and run commands, opened the way the product opens a project,
with a hidden check the agent never sees. The walk is `ui-audit.sh light code-check`: the real window's page
with the real engine and the local Qwen 27B behind it, on a throwaway project, every result read back from
disk.

| Gate | Result | How it was measured |
|---|---|---|
| Bug-fix tasks pass with tests run by the agent, Claude Sonnet 5.5 | **Passed: 8 of 8, the terminal used in all 8.** All tasks: **36 of 36** in each of two full runs, 11.7 minutes a run, median 15 s a task. The terminal was used in 34 of the 36 (not in two of the four questions) | `run_eval.py --data ... --model claude-sonnet-5-5 --app-keys --limit-usd 8`, twice |
| The same, local Qwen 27B (Ollama) | **Passed: 8 of 8 in two runs, the terminal used in 7 of the 8.** All tasks: **33 of 36** (everything outside the hard group 30 of 30; hard 3 of 6: `hard-kv-store`, `hard-bug-hunt`, `hard-cli` missed), median about 45 s a task. In stage C2, without a terminal, the same model had 31 | The same with `--model qwen-27b-ollama`: one run of 32 tasks, then the six hard tasks and the eight bug tasks again (below) |
| Every change still undone exactly | **Passed** in every run: Sonnet 36 of 36 undone and 36 of 36 brought back, twice; Qwen 32 of 32, 6 of 6 and 8 of 8 | The same runs |
| The hostile tests cannot write outside | **Passed: 48** (30 hostile tests of C1a, 18 of the sessions; 7 are new) on the real server in its sandbox. New in this stage: a command writes inside the project and is refused outside it, cannot read the person's home or the app's data, and reaches no network; the check, run in our own sandbox for the project, is refused a write outside; so is the person's terminal | `make test-coding` |
| The loop, point 1: the review's case passes from the app (an old bug, a task that adds a function, a check that covers both; one refusal, one fix, one pass, the check file untouched) | **Passed** from the window with the local model: round 1 failed 5 s after the request ("total of nothing must be 0"), went back, the agent fixed the old bug, round 2 passed; 12 s in all. `check.py` byte for byte what it was, and the check passes when run on disk afterwards. Also passed with a scripted agent on the real engine and on the pretended place | The walk, step 3; `test_the_reviews_case_...` in both test files |
| Point 2: a check of two minutes runs while the screen stays live and every other call answers within a second | **Passed:** a check of 123 s; 120 calls to five routes meanwhile, the slowest 62 ms; the Files tab opened and listed the project each time | The walk, step 4 |
| Point 3: Stop during a check ends it within one second and leaves no process behind | **Passed: 229 ms** from the click to "Not checked"; no `sleep` of the check left running | The walk, step 5; `test_stop_during_a_check_...` |
| Point 4: a question in a project whose check fails is answered, and no file changes | **Passed:** answered in 28 s, no check ran, the files byte for byte the same; the chat says "No file was changed. The last check still stands: check failed" | The walk, step 2; `test_a_question_in_a_project_whose_check_fails_...` |
| Point 5: a check that cannot pass ends after three rounds with "needs you" | **Passed with a pretended agent** (three failed rounds, then "needs you"; "Try 3 more rounds" starts a new count). **With the real model it ended after one round**, also as "needs you": the agent read the command, saw that it ends in `exit 1`, said so and changed nothing, and a failed check with nothing changed since ends the turn | `test_a_check_that_cannot_pass_...`; the walk, step 6 |
| The person's terminal is held by the same sandbox | **Passed:** `python3 -B check.py` ran and printed "all good"; listing the person's home folder, writing a file beside the project and `ps` were each refused; a package index answered through the proxy and `example.com` did not | The walk, step 7; `test_the_persons_terminal_is_held_by_the_same_sandbox` |
| A command that deletes is asked first; Undo brings the file back | **Passed:** the card came 2 s after the request with `rm notes.txt`; the file was there until the yes, gone after it, and back, byte for byte, after "Undo this turn" | The walk, step 8 |
| The agent may make a repository; opening a project makes none | **Passed:** no `.git` after eight turns in the project; `.git` there after "Run git init" | The walk, step 9; the real test of the same name |
| An install reaches a package index only when it was let through | **Passed:** the same request for a page of PyPI was refused before an install step and answered (200) after one; `example.com` was refused even then | `test_an_install_that_is_let_through_...` (the one real test that uses the network) |
| `make test`, `make lint` | **Passed** on the final tree: ruff, the format check, pyright (0 errors), the design check, Biome and the TypeScript check; 3,730 Python tests passed and 491 skipped; 1,289 TypeScript tests (178 client, 220 web, 108 desktop, 783 screens) | The full chains, run while no coding engine was running |

**Counted cost on Claude Sonnet 5.5: $1.87 for the second run of the 36 tasks.** The first run was not counted,
through a fault of the runner (below); it made the same 36 tasks and will have cost about the same, so about
$3.75 of the $25 the owner allowed was spent. No other paid run was made.

**How the local model's count was put together.** The first full run stopped after 32 tasks (31 passed), by a
fault of the runner and not of the product (below). The six hard tasks were then run again (3 passed), and the
eight bug tasks once more to record which tools were used (8 passed). So 33 of 36 is 30 from the first run and
3 from the second; `hard-expr` passed its hidden check in both, the first time only after the time limit.

## What is built

| Part | Where |
|---|---|
| The agent's terminal: a session in "Ask me" or "Work on its own" gets it beside the file editor; every command waits for our rules before it runs | `client.py` (`EDIT_TOOLS`, `WAIT_TOOLS`, `EDIT_NOTE`), `services/coding-engine/wasify_rules.py` |
| Which kind a command is: `delete`, `install`, or neither | `rules.py` (`command_kind`) |
| Installs through a proxy of our own, to package indexes only; the agent only after an install was let through | `services/api/src/wasifyai_api/coding_proxy.py`, `coding_install_hosts.txt`, `client.py` (`_installs`) |
| The Agent Server's own `git init` switched off; the agent may run it | `wasify_rules.py`; the profile's `.git` rule is gone |
| A sandbox of our own for each project, for the check and the person's terminal | `coding_server.py` (`sandbox_for`, `_environment`, `install_env`) |
| Every turn run by the loop, through hooks | `loop.py` (`Hooks`, `run_turn`), `runtime.py` (`_Hooks`, `_on_loop`, `_closing`) |
| The check: suggested from the project's files, set by the person, run after a turn, run by hand, its output read | `checks.py` (`suggest`), `runtime.py` (`check`, `set_check`, `check_now`, `check_output`, `try_again`), `routes.py` |
| On the stream: `code_check`, and `round`, `needs_you`, `check_why` on `code_state` | `packages/contracts/.../events.py`, `docs/contracts/sse-events.md` |
| The action `code.session.check` | `actions.py`, `docs/help/code.session.check.md` |
| The person's terminal: a shell on a pseudo-terminal inside the project's sandbox | `terminal.py`, `routes.py` |
| The screens: the check's word in the bar, the check cards, the check's dialog, the Terminal tab, the card's words for a command | `packages/ui/src/code/Checks.tsx`, `Terminal.tsx`, `xterm-css.ts`, `Code.tsx`, `Asking.tsx`, `thread.ts`, `use-code.ts` |
| The evaluation lets a command through like a change | `evals/run_eval.py` |
| The walk of this stage | `apps/desktop/scripts/ui-audit-pictures.mjs`, scenario `code-check` |

## Found on the way

Each was found by a run on the real, pinned Agent Server (1.62.0) or in the real window, not by reading.

1. **A terminal's far side reads as closed until something holds it open.** The shell opens its side of the
   pseudo-terminal a moment after it starts. Until then our side read "end of file", and the terminal was taken
   for ended before it began. The engine now keeps its own hold on that side for as long as the terminal lives.
2. **A shell with job control gives every job a process group of its own**, so ending the shell's group left a
   background job running. Closing a terminal now finds everything under the shell first and ends it all.
3. **A check tried in the dialog before anything was asked showed up as a stray card at the bottom of the
   chat**, with "Try 3 more rounds" on it. It belongs to no turn; the dialog shows its result, and the chat no
   longer does.
4. **`~` in the person's terminal is not the person's home.** The sandbox gives its programs a home of its
   own. The walk's first check ("can it list the home folder?") listed that one and passed for the wrong
   reason; it now names the person's real home, which is refused. The tab's note says that start-up files are
   not read.
5. **`python3` inside the sandbox is the coding engine's own Python**, which has no `pytest`. A project with an
   environment of its own is found (`.venv/bin/python` is what the check's suggestion then names); one without
   gets `python3 -m unittest` or must install what it needs. This is the first thing a person will meet, and
   it is why managed tools are stage C4's work.
6. **The evaluation's runner left a session "in the middle of a turn" after a time limit**, and the next task
   was refused. The runner now reads on to the turn's end and ends the session.
7. **The gateway forgets a session's cost when the session is ended.** After fault 6 was fixed that way, the
   first Sonnet run reported $0.00. The cost is now read before the session is ended, and the run was made
   again to have a counted number.
8. **A real model does not keep trying against a check that cannot pass.** Asked to fix a failure whose
   command ends in `exit 1`, the local model said that no change to the project can help, and stopped. The
   loop's rule for that (a failure, then nothing changed: "needs you") is what a person then sees, after one
   round and not three.
9. **The words of a turn's ending.** The loop writes one reason for a turn (`no_change`, `rounds_used`,
   `no_command`); the screens of C1b and C2 read it as how the agent's turn ended and would have shown
   "stopped with a problem". The stream and the routes now say the two apart (`why`, `check_why`).

## Decided while building, for the owner to see

1. **The person's terminal runs in the Python engine, not in the Tauri shell.** The plan's table named
   `portable-pty` in Rust. A shell started by the engine is inside the same sandbox code as the check, is closed
   with the engine, is tested by `pytest`, and can be walked in a browser. Only `xterm.js` was downloaded.
2. **A sandbox of our own for each project**, not the server's. The check and the terminal then work when the
   Agent Server is not running, and cannot reach another project the server has open.
3. **`why` keeps its five endings on the stream and in a turn's row as the window gets it.** The check's own
   reason is beside it, in `check_why`. The loop writes one word for both; `runtime.how_it_ended` splits it.
4. **The check's command is never set by us.** It is suggested, shown, and saved by the person. Until then a
   turn that changed files ends "not checked" and offers "Set a check".
5. **A session that only reads has no word.** However its turn ends, the word the session had stands.
6. **The agent's commands reach a package index only for ten minutes after an install step was let through.**
   The person's terminal always does.
7. **The list of hosts has no code hosting site.** A package that is fetched from a git address cannot be
   installed from inside the sandbox.
8. **`design/token-allowlist.json` has one new entry**, for `packages/ui/src/code/xterm-css.ts`: the style sheet
   of xterm.js carried as text, with the package's own fallback colours. The terminal's colours are set from the
   app's tokens when it opens.
9. **A step limit of 120** for a session that changes files and runs commands (60 for one that only reads).

## Not measured, not built

- **The real Tauri window was not opened.** The walk drives the real window's page in a browser with the real
  engine behind it; the folder picker is answered by the walk's stand-in. xterm.js inside the Tauri webview,
  with its copy and paste, was not tried.
- **A real install of a package by the agent** (`pip install`, `npm install`) from the window. The proxy was
  shown to let a package index through after an install step and nothing else; no package was installed.
- **Three failed rounds with a real model** (found 8).
- **Node, Rust and Go projects.** Every task of the evaluation is Python.
- **A check that needs the network or a database.** It will fail inside the sandbox; nothing says why.
- **A command that never ends in the agent's terminal** (a server in the foreground). The agent is told not
  to; one task of the first local run reached its seven-minute limit and may have been this. The step limit
  and Stop end it; nothing else does.
- **Two sessions on one project at the same time**, as in stage C2.
- **A command judged by its words can be wrong both ways:** `git checkout -- .` is asked about, a script that
  deletes is not. The sandbox and Undo are what holds.
- **"Show what is running"**, managed tools, build and lint as steps, the check's output through the storage
  interface, the approval card on other screens, the Browser and Preview tabs, Windows and Linux.
- **The web.** Coding is desktop only.

## For the next stage

- **"Show what is running"** (mockup `terminal-processes`): everything started in a project by the person, the
  agent or a check, with a way to stop each. The Terminal tab says `ps` does not work and offers nothing yet.
- **Managed Node** and the other tools a project needs (stage C4): today the sandbox finds what the computer
  has, and `python3` inside it is the coding engine's own Python unless the project has an environment.
- **The check's output through the storage interface**, and build, lint and test as separate steps.
- **Scheduled runs** (stage C6) call the same `Loop.run_turn` with `unattended=True`: a question is refused and
  written down. Nothing calls it that way yet.
- `CLAUDE.md` (it is not in the repository; the main checkout has it): its row "Working on the coding agent" was
  brought up to date with this stage.
