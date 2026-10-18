# ADR-0069: An MCP server: Claude Code, Codex and OpenCode can use the app

- **Status:** Accepted (2026-10-18, by the owner), together with the new dependencies it names.
- **Date:** 2026-10-18
- **Depends on:** ADR-0068 (action catalogue), ADR-0056 (one engine, two shells; one memory slot), ADR-0047
  (safeguards), ADR-0066 (voice product; consent), ADR-0041 (search), ADR-0061 (how outside code enters).
- **Plan:** `docs/phase4-agent-plan.md`, stages M1 to M3.

## Context

The owner wants the product's features and skills usable from coding agents: **Claude Code, Codex and OpenCode**.
All three are MCP clients. What each does, read from their documentation on 2026-10-18 (re-read in spike S1,
because these change):

| Client | How a server is added | Limits that shape our design |
|---|---|---|
| Claude Code | `claude mcp add --transport http <name> <url>` or `... -- <command>` for stdio; scopes local, project (`.mcp.json`, shared in git), user; OAuth for HTTP servers; headers helper | A tool result over 10,000 tokens warns and is cut at 25,000 by default (`MAX_MCP_OUTPUT_TOKENS`), saved to a file; a call over two minutes moves to a background task; HTTP responses over 16 MiB fail |
| Codex | `[mcp_servers.<name>]` in `~/.codex/config.toml` or a trusted project's `.codex/config.toml`; `command`/`args`/`env` for stdio, `url` with `bearer_token_env_var` or OAuth for streamable HTTP; per-tool approval modes and allow/deny lists | `tool_timeout_sec` defaults to 60, `startup_timeout_sec` to 10 |
| OpenCode | `"mcp"` in `opencode.json`: `"type": "local"` with a `command` array, or `"remote"` with `url`, `headers`, `oauth`; tools are prefixed with the server name | tool discovery timeout 5,000 ms by default; every tool definition costs context, so people turn servers off |

The protocol itself moved in July 2026. The revision **2026-07-28** (changelog read 2026-10-18) makes MCP
stateless: no `initialize` handshake and no session id on Streamable HTTP; every request carries its protocol
version and client capabilities; servers must answer `server/discover`. Tasks left the core for an official
extension. Server-to-client requests (elicitation, sampling, roots) are replaced by **multi round-trip requests**
(a result of `input_required` that the client answers by retrying). Roots, sampling and logging are deprecated,
HTTP+SSE is deprecated, and Dynamic Client Registration is deprecated in favour of Client ID Metadata Documents.
The Python SDK `mcp` 2.x (MIT, 2.3.0 on 2026-10-02) implements the new revision and serves the older ones.

Facts about our engine that decide the shape:

- The engine is a **per-launch child of the desktop shell**: random loopback port, per-launch secret, exits when
  the shell exits (`docs/desktop-profile.md`, "How the shell and the engine meet"). Nothing listens on the network.
- **One memory slot** (ADR-0056): chat, image, audio and video models take turns. An agent and the window share
  it.
- The window and an agent are the **same person** on the same computer, but an agent is a program with a model
  behind it that can be told to do harmful things by text it reads.

## Decision

1. **The server is part of the engine,** a Streamable HTTP endpoint (`/mcp`) on the engine's loopback port, built
   on the official `mcp` Python SDK 2.x, speaking revision 2026-07-28 and (through the SDK) the earlier ones
   (`2025-11-25`, `2025-06-18`). It is **stateless**, as the new revision is, so a restart of the engine loses
   nothing a client needs. It is **off by default**.
2. **Clients reach it through a small stdio launcher, `wasify-mcp`,** shipped with the app (a Rust binary beside the
   shell). The engine's port changes every launch, so a static client config cannot hold a URL. The launcher reads
   a runtime file that the shell writes when the engine is ready and deletes when it stops (new: `engine.json` in the
   app data folder with the pid, the port and the launcher's connection secret; mode 0600, the same
   operating-system user only), proxies stdio to the endpoint, and, if the app is not running, answers every
   call with one clear tool result: "Open Wasify AI, then try again." (Starting the engine without a window is a
   later step, M3, and a shell decision.) A fixed-port HTTP URL for clients that cannot run a command is an option
   in Settings, off by default, with a token.
