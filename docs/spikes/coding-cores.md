# The coding product's cores: what is built, what is not wired in, what was settled

- **Date:** 2026-11-14
- **Branch:** `coding-cores` (worktree `.claude/worktrees/coding-cores`), from `main` at 1c89b31a.
- **Decisions it follows:** ADR-0101 (the place interface), ADR-0103 (the check loop and undo), ADR-0105 (the
  scheduler). Plan: `docs/v2-coding-agent-start-plan.md`, sections 4, 5, 6 and 8.
- **Not touched:** the Accepted ADRs, `docs/contracts/`, the SSE contract, `lib/products.ts`, every screen, the MCP
  server, and the files of stage C1a (`services/coding-engine/`, `components/coding.py`, `coding_server.py`).

## In short

The parts of the coding product that need no screen and no running engine now exist as library code with tests, in
`products/wasifyai-code/`. Nothing is wired into the app. The tests use a real git, a real SQLite, a real Postgres
and real child processes; the only pretended things are the agent (there is no engine yet) and the clock.

| | |
|---|---|
| Tests | 225, all passing on SQLite and on Postgres 16, three runs in a row (208 pass and 17 skip where no Postgres answers) |
| `ruff check`, `ruff format --check`, `pyright` | Pass, for the package and for the whole repository |
| New dependency | None. Python's standard library and what the repository already had |
| Download, model run, use of a model key | None |

## What is built

| File | What it does | Tests |
|---|---|---|
| `wasifyai_code/place.py` | The interface between the product and an engine: start a session, send, run, stop, follow its events, answer a confirmation. Six plain kinds of event and five plain reasons a turn ends. `FakePlace` is a place in memory whose "agent" is a function the test gives; it writes real files | 8 |
| `wasifyai_code/store.py` | Rows for workspaces (with the check command), sessions, turns, checks, checkpoints, schedules and schedule runs. One class on SQLite (`code.db`) or Postgres (schema `code`), the way training and 3D do it. Every row carries `tenant_id`, `product_id` and the person | 33 |
| `wasifyai_code/checks.py` | One run of a check command: its own process group, a time limit (ten minutes by default), the whole group stopped at the limit, on Stop and when the command has ended, an optional wrapper in front for the sandbox, a cleaned environment. Which changed files are tests | 48 |
| `wasifyai_code/loop.py` | `Loop.run_turn`: the turn's states, three rounds, the four result words, Stop in every state. One function for a chat turn and a scheduled run. `Loop.check_now` runs the check outside a turn | 29 |
| `wasifyai_code/checkpoints.py` | A git store outside the workspace with the workspace as its work tree: `checkpoint`, `undo` (one more checkpoint first), `changed_since`, `changes`, `left_out` | 16 |
| `wasifyai_code/schedules.py` | The plain rules, `next_due` (pure, on `zoneinfo`), the two clock-change rules, `Timer` (one timer, a clock that can be pretended) | 63 + 19 |
| `evals/tasks.json`, `evals/run_eval.py` | The 36 tasks and a runner written against the place interface. `--start` proves each hidden check fails on the starting files | 9 |

### The loop, arrow by arrow

Each line is a test in `tests/test_loop.py`, against the pretended place, a real store, a real git and real checks.

| Case | Result |
|---|---|
| The check passes | `passed`; states working, turn ended, checking, done; one check row; a checkpoint before the turn and one of the state that passed |
| Fails, then passes | `passed` after two rounds. The agent was sent the command, the exit code and the end of the output |
| Three fails | `failed`, "needs you", with what still fails. Nothing is sent after the third. The person's next message starts a new count |
| The time limit | `could not check`. Nothing goes back to the agent |
| A command that is not there | `could not check` |
| No command set | `not checked` |
| The step limit | `not checked`, though the files would have passed: the check is not run |
| Stop while the agent works, when the turn has just ended, while the check runs, while the agent fixes | `not checked` each time. Stop during a check returned in under a second and left no process |
| A question (no file changed) | No check runs, no word changes, nothing is sent back, in a new workspace, after a pass and after a failed turn |
| Files brought back to exactly what passed | `passed` stands, no check |
| The agent changes nothing after a failure | `failed`, "needs you", after one round |
| A check that leaves a child running | The result is the command's; the child is gone |
| Changed and deleted test files | Listed on the check row; new test files are not |
| An error, a refusal, a place that fails | `not checked` |
| A scheduled run that asks a question | The question is refused and written on the turn; the same rows as a chat turn |
| The review's case, with a real pytest | A project with an old bug, a request that adds a function, a check that covers both: one failure back, one fix, one pass, the test file untouched |

### The scheduler

- `next_due` is tested for every kind of rule in New York, Berlin and Sydney (and Lord Howe, whose clocks move by
  half an hour, and Kolkata, which never changes): both clock-change days of 2027, a whole year of days, and the ends
  of short months including February of a leap year. The expected moments were worked out by hand.
