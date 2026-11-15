# Stage H1: coding sessions on the person's own Claude Code or Codex (ADR-0107)

Built 2026-11-15 on branch `coding-harness`. The owner accepted ADR-0107 the same day ("Accept, start H1").
Stage H0 (the spike) is `docs/spikes/coding-harness-h0.md`.

## What was built

- **The harnesses** (`services/api/src/wasifyai_api/coding_harness.py`). There are two:
  - **claude-code:** Anthropic's Claude Agent SDK program, run through `@agentclientprotocol/claude-agent-acp`.
  - **codex:** OpenAI's Codex, run through `@agentclientprotocol/codex-acp`.

  For each one the file holds:
  - the provider hosts the program may reach;
  - the sign-in files in the person's home that it may write;
  - what it may read (the keychain and the installed programs);
  - its own commands for sign-in state and for signing in.
- **The optional part "Agent programs (Claude Code, Codex)"** (`components/harness.py`):
  - It runs `npm ci --ignore-scripts --omit=dev` from the committed lock in `services/coding-engine/harness/`, using the Node part's npm. Every package in the lock has an integrity hash, so no install script runs.
  - It then starts each program with `--version` to check it.
  - It is offered only where the coding engine is, and it needs the coding engine and Node set up first.
- **One sandboxed Agent Server per harness** (`CodingServer.for_harness`). Each server:
  - has its own run folder;
  - uses the same profile as the Wasify AI server, opened further for one program only:
    - its sign-in paths, for writing (including the files that begin `.claude.json.`);
    - the keychain, for reading;
    - the installed programs, for reading;
    - the install proxy under the harness's own name. The proxy lets through only that provider's hosts, and refuses every other host with `not_the_provider`.
- **Sessions** (`wasifyai_code/client.py`, `events.py`, `runtime.py`):
  - **Model and settings:** a session's model is `<harness>:<program's model>`, and `<harness>:default` means the program chooses. The session sends the ACP agent's settings with no model key, no token, no security analyser and no hooks of ours.
  - **What a harness session does not get:**
    - "Ask me" is refused.
    - Skills, plugins and hooks are not given to a harness.
    - A session that only reads is made read-only by the sandbox, because the project is opened read-only. For Claude, the program's Plan mode and a note at the start of each message are added as well.
  - **Cost:** the program's own report of cost and tokens is added to the session, with `counted_in: "plan"`.
- **Sign-in** (`HarnessAccounts`):
  - The program's own commands run outside the sandbox, with the person's real home and a clean environment.
  - Only three things are kept: signed in or not, how, and the plan. The email is never kept.
  - "Sign in" starts the program's own login and gives back the provider's page to open.
  - Nothing of ours reads, stores or sends a login or token.
- **Routes:**
  - `GET /code/harnesses`
  - `POST /code/harnesses/{harness}/sign-in`
  - `POST /code/harnesses/{harness}/sign-in/cancel`
  - `GET /code/harnesses/{harness}/models`

## Measured

| What | Result |
|---|---|
| The part's size on disk | 694 MB, 125 packages (`install_bytes` 694400000) |
| Installing from npm's cache | 2 s |
| Hostile tests on a harness's server (`test_coding_harness_sandbox.py`) | 12 pass. The program's own sign-in can be read and written. Nothing else in the home folder can be read or written: `Documents`, `.ssh` and the other program's sign-in are refused. The app's data is refused. The internet is refused directly. The proxy refuses any host that is not the provider's, including PyPI. A process outside cannot be signalled |
| The existing hostile and real-session tests | 30 pass, unchanged |
| The gate (`test_coding_harness_real.py`): Claude Code on the person's plan, model `haiku` | Finished in 1 round; changed 1 file; the check passed; undo put the file back. The program reported $0.004119 and 73,448 tokens in / 818 out |
| The gate: Codex on the person's plan, model `gpt-5.6-terra` | Finished in 1 round; changed 1 file; the check passed; undo put the file back. The program reported $0.048778 and 92,829 tokens in / 540 out |

The costs are what the programs reported. They are counted against the person's plan, not paid by the app.

## How to run

```bash
make test-coding
```

```bash
CODING_E2E=1 CODING_HARNESS_E2E=1 uv run pytest services/api/tests/integration/test_coding_harness_real.py -s
```

`make test-coding` runs the hostile tests, including the harness ones. The second command is the gate. It uses the person's own plans, so they must be signed in.

## Not done

- **The screens (H2, mockup first):**
  - the harness in the model picker;
  - "Sign in" in Settings;
  - what a session on a harness shows.
- **Scheduled runs and the evaluation on a harness (H3).**
- **Gemini CLI** (open question 3).
- **A program the person installed themselves.** Only the part's own copy is used.
- **Installs inside a harness session.** The proxy gives a harness only its provider, so it has no package index.
- **A plan whose limit is reached.** This was not seen; the program's error is shown as it comes.
- **The program's own Plan mode** is not trusted (H0). Read-only comes from the sandbox.