3. **Settings > Connections** (desktop) is where it is controlled. The switch "Let other apps use Wasify AI" creates
   a first **connection** for the launcher; the person can add more (a name, for example "Codex on my laptop").
   Each connection has: its secret (shown once, stored hashed), a **scope** (decision 5), an **approval setting**
   (ADR-0068 decision 4, with the same floor), the **folders** it may read from and write to (decision 6), a rate
   limit, a last-used time, and a revoke button. Settings shows the exact command to paste for each client
   ("Copy for Claude Code", "Copy for Codex", "Copy for OpenCode"), generated, never typed by hand.
4. **Tools are catalogue actions** (ADR-0068) whose `surfaces` include `mcp`, filtered by the connection's scope.
   Names are `domain_verb` (`image_generate`, `speech_speak`, `speech_transcribe`, `music_generate`,
   `audio_separate`, `library_search`, `notebook_ask`, `job_wait`), no product prefix (clients add the server
   name). Each carries MCP **annotations** from the catalogue: `readOnlyHint` for `read`, `destructiveHint` for
   `destroy`, `idempotentHint` where true, `openWorldHint` for `leaves_device`. Annotations are hints a client
   may not trust; **the engine enforces** the effect, not the client.
5. **Scope defaults protect private data.** Tool groups: `make` (image, video, speech, music, audio tools, dub,
   audiobook), `library` (search, list, get, export: `private`), `notebooks` (`private`), `voices` (design, clone:
   `needs_consent`), `models` (status only), `admin` (delete, rename). A new connection gets **`make` and
   `models`**. `library` and `notebooks` are opt-in with a warning that what an agent reads goes to its model
   provider ("Claude Code sends this to Anthropic"). `voices`, `lipsync` and `destroy` are off until chosen.
6. **Files: references out, allowed folders in and out.** Results are structured content plus `resource_link`
   items (`wasify://creation/<id>`); no bytes in a result, except an optional downscaled image preview of at most
   256 KB when `preview: true` (agents that can see pictures benefit; the 25,000-token limit of Claude Code is
   respected). To get a file, an agent calls `library_export` with a destination **inside a folder the connection
   may write to** (the default is a "Wasify AI exports" folder under the person's Documents; the person can add a
   project folder). To give the app a file (a recording to transcribe), the path must be inside a folder the
   connection may read. Paths are resolved, symbolic links followed and checked, `..` refused. MCP **roots** are
   deprecated and are not used.
7. **Long work is a handle.** A long action starts the job, waits up to `wait_seconds` (default 25, at most 50,
   below the 60-second limits of Codex and the two-minute background rule of Claude Code) and returns the result
   or `{status: "running", job_id}`; `job_status`, `job_wait` and `job_cancel` follow it. Progress is sent as
   `notifications/progress` on the request's own stream when the client gave a progress token. Where a client
   supports the **tasks extension** (`io.modelcontextprotocol/tasks`), the same jobs are offered as tasks
   (decided in spike S1 against what the three clients actually do).