- The timer is tested on a pretended clock: fires at its time; never sleeps longer than a minute; 170 wakes with
  nothing due read the store not once; one catch-up run after an absence and the rest missed; a time older than a day
  not run; a time skipped while the earlier run is still going; runs of different schedules one at a time; a clock set
  forward noticed within a minute; "Run now".
- Two timers on one store give one run, on a SQLite file with two connections and on Postgres. Eight threads claiming
  one due time at the same moment: one gets it.

## What is not wired in

Nothing here changes what the running app does.

- The package has **no `wasifyai.products` entry point** and no `product.yaml`, so the engine does not load it. It is
  not in `services/api`'s `desktop` extra and not in `scripts/build-engine-bundle.sh`.
- No action, no route, no help file, no row in `docs/contracts/actions.json`, no entry in `lib/products.ts`, no screen,
  no event on the SSE stream.
- No real place. `place.py` has the interface and the pretended one; the one that talks to the Agent Server
  (`client.py`, stage C1b) is not written.
- The store is not opened by the engine (`assemble.py` is untouched).

## Shared files changed

- `uv.lock`: 12 lines, the new workspace member `wasifyai-code`. It has to change because `products/*` are workspace
  members by a glob.

Nothing else outside `products/wasifyai-code/` and this file. The root `pyproject.toml` is not changed (stage C1a
changes its `exclude` line in its own worktree). The tests import no helper module by name, so pyright's
`extraPaths` needed no line.

## Open points, and how each was settled

The first three are the points ADR-0103 (decision 13) left for stage C2. The ADR is not edited; this is what the
code does, as input for its amendment.

1. **Undo restores the person's own git: yes** (the ADR's proposal). Each checkpoint saves where `HEAD` points, the
   commit of that branch and the index file. Undo puts all three back. Tested: after the agent committed twice and
   made a branch, undo gave back the person's commit, branch, staged file and unstaged edit, `git fsck` was clean, and
   undoing the undo gave the agent's branch and commit back. The agent's commits are not deleted; they stay in the
   person's git. **Not restored:** other branches and tags the agent made, stashes, a merge in progress. If the agent
   ran `git init` in a project that had no git, undo leaves that folder there.
