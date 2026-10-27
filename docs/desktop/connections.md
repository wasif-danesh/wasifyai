# Other apps (the MCP server) on the desktop

Part of [the desktop profile](../desktop-profile.md). ADR-0069, built 2026-10-27 (stages M1 to M3).

Coding agents (Claude Code, Codex, OpenCode) use the app as a tool. The engine serves `POST /mcp` on its loopback
port; the stdio launcher `wasify-mcp` (built beside the shell) is what the agents run.

| Piece | Where |
|---|---|
| Engine | `services/api/src/wasifyai_api/mcp_server/`: `connections.py` (store, service, principals), `tools.py` (one tool per catalogue action offered to `mcp`), `calls.py` (the executor runs it; jobs, progress, approvals), `approvals.py` (the desk), `endpoint.py` (the SDK's server and the gate), `routes.py` (Settings and the window's answer), `runtime_file.py` (`engine.json`, the switch), `fixed_port.py` (the opt-in HTTP port), `skill.py` (the skill file for Claude Code) |
| Window events | `GET /desktop/events` (server-sent; `approval` when an agent waits), `wasifyai_api/desktop_events.py` |
| Launcher | `apps/desktop/src-tauri/src/bin/wasify_mcp.rs`; `cargo build --bin wasify-mcp`; the shell passes its path as `WASIFYAI_MCP_LAUNCHER` |
| Settings | `packages/ui/src/connections/ConnectionsSettings.tsx` in Settings > Other apps; the cards `ApprovalCards.tsx` in the window |
| Tables | `mcp_connections`, `mcp_activity` (SQLite on first use; Alembic 0023, 0024 adds the daily quota) |
| Review | `docs/mcp-security-review.md` (stage M3: the phase 4 checklist, row by row) |
| Tests | `services/api/tests/test_mcp_server.py` (the SDK's client on three protocol modes, the gate, approvals, the launcher) |

**How it is used.** Settings > Other apps > "Let other apps use Wasify AI" makes the launcher's connection, keeps its
secret in the keychain (`mcp.launcher.secret`) and writes `<app data>/engine.json` (0600: pid, port, secret). The
page then shows the command to paste for each client. The agent's tool list is the catalogue filtered by the
connection's scopes; a `make` shows a card in the window unless the connection's setting says otherwise; deleting
and consent always ask. A call that waits more than 25 s answers with a `job_id` or an `approval_id` to follow.

**Files (M2).** A connection's read and write folders (Settings > Other apps; a new connection may write into
`~/Documents/Wasify AI exports`) ride on its principal: `library_export` takes a `folder` inside a write folder,
`speech_transcribe` a `path` under a read folder, both held to spike S2's rules (`wasifyai_platform_sdk.folders`).

**Limits (M3).** A connection runs one job at a time (a second long call is refused with `busy` and the running
job's id) and has a daily quota of tool calls (default 1,000; "Tool calls a day, at most" on its row) besides its
rate per minute. "Running now" at the top of the page lists what runs, with "from Codex" and a Stop button
(`GET /actions/jobs`, `POST /actions/jobs/{id}/cancel`).

**Over HTTP (M3).** "A fixed port, for apps that connect over HTTP" opens a second loopback port that serves only
`/mcp` through the same gate; it is remembered (`mcp.fixed_port` in the settings store) and opened at the next
launch; the HTTP snippet for Claude Code appears once it is on. Off by default.

**A skill file (M3).** "Show the skill file" prints a `SKILL.md` made from the catalogue (`GET /connections/skill`)
to save under `.claude/skills/wasify-ai/`; it tells Claude Code when and how to use the tools, in addition to the
connection.

**Tools from other apps (the MCP client, ADR-0070, stage C1).** The other direction: the assistant uses outside
MCP servers the person adds under the same Settings page (`packages/ui/src/connections/ExternalServers.tsx`; engine
`services/api/src/wasifyai_api/mcp_client/`; routes `/external`; tables `mcp_servers`, `mcp_client_activity`,
Alembic 0025; tests `services/api/tests/test_mcp_client.py` with the malicious `fake_external_server.py`). An
address (https, or loopback) or a program (the name typed again: it is installing software); a token or variables
in the keychain; trust "asks you before every call" or "is never called"; Test lists the tools with their
annotations; the row shows the host and the bytes sent and received. In the chat, `external_tools` finds a tool and
`call_external` proposes it on a card; the result reaches the model as labelled, cut, untrusted text, and after one
everything that is not a read asks. OAuth is not built (a pasted token works).

**What is not done.** Image previews and `resource_link` results; placing `wasify-mcp` in the app bundle; Windows
and Linux (not compiled); notifications for background approvals (needs a dependency); the "from Codex" label on
library cards. The three real clients were driven end to end on 2026-10-27 (`docs/spikes/mcp-m1-clients.md`), not
yet with files or over the fixed port.