8. **A person approves in the app, not through the agent.** An action that needs approval (ADR-0068 decision 4:
   `destroy`, `needs_consent`, a `make` the person chose to be asked about) returns the **`input_required`**
   result of the multi round-trip pattern when the client supports it, and in every case shows an **approval card
   in the Wasify window** ("Claude Code wants to make a 30-second song. Allow once / Always for this connection
   / Deny"); the tool call waits for the answer for a bounded time and then returns `needs_approval` with what
   to tell the person. Clients are unaffected by their own approval prompts: ours is the one that counts. A call
   made while the app is in the background raises a notification.
9. **New dependencies, to be approved:** the Python `mcp` SDK 2.x (MIT, official) in the engine, and, for the
   launcher, nothing beyond what the shell already builds with (an HTTP client already present, or
   `ureq`/`reqwest`: checked in M1). The launcher is about 300 lines.
10. **The engine's rules apply unchanged.** Every call runs as the desktop user through the same child runs, so
    safeguards, quotas, moderation, upload hardening and the one-job-at-a-time rule are the app's (ADR-0047). The
    queue is first in, first out with the window's own jobs; a connection has at most one running job and eight
    waiting; the window shows "from Codex" on its jobs and lets the person cancel any of them. What an agent
    made carries `origin` and is findable in My creations like anything else (ADR-0041).
11. **Transport safety.** The endpoint accepts only `POST` to `/mcp` with `Authorization: Bearer <connection
    secret>`, rejects requests whose `Origin` is present and not the launcher's, checks `Host` against loopback
    (DNS rebinding), limits body size (1 MiB) and rate, and logs every call to an **activity log** (connection,
    action, result status, duration; never prompts or content) that Settings shows. A web page in a browser
    cannot call it: it has no secret and its `Origin` is refused.
12. **A conformance suite.** Tests drive the endpoint with the SDK's client for each protocol revision we claim,
    plus a recorded session from each of the three clients, replayed in CI. Manual checks against the three real
    clients are a release gate (plan, M2).

## Consequences

- The app becomes a tool for agents: what Claude Code makes can land in the library, and the person can see and
  stop it. The cost is a security surface: a connection secret, a loopback endpoint, an approval queue and an
  activity log, all new.
- Two things leave the computer through an agent and the person must be told in plain words: the **content of
  tool results** (to the agent's model provider) and **paths** the agent reads. The default scope keeps private
  data out until chosen.
- The launcher has to be signed and notarised with the app (macOS), and its path is stable inside the app bundle.
  It changes the installer and the updater slightly (ADR-0061's import of the shell's installer driver).
- The catalogue (ADR-0068) must exist first; the server is a thin layer on it.
- With the app closed, nothing works. That is the right default for a first version and it is stated in the tool
  result; a background mode is a separate decision.

## Alternatives considered

- **A stdio server that starts its own engine per client.** Two engines would fight over the single memory slot
  and over one SQLite database. Rejected.
- **Expose the engine's HTTP routes with an OpenAPI-to-MCP converter.** See ADR-0068: no safety classes, wrong
  granularity, leaks internals. Rejected.
- **A fixed port for everyone.** A port other software already uses, and every client config breaks when it
  does. Kept only as an opt-in.
- **Run a server in the Rust shell.** The logic is in Python; a second implementation would drift. Rejected.
- **A remote MCP server on the web deployment first.** It needs OAuth 2.1 with Client ID Metadata Documents, per
  tenant isolation and abuse limits. Desktop first (owner's priority); the catalogue makes it possible later.
- **Skills (Claude Code's `SKILL.md`) instead of MCP.** A skill is instructions, not a connection to a running
  app. A generated skill file that tells an agent how to use our tools well is cheap and useful **in addition**
  (M3), but it does not replace the server, and Codex and OpenCode have their own conventions.

## Open questions

1. Does each of the three clients support `input_required` and tasks today? If not, approval waits inside the call
   (decision 8) and jobs use handles (decision 7). The spike answers it, per client version.
2. Where the launcher lives on Windows and Linux (the desktop is Mac first); the runtime file's location follows
   the app data folder.
3. Whether an agent may **start** the app. Wanted by users ("the agent opens it"), but it starts a window and loads
   models without a person present; M3 decides with the shell's single-instance logic.
4. Claude Code's plugin and `.mcp.json` sharing: a team could commit a config that points at the launcher path.
   Paths differ per machine; a documented environment variable (`WASIFY_MCP`) may be needed.

## Not in this version

Windows and Linux launchers (after the Mac); a remote or multi-user MCP server; exposing the assistant itself as a
tool (agents are assistants already); MCP **prompts** as slash commands (a generated list of useful prompts is M3);
sampling, roots and logging (deprecated in the revision we build against); a public marketplace listing.