2. **Ignored files are left out, and the checkpoint says so** (the ADR's proposal). `Checkpoint.left_out` and
   `left_out()` name them (`.env`, `node_modules/`), for the screen to show. Undo does not touch them. A change to an
   ignored file alone does not count as "files changed".
3. **A project that holds another git folder: its files are kept as plain files.** This was not tried in the spike,
   and plain `git add -A` gets it wrong in two ways, both seen with git 2.54:
   - an inner project **with** a commit is recorded as a pointer to that commit and none of its files, so undo would
     restore nothing inside it;
   - an inner project **with no commit yet** makes the whole `git add` fail (`does not have a commit checked out`),
     so no checkpoint at all could be taken. The spike's script would not have noticed: it threw git's errors away.

   What the code does: before `git add`, each such folder's files are put into our index by name. From then on git
   treats the folder as an ordinary one. Its own ignore rules still hold. A folder with nothing to keep is left out
   of the `add`. Tested with an inner project with a commit, one without, one inside another, and one emptied
   between checkpoints. The inner project's own git state is not saved or moved.
4. **When the check runs.** The ADR says "only when files changed since the last pass". Taken alone that breaks the
   plan's own gate ("a question in a workspace whose check fails is answered, and no file changes"): in a workspace
   that has never passed, or after a failed turn, a plain question would run the check, fail, send the failure to the
   agent and set it editing. So the rule in the code is: the check runs when the agent finished **and the turn
   changed files** (compared with the checkpoint taken before it, or with the state straight after the check of the
   round before) **and the files differ from the last state that passed**. A turn that changed nothing runs no check
   and changes no word. The cost: files the person edited by hand between turns are not checked until the agent
   changes something or the person runs the check (`Loop.check_now`).
5. **A turn that ended any other way than "finished" is "not checked"**: stopped, the step limit, an error of the
   engine, a refusal by the model. The ADR names the first two.
6. **No command set is "not checked"** (the plan's table: a blank box must be a state the person sees). **A command
   that cannot run is "could not check"**: the shell's exit codes 126 and 127, a time limit, a crash (killed by a
   signal), or a wrapper that cannot start. Only exit code 0 is a pass.
7. **The agent changes nothing after a failure:** the turn ends as "failed, needs you" without running the same check
   again.
8. **Stop after a failed check, before the next round:** the result stays "failed" (it was checked), and the loop
   does not go on.
9. **A checkpoint that cannot be taken** (git fails) does not stop the turn. It is written on the turn ("cannot be
   undone") and the check then runs whatever changed.
10. **Interval rules** ("every 15 minutes", "every 2 hours") count real time from a `start` kept in the rule. A clock
    change does not move them. The other kinds are wall-clock times in the schedule's zone.
11. **"On time" and "missed".** A time noticed within 90 seconds is on time. Later than that it was missed: it runs
    if it is less than a day old and the schedule says "run when missed", and is recorded as missed otherwise.
12. **A long absence does not write thousands of rows.** The last 20 missed times get a row each; one more row
    stands for all the earlier ones (`stands_for`). Two weeks of a five-minute rule: 22 rows for 4,032 times.
13. **The claim.** ADR-0105 says a due time is claimed by writing its row. The store has that rule (one row per
    schedule and due time). The timer also moves the schedule's next time in the same transaction, and only if it is
    still the one it saw. Without that, two timers that looked a moment apart could each claim a different "latest"
    time and both run.
14. **A changed schedule starts again from now.** Times that passed while it was off, or under the old rule, are not
    "missed".
15. **Empty folders and unusual permissions are restored too.** Git keeps neither. Each checkpoint remembers the
    empty folders and the permissions other than the usual two (a key file readable only by its owner), and undo
    puts them back. The spike listed the empty folder as not restored.
16. **Line endings and filters.** A project's `.gitattributes` (line endings, a large-file filter) is switched off
    for our store, and the person's and the system's git settings are not read, so a file comes back byte for byte.
    Tested with a hostile home folder (a global ignore file, `autocrlf`, commit signing).
17. **The evaluation's answer** for a question is the agent's last message. The tasks are copied into the product
    (`evals/tasks.json`); the spike's file stays as the record of what was run, and a test keeps the two the same.
18. **Store migrations.** The product stores (training, 3D) make their tables with `open_tables` and a `meta`
    schema row, not with the numbered migrations of the engine's own stores. This store does the same.

## Found on the way

- **Python's own way of waiting for a child program hangs** when something the child started still holds its output
  open (`asyncio`'s `wait()`, Python 3.12). That is exactly "a check that leaves children behind". The check is
  started as a plain child and its end is waited for in a thread.
- **Two rows written in the same millisecond changed places** when listed. Row times are now to the microsecond and
  never repeat within one process.

## Measured

| | Result |
|---|---|
| A checkpoint of this repository (2,485 files) | 3.2 s the first time, 0.4 s the next, 86 MB (the spike: 3 s, under 1 s, 88 MB) |
| "Did files change?" on this repository | 0.06 s |
| Stop during a check | Under 1 s, no process left (asserted in the tests) |
| The 36 hidden checks on the starting files | All 36 fail, as they must (1.2 s) |
| The whole test suite | About 30 s |

## Not measured, not built

- **No real engine and no real model.** The loop has only met the pretended place. The plan's gate for the loop
  (C3) is still to run: the review's case with a real model, a two-minute check with every other call answering
  within a second, the same rows from a real scheduled run.
- **No sandbox.** The check takes a wrapper and the tests use a stand-in for it; `sandbox-exec` with the real
  profile was not run. A child that leaves the check's process group (its own session) is not stopped by us: only
  the sandbox can hold that.
- **The check's environment.** By default a check gets a short cleaned environment (`PATH`, `HOME` and the like).
  When it is wired in it should get the same environment the coding server gives the agent's commands.
- **Not built in the loop:** the usage event for a check, the check's output through the storage interface (it is
  written to a folder the caller gives), the events on the stream, suggesting a check command from the project's
  files, dropping old checkpoints.
- **Not built in the scheduler:** the function that joins the timer to the loop (the copy of the workspace, the
  changes offered to apply), the job in Running now, the one-job-per-person rule on the web, starting at login. The
  timer was not run on a real clock for the gate's "within two seconds" and "a week of nights". The computer was not
  put to sleep.
- **Checkpoints:** two processes taking a checkpoint of one workspace at the same moment (git's own lock makes one
  fail; not tried). A workspace on a file system that ignores case was not looked at. An undo more than two weeks
  after its checkpoint may find that the person's git has dropped a staged file's content; not tried.
- **Windows.** `zoneinfo` needs the `tzdata` package there, and the process group code is for macOS and Linux.
  Windows is not in v1.
- **The TypeScript half of `make lint`** (`pnpm lint`, `pnpm typecheck`) was not run: this worktree has no
  `node_modules`, installing them is a download, and no TypeScript file changed.
- **The repository's whole test suite** was not run, only this product's. No other package imports this one.

## For whoever wires it in

- `CLAUDE.md` (the row "Working on the coding agent") still says nothing is built. It lives in the main checkout,
  outside this worktree, and was left alone.
- Section 5 of the start plan lists `store.py`, `place.py`, `loop.py`, `checks.py`, `checkpoints.py` and
  `schedules.py` as not existing yet. They exist now; `client.py`, `events.py`, `actions.py`, `routes.py` and
  `extensions.py` do not.
- Points 1 to 3 above are the content of the amendment ADR-0103 asks for in stage C2.
