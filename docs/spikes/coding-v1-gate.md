# Coding agent: the v1 gate

Written 2026-11-15 on the owner's Mac (M5 Pro, macOS 27.0). This is piece 10 of
`docs/v2-coding-agent-start-plan.md`, section 9: "The evaluation with Sonnet 5.5, the hostile tests, a walk of
every screen in the real window. Written results; the owner's yes." It was run on the tree of the Browser tab's
branch (every stage from C1a to the Browser tab), on the owner's order ("lastly v1 gate").

**The yes is the owner's.** This note is the written results. It also says plainly what the gate asks for and
was not done: nobody has looked at the real window.

## The results

| Part of the gate | Result | How it was measured |
|---|---|---|
| The evaluation, Claude Sonnet 5.5 | **36 of 36 passed.** 12 min 19 s for the 36 tasks, median 15 s a task, the longest 70 s | `products/wasifyai-code/evals/run_eval.py --data <throwaway> --model claude-sonnet-5-5 --app-keys --limit-usd 4`: the real coding engine in its sandbox, the model through the gateway, the key through the app's own secret store, each task checked by a hidden check the agent never sees |
| Every change undone exactly | **36 of 36 undone exactly and 36 of 36 brought back exactly** (32 files changed) | The same run |
| What it cost | **$1.95**, counted by the gateway | The same run. About $5.70 of the $25 the owner allowed is now used |
| The hostile tests | **54 passed** (30 hostile tests, 24 of the sessions): writes outside the project, reads of secret folders, the internet, the key, a model told to try other ways, a hook's write outside, a scheduled run's copy | `make test-coding` on the real engine in its sandbox, with a scripted model |
| The walks, with a real model (the local Qwen 27B) on a fresh data folder | **All seven passed** (below) | `apps/desktop/scripts/ui-audit.sh light <name>`: the real window's page driven in a browser, the real Wasify engine, the real coding engine; what a walk claims is read back from the project's files on disk |
| The shell's own tests in the real app | **Passed**: the Browser tab's webview, the login item and the menu bar item | `docs/spikes/coding-browser.md` |
| `make test`, `make lint` | **Passed** on this tree: 3,767 Python tests and 498 skipped; 1,317 TypeScript tests; 44 shell tests; ruff, pyright, the design check, Biome, the TypeScript check | `docs/spikes/coding-browser.md` |

### The walks

| Walk | What it showed |
|---|---|
| `code-plan` | A folder chosen, a question answered in Plan in 31 s with no file changed, the Files tab, a file found by name, the cost, the session in the Library |
| `code-edit` | A change with no question (34 s), the card for a file Undo cannot put back (yes, no, "Allow for this project", Stop in 0.33 s), the Changes tab, Undo and "Bring it back", each read back from disk |
| `code-check` | The check set and tried; one refusal, one fix, one pass in 16 s; a check of two minutes with the screen live; Stop during a check in 0.23 s; "needs you"; the person's terminal held by the sandbox; a delete asked first and undone; `git init` by the agent |
| `code-build` | A new project from the starter, then "a to-do web app with a logo": a real picture made by Wasify AI's picture product after a yes, the check passed, and the page used in the preview (10 min) |
| `code-extensions` | The short list, a public skill's text, one of ours firing, ours off and a public one on, a skill added from a folder whose rule the answer followed, its removal |
| `code-scheduled` | A schedule from a template, "Run now" on a copy (40 s, passed), the project byte for byte unchanged, the change applied; a plugin's hook only after approval |
| `code-browser` | The Browser tab's bar and the stay-open switch (the pages themselves are the shell's; see its own tests) |

**Run again on 2026-11-18 (LM3, `docs/spikes/coding-local-lm0.md`):** the local model is now the Model hub's
choice on the app's own `llama-server`, not Qwen 27B through Ollama. All seven walks passed on
`Qwen3.8-27B-Q4_0.gguf`, and the 36 tasks passed 33 of 36 through the same route.

## What the gate asks for and was not done

1. **"A walk of every screen in the real window."** The walks drive the window's page in a browser, with a
   stand-in for the shell. The real Tauri window was started only by the shell's own tests, which look at
   nothing. A person has not looked at: the Browser tab's page inside the window, the menu bar item, a real
   login, the folder picker, and every coding screen in the real window. The list of what to look at is in
   `docs/spikes/coding-browser.md`.
2. **A week of scheduled runs.** Measured as seven timed runs five minutes apart (`docs/spikes/coding-c6.md`).
3. **Stage C1's check in the real window**, which the owner put off ("We can check C1 later").

## What is not in v1, by the stages' own notes

Each stage note lists what it did not build. The ones a person would meet first:

- Windows, Linux and Intel Macs (ADR-0102, decision 10); the web (coding is desktop only).
- A plugin's tool connections; extensions from the internet; the integrations list.
- A diff of each file before a scheduled run's changes are applied; a schedule moved to another project.
- Tabs, history and downloads in the Browser tab; the agent has no browser.
- "Show what is running" in the Terminal tab; other managed tools than Node; more starters than one.
- A session going on after the app was closed and opened again starts a new conversation with the agent.

## Found while running the gate

1. **Two older walks had drifted from the screens and their fixtures.** `code-plan` and `code-edit` need the
   two small projects they were written for; `code-edit` looked for words that are now also inside a folded
   list. The walk was corrected. Neither was a fault of the product: what each claims was read back from disk.
2. **One engine must be gone before the next starts.** Two walks run back to back failed to reach their
   engine. The gate's script now waits for the port to be free.
3. **A test of the login item failed on Windows in CI** (a Mac's path is not a whole path there). It is now a
   test for where paths look like a Mac's. The shell itself built on all three systems.

## The pull requests, in the order to merge

| # | Stage | Branch |
|---|---|---|
| 23 | X2: Extensions | `coding-x2` |
| 24 | C6 with X3: Scheduled, plugins | `coding-c6` |
| 25 | The Browser tab, starting at login, the menu bar | `coding-browser` |
| this one | The v1 gate: this note and the corrected walk | `coding-v1-gate` |

Each is stacked on the one before. Merging them in this order, each into `main`, keeps every one small.
