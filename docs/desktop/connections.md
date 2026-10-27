# Other apps (the MCP server) on the desktop

Part of [the desktop profile](../desktop-profile.md). ADR-0069, built 2026-10-27 (stage M1).

Coding agents (Claude Code, Codex, OpenCode) use the app as a tool. The engine serves `POST /mcp` on its loopback
port; the stdio launcher `wasify-mcp` (built beside the shell) is what the agents run.

| Piece | Where |
|---|---|
| Engine | `services/api/src/wasifyai_api/mcp_server/`: `connections.py` (store, service, principals), `tools.py` (one tool per catalogue action offered to `mcp`), `calls.py` (the executor runs it; jobs, progress, approvals), `approvals.py` (the desk), `endpoint.py` (the SDK's server and the gate), `routes.py` (Settings and the window's answer), `runtime_file.py` (`engine.json`, the switch) |
| Window events | `GET /desktop/events` (server-sent; `approval` when an agent waits), `wasifyai_api/desktop_events.py` |
| Launcher | `apps/desktop/src-tauri/src/bin/wasify_mcp.rs`; `cargo build --bin wasify-mcp`; the shell passes its path as `WASIFYAI_MCP_LAUNCHER` |
| Settings | `packages/ui/src/connections/ConnectionsSettings.tsx` in Settings > Other apps; the cards `ApprovalCards.tsx` in the window |
| Tables | `mcp_connections`, `mcp_activity` (SQLite on first use; Alembic 0023) |
| Tests | `services/api/tests/test_mcp_server.py` (the SDK's client on three protocol modes, the gate, approvals, the launcher) |

**How it is used.** Settings > Other apps > "Let other apps use Wasify AI" makes the launcher's connection, keeps its
secret in the keychain (`mcp.launcher.secret`) and writes `<app data>/engine.json` (0600: pid, port, secret). The
page then shows the command to paste for each client. The agent's tool list is the catalogue filtered by the
connection's scopes; a `make` shows a card in the window unless the connection's setting says otherwise; deleting
and consent always ask. A call that waits more than 25 s answers with a `job_id` or an `approval_id` to follow.

**What is not done.** Exporting files and giving the app a file (M2, with the folders of spike S2); the fixed HTTP
port; placing `wasify-mcp` in the app bundle; Windows and Linux; the three real clients driven end to end.
