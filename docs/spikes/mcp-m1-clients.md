# M1 with the three real clients, run 2026-10-27

ADR-0069 stage M1, after the conformance tests. Claude Code 2.1.302, Codex 0.163.0 and OpenCode 1.19.3 (the same
installs as spike S1) drove the built MCP server through `wasify-mcp` (the Rust launcher, debug build) against a
desktop engine on a temporary data folder with the stub image engine. The model behind each client was S1's scripted
fake (no credentials), told which tools to call; a small "approver" played the person in the window, answering the
card after 3 s (the tour) or 30 s (the late approval). The harness is `~/Projects/wasifyai-spikes/m1` (outside the
repository; S1's fake model with wider id matching, the three run scripts, the logs).

## What each client did

| | Claude Code | Codex | OpenCode |
|---|---|---|---|
| Tools seen from the launcher connection (make, models, read) | 33 as `mcp__wasify__*` | 33 in the `mcp__wasify` namespace | 33 as `wasify_*` |
| How a result reaches the model | the structured content as JSON text (4,271 chars for `app_status`) | "Wall time … Output:" plus the JSON | **the text content only** (991 chars) |
| `image_generate`, card approved after 3 s | job handle after 4.0 s, `job_wait` done in 0.6 s | job handle after 3.4 s, done in 0.6 s | "running as job …" after 3.8 s, done in 0.7 s |
| `image_generate`, card approved after 30 s | `needs_approval` with the id after 25.0 s; `approval_status` answered approved with the job in 5.6 s; the job done | the same, 25.0 s then 5.4 s | the same, 25.0 s then 5.9 s, from the sentence alone |
| A tool outside the scopes (`library_search`) | not in the list: "No such tool available" | "unsupported call" | "unavailable tool" |
| The app closed (no runtime file) | the one stub tool, "Open Wasify AI, then restart your agent …" | at first **refused to call the stub** ("requires approval, but approval policy is never"); with `readOnlyHint` on it, the call is made and the model gets the sentence (the item is marked failed, as an error result should be) | the stub tool and the sentence |

No client needed the fixed HTTP port, a secret in its config, or a restart when the engine restarted between runs.

## What the run changed

1. `WASIFYAI_MCP_LAUNCHER` is the variable the engine reads for the launcher's path (it read another name; Settings
   showed a placeholder).
2. Every result's sentence carries its `job_id` and `approval_id`, and `approval_status` answers a sentence too:
   OpenCode hands its model only the text, so an id that lived only in the structured part was invisible to it.
3. The launcher's own `app_status` (the app-closed answer) now carries `readOnlyHint`, because Codex's default
   policy refuses a tool without it. Rebuilt and re-run: Codex calls it and reads the sentence.

## Not verified

The three clients' interactive screens (all runs were non-interactive, Claude Code with permissions bypassed); the
tool list refreshing after the app starts (S1's open problem 6); Windows and Linux; a real model choosing the tools.
