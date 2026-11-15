# Spike H0: the person's own agent program as a harness (2026-11-15)

ADR-0107, stage H0. Claude Code and Codex, each as an ACP conversation (`agent_kind: "acp"`) on OpenHands' Agent
Server 1.62.0, signed in with the owner's own plans, one real task each; then inside `sandbox-exec`, opened step
by step until they worked. Nothing of this is in the app; the scratch files were outside the repo.

## What was used

- The Agent Server from the installed coding engine (`<app data>/engine/coding/venv`) and its Node 24.22.3.
- The adapters OpenHands pins, downloaded with the owner's yes: `@agentclientprotocol/claude-agent-acp` 0.99.1
  and `@agentclientprotocol/codex-acp` 2.2.2. **682 MB in all** on this Mac: the Claude Agent SDK's darwin binary
  is 273 MB, Codex's darwin binary 328 MB. Gemini CLI was not tried.
- A small driver that starts a conversation, sends one request and follows its events; a CONNECT proxy on
  loopback that writes down every host asked for and can refuse hosts outside a list.
- Two small projects with a one-line bug in `calc.py` and a test.
- The programs' own sign-in from the owner's earlier use (`~/.claude`, `~/.codex`). **No login or token was read,
  printed, copied or sent by us**; the programs read their own.

## Results

| Run | Program | Where | Took | Cost the program reported | Result |
|---|---|---|---|---|---|
| 1 | Claude Code | no sandbox | about 30 s | $0.185 | fixed, test passes |
| 2 | Codex, `gpt-5.6-terra` | no sandbox | 20 s | $0.054 | fixed, test passes |
| 3 | Claude Code | strict sandbox (ADR-0102's profile) | | | refused, as expected: no network, no sign-in files |
| 4 | Claude Code | sandbox opened for its sign-in files and the proxy | 29 s | $0.157 | fixed, test passes |
| 5 | Codex, `gpt-5.6-terra` | the same | 41.5 s | $0.064 | fixed; it could not run pytest (none inside), checked the fix by hand |
| 6 | Claude Code | the same, proxy limited to `anthropic.com`, `chatgpt.com` | 29 s | $0.144 | fixed, test passes |
| 7 | Claude Code, session mode `plan` | the same | 33 s | $0.200 | **edited the file**: Plan did not hold |

The costs are what each program says it would cost at API prices; on a plan nothing is billed per call. They
come back in `stats.usage_to_metrics["acp-managed"]` with tokens (Claude names its model `acp-managed`; Codex
names the model).

## What the sandbox must open

Starting from ADR-0102's profile (writes only in the project and the engine's own state; reads denied under
`/Users`, `/Volumes`, `/private/var/folders`, `/private/tmp`; outbound network only to loopback):

- **The program's sign-in and settings, read and write:** `~/.claude`, `~/.claude.json` and its `~/.claude.json.*`
  backups for Claude Code; `~/.codex` for Codex. **Read only:** `~/Library/Keychains`.
- **The Agent Server keeps its own home.** It writes `~/.openhands/profiles`; it gets a home of its own
  (`HOME=<state>/home`), and the program alone is started with the person's real home by a small launcher.
- **Claude Code's temporary folder:** it writes `/tmp/claude-<uid>` and failed with `EPERM` there;
  `CLAUDE_CODE_TMPDIR` pointed inside the state folder fixes it.
- **The network through our proxy, by host:**
  - Claude Code: `api.anthropic.com` (12 to 13 connections per task), `mcp-proxy.anthropic.com` (5); it also tried
    `http-intake.logs.us5.datadoghq.com` (its own logs) and `raw.githubusercontent.com` once. With the list
    limited to `anthropic.com` the logs host was refused and the task still passed.
  - Codex: `chatgpt.com` only (28 connections).
  - So the lists are **Claude Code: `anthropic.com`; Codex: `chatgpt.com`** (and `openai.com` for a Codex on a key,
    not measured).

With the creds step in place, a command under the same profile still could not list `~/Documents`, `~/.ssh`, the
app's data folder, the repo or the other project, could not write in `~/Documents`, and could not reach
`example.com` outside the proxy. Only the program's own folders were opened.

## What else was found

- **Plan mode does not hold.** OpenHands' ACP agent approves every permission the program asks, including Claude
  Code's "Exit plan mode": in run 7 it planned, approved its own plan and edited the file. A read-only harness
  session must be made read-only by the sandbox (the project opened for reading only), not by the program's mode.
- **Codex's default model can fail on a plan.** The owner's `~/.codex/config.toml` names `gpt-6.1-sol`, which Codex
  refuses "when using Codex with a ChatGPT account". The session has to choose a model the plan allows;
  `POST /api/acp/models` lists them (Codex: gpt-6.1-sol, gpt-6-luna, gpt-5.6-terra, gpt-5.6-luna; Claude: default,
  opus, sonnet, haiku, fable and others), but not which ones the plan allows.
- **The program's tools are not ours.** Codex's `git status` failed inside the sandbox and pytest was not there:
  the tools a program uses come from the sandbox's `PATH`, so a harness session needs the same tools as a Wasify
  AI session (the project's Python and Node parts).
- A turn's events arrive as `ACPToolCallEvent` and `MessageEvent` (with the program's reasoning), and the end as
  `ActionEvent`/`ObservationEvent`; the conversation goes `running` then `finished`.

## Not measured

- **Starting sign-in from the app.** The programs were already signed in. The way proposed for H1 is to open the
  program's own sign-in command (`claude` `/login`, `codex login`) in the Terminal tab, so the program shows its
  own page in the person's browser; not tried.
- **A reached plan limit.** It cannot be caused on purpose here; how it looks is left to H1.
- Gemini CLI; Codex on an OpenAI key; a Codex run in `plan`/read-only mode; the time to start a program cold.

## What this means for ADR-0107

- Decisions 1 to 5, 7, 8 hold as written; the host lists of decision 5 are the ones above.
- Decision 6 changes: **Plan on a harness is a sandbox with the project open for reading only**, not the program's
  own mode.
- The optional part is large: about 680 MB for the two adapters on a Mac, before Gemini CLI.
- The model of a harness session is chosen from the program's own list, and a model the plan refuses must fail in
  words.
