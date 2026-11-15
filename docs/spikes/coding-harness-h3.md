# Stage H3: Scheduled on a program, and the evaluation on each program (ADR-0107)

Built and measured 2026-11-15 on branch `coding-harness`. Stage H2 (the screens) is
`docs/spikes/coding-harness-h2.md`; the run on a key that this one is set beside is
`docs/spikes/coding-v1-gate.md`.

## What was built

- **Scheduled on a program** (`products/wasifyai-code/wasifyai_code/scheduled.py`):
  - A schedule runs on its own model, or on the model of the project's newest session. When that is a program's model (`claude-code:…`, `codex:…`), the run is a session on that program, on a copy, in "Work on its own", the same as on a key.
  - A program that is not set up or is signed out ends the run in words, for example "Sign in to Claude Code first". Nothing is copied.
  - Two tests on the pretended place: a run on a copy, and the signed-out program.
- **The evaluation on a program** (`products/wasifyai-code/evals/run_eval.py`):
  - `--model claude-code:<model>` or `codex:<model>` runs each of the 36 tasks on that program, on the person's own plan, on the program's own sandboxed server, with the install proxy letting through only its provider. It needs no `--app-keys`.
  - The cost is what the program reported, marked `counted_in: "plan"`.
  - A task that the program refuses because the plan's limit was reached is not counted as a failure: the run stops there, and that task and the rest are listed as not run, with the program's own words (`stopped`). The words are matched the same way as the window's limit card (`PLAN_LIMIT`).
- **"Tested for coding" per program model:**
  - `HARNESS_TESTED` in `runtime.py` holds what the evaluation measured.
  - `GET /code/harnesses/{harness}/models` gives it as `tested`.
  - The Your agent row says "Tested for coding here: …" or "Not tested for coding here."

## The gate: the same rows as a session on a key

Each run was `run_eval.py --data <throwaway> --model <model> --limit-usd 5`, on the real coding engine and the person's own signed-in programs. Each task was checked by a hidden check the agent never sees.

| | On a key: Claude Sonnet 5.5 | Claude Code, Haiku | Codex, GPT-5.6 Terra |
|---|---|---|---|
| Passed | 36 of 36 | **36 of 36** | **19 of 19 that ran**; the free ChatGPT plan's limit stopped the other 17 |
| Undone exactly | 36 of 36 | **36 of 36** | **36 of 36** (19 with a change) |
| Brought back exactly | 36 of 36 | **36 of 36** | **36 of 36** |
| Files changed | 32 | 32 | 19 |
| Time | 12 min 19 s; median 15 s a task, longest 70 s | 16 min 41 s; median 21 s a task, longest 76 s | 19 tasks: median 50 s a task, longest 78 s |
| Cost | $1.95, counted by the gateway, on the key | **$0.23** as the program reported it, on the plan | **$1.05** as the program reported it, on the plan |

What each program did, by kind of task:

| Kind | Claude Code, Haiku | Codex, GPT-5.6 Terra |
|---|---|---|
| bug | 8 of 8 | 8 of 8 |
| feature | 8 of 8 | 8 of 8 |
| refactor | 3 of 3 | 3 of 3 |
| multi | 4 of 4 | not run |
| question | 4 of 4 | not run |
| tests | 2 of 2 | not run |
| data | 1 of 1 | not run |
| hard | 6 of 6 | not run |

**About the Codex run.** The ChatGPT account used is on the free plan. After 19 tasks, Codex answered every request with "You've hit your usage limit… try again at Dec 15th, 2026", so the other 17 tasks never started. The first run of the evaluation counted them as failures, each after waiting a minute. That was the evaluation's fault: it now stops at a plan's limit and says so (above). The other 17 tasks wait until the limit resets on 2026-12-15, or for a paid plan. The same message is matched by the window's limit card from H2, so a person sees the program's own words with "Try again" and "New session on another agent".

A smoke run of one task (`bug-paginate`) went first on each program: Claude Code passed in 17.9 s and reported $0.004; Codex passed in 39.6 s and reported $0.059. Undo was exact on both.

## Tests

- `products/wasifyai-code/tests/test_code_scheduled.py`: the two Scheduled tests.
- `test_code_harness.py`: what the evaluation measured for a model.
- `test_evals.py`:
  - a program's model is known as one;
  - a run stops where the plan ran out and counts no failure.
- `apps/desktop/src/choices/code-choices.test.ts`: the "Tested for coding here" words.
- All of `products/wasifyai-code/tests` passed (352, 17 skipped), as did the desktop choices (57); ruff and pyright are clean.

## Not done

- The 17 Codex tasks that the free plan's limit stopped.
- Other program models: Claude Code's Sonnet and Opus, and Codex's other models. Each says "Not tested for coding here" until it is run.
- A Scheduled screen that names the program a schedule runs on, and choosing one there. A schedule follows the project's newest session (or its own model).
- A real scheduled run on a program in the real window. The run itself is the same session as the evaluation's, and is covered on the pretended place.
