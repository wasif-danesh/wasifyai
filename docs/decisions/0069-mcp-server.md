# ADR-0069: An MCP server: Claude Code, Codex and OpenCode can use the app

- **Status:** Accepted (2026-10-18, by the owner), together with the new dependencies it names. Amended 2026-10-27 with
  what spike S1 measured (section "Amendment after spike S1" below); the decisions stand, the sentences marked
  *amended* are read with it. Stage M1 has not started.
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

1. **The server is part of the engine,** *(amended below: revisions per client, `stateless_http=True`)* a Streamable HTTP endpoint (`/mcp`) on the engine's loopback port, built
   on the official `mcp` Python SDK 2.x, speaking revision 2026-07-28 and (through the SDK) the earlier ones
   (`2025-11-25`, `2025-06-18`). It is **stateless**, as the new revision is, so a restart of the engine loses
   nothing a client needs. It is **off by default**.
2. **Clients reach it through a small stdio launcher, `wasify-mcp`,** *(amended below: what the launcher must do)* shipped with the app (a Rust binary beside the
   shell). The engine's port changes every launch, so a static client config cannot hold a URL. The launcher reads
   a runtime file that the shell writes when the engine is ready and deletes when it stops (new: `engine.json` in the
   app data folder with the pid, the port and the launcher's connection secret; mode 0600, the same
   operating-system user only), proxies stdio to the endpoint, and, if the app is not running, answers every
   call with one clear tool result: "Open Wasify AI, then try again." (Starting the engine without a window is a
   later step, M3, and a shell decision.) A fixed-port HTTP URL for clients that cannot run a command is an option
   in Settings, off by default, with a token.
3. **Settings > Connections** (desktop) is where it is controlled *(amended below: generated snippets; a connection is a principal, ADR-0092)*. The switch "Let other apps use Wasify AI" creates
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
6. **Files: references out, allowed folders in and out.** *(amended below: measured result limits)* Results are structured content plus `resource_link`
   items (`wasify://creation/<id>`); no bytes in a result, except an optional downscaled image preview of at most
   256 KB when `preview: true` (agents that can see pictures benefit; the 25,000-token limit of Claude Code is
   respected). To get a file, an agent calls `library_export` with a destination **inside a folder the connection
   may write to** (the default is a "Wasify AI exports" folder under the person's Documents; the person can add a
   project folder). To give the app a file (a recording to transcribe), the path must be inside a folder the
   connection may read. Paths are resolved, symbolic links followed and checked, `..` refused. MCP **roots** are
   deprecated and are not used.
7. **Long work is a handle.** *(amended below: progress every 5 s; the tasks extension is dropped from M1)* A long action starts the job, waits up to `wait_seconds` (default 25, at most 50,
   below the 60-second limits of Codex and the two-minute background rule of Claude Code) and returns the result
   or `{status: "running", job_id}`; `job_status`, `job_wait` and `job_cancel` follow it. Progress is sent as
   `notifications/progress` on the request's own stream when the client gave a progress token. Where a client
   supports the **tasks extension** (`io.modelcontextprotocol/tasks`), the same jobs are offered as tasks
   (decided in spike S1 against what the three clients actually do).
8. **A person approves in the app, not through the agent.** *(amended below: `needs_approval` with an id; clients do prompt on their own)* An action that needs approval (ADR-0068 decision 4:
   `destroy`, `needs_consent`, a `make` the person chose to be asked about) returns the **`input_required`**
   result of the multi round-trip pattern when the client supports it, and in every case shows an **approval card
   in the Wasify window** ("Claude Code wants to make a 30-second song. Allow once / Always for this connection
   / Deny"); the tool call waits for the answer for a bounded time and then returns `needs_approval` with what
   to tell the person. Clients are unaffected by their own approval prompts: ours is the one that counts. A call
   made while the app is in the background raises a notification.
9. **New dependencies, to be approved:** *(amended below: eight packages besides `mcp`)* the Python `mcp` SDK 2.x (MIT, official) in the engine, and, for the
   launcher, nothing beyond what the shell already builds with (an HTTP client already present, or
   `ureq`/`reqwest`: checked in M1). The launcher is about 300 lines.
10. **The engine's rules apply unchanged.** Every call runs as the desktop user through the same child runs, so
    safeguards, quotas, moderation, upload hardening and the one-job-at-a-time rule are the app's (ADR-0047). The
    queue is first in, first out with the window's own jobs; a connection has at most one running job and eight
    waiting; the window shows "from Codex" on its jobs and lets the person cancel any of them. What an agent
    made carries `origin` and is findable in My creations like anything else (ADR-0041).
11. **Transport safety.** *(amended below: a Starlette route and an ASGI wrapper; 1 MiB explicit)* The endpoint accepts only `POST` to `/mcp` with `Authorization: Bearer <connection
    secret>`, rejects requests whose `Origin` is present and not the launcher's, checks `Host` against loopback
    (DNS rebinding), limits body size (1 MiB) and rate, and logs every call to an **activity log** (connection,
    action, result status, duration; never prompts or content) that Settings shows. A web page in a browser
    cannot call it: it has no secret and its `Origin` is refused.
12. **A conformance suite.** *(amended below: three revisions, three session shapes)* Tests drive the endpoint with the SDK's client for each protocol revision we claim,
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
   (decision 8) and jobs use handles (decision 7). The spike answers it, per client version. **Answered by S1:** none
   advertises tasks; `input_required` only on Claude Code (2026-07-28); approval waits inside the call and jobs use
   handles in all three.
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

## Amendment after spike S1 (2026-10-27; report: `docs/spikes/mcp-s1.md`, run 2026-10-19)

Measured with `mcp` 2.3.0 against Claude Code 2.1.302, Codex 0.163.0 and OpenCode 1.19.3. Verdict for stage M1: **Go**,
with these corrections. None changes a stage.

1. **Decision 1, revisions.** Only Claude Code speaks 2026-07-28; Codex speaks 2025-06-18 and OpenCode 2025-11-25, and
   both open sessions. The server runs with `stateless_http=True` (an engine restart loses nothing, no session table, no
   replay in the launcher) and accepts that on the legacy revisions it cannot ask the client anything mid-call. If a
   later feature needs that on Codex, switch to stateful and keep the launcher's re-initialize.
2. **Decisions 1 and 11, mounting.** The endpoint is a Starlette `Route` around the SDK's `StreamableHTTPASGIApp`,
   outside FastAPI dependencies; the engine's `/mcp` authentication, rate limit and activity log are an ASGI wrapper of
   ours. `max_request_body_size` is set to 1 MiB explicitly (the SDK default is 4 MiB); the `Origin` and `Host` checks
   come from the SDK when the host is loopback. With ADR-0092 the bearer resolves to a `Principal` of kind `connection`
   with the connection's scopes, through the same `get_principal` as every other credential.
3. **Decision 2, the launcher.** Requirements found by running it: derive the headers from `engine.json` read on the
   open descriptor (mode checked there), stream the response, forward cancellation, answer locally per revision when
   the app is closed, re-initialize on a 404 if ever stateful. About 300 lines of Rust; the Python prototype in the spike
   is the reference. Open problem: with the app closed the launcher can only offer a stub tool list, and the clients
   read the list once (open question 5 below).
4. **Decision 7, long work.** `wait_seconds` default 25, at most 50, stays. Progress is sent **at least every 5 s**
   (it resets Claude Code's idle limit and OpenCode's 60 s; Codex's explicit limit it does not). The **tasks extension is
   dropped from M1**: no client advertises it and the SDK has no server side for it. Job handles work in all three.
5. **Decision 8, approval.** Approval is decided in the Wasify window; the tool waits a bounded time and then returns
   `needs_approval` with an `approval_id` that `job_wait` and `approval_status` follow. `input_required` is optional,
   only on 2026-07-28 with `elicitation` declared; a cancel or decline from it means "not answered". The sentence
   "clients are unaffected by their own approval prompts" is withdrawn: Codex asks or refuses per tool by
   `readOnlyHint`, Claude Code has permission rules and `anthropic/requiresUserInteraction`, so decision 4's
   annotations must be accurate, and the Codex snippet offers `default_tools_approval_mode` as a choice.
6. **Decision 6, results.** Measured limits: Codex cuts text over about 12,000 characters in the middle; Claude Code and
   OpenCode replace text over 50,000 characters with a file path; 500 KB is an error in Claude Code. Results stay under
   about 10 KB, ids and links as written, and are a dict with a sentence in the text content (the SDK wraps a plain
   string as `{"result": ...}`).
7. **Decision 3, copy-for-client.** The snippets are generated from the spike's "Config snippets that worked": the
   HTTP forms need a variable holding the secret, the stdio forms only the launcher path (and `WASIFY_ENGINE_JSON` when
   the default location is not used); `claude mcp add` wants the name before `-e`.
8. **Decision 9, dependencies.** Eight packages enter the lock besides `mcp`, one compiled (`rpds-py`); the hashed
   engine bundle must carry them.

Added open question: **5.** how the tool list refreshes once the app starts (`notifications/tools/list_changed`), since
the clients read it once. Not verified by the spike: the clients' interactive screens, behaviour with a real model,
Windows and Linux, the Rust launcher and its signing, OAuth, and the 1 MiB limit under load.

## Built 2026-10-27 (stage M1, make-only; spike S2 first)

- **Spike S2** (`docs/spikes/mcp-s2.md`): the file rules of decision 6 are `wasifyai_platform_sdk.folders`
  (`AllowedFolders.resolve`), held under 26 hostile paths. The macOS folder prompt is noted, not measured.
- **Decisions 1, 4, 5, 11, 12 and the amendment:** `services/api/src/wasifyai_api/mcp_server/`: the SDK's server
  (`mcp` 2.3.0, `stateless_http=True`, 1 MiB body) behind an ASGI gate that turns a connection secret
  (`wsc_<id>_<random>`, hashed with a salt per row) into the connection, holds its rate (429), logs each call
  without content (`mcp_activity`), and refuses a missing or wrong secret (401; the SDK's own `Origin` 403 and
  `Host` 421 stay). One tool per catalogue action offered to `mcp`, named `domain_verb`, with the action's schema and
  annotations; which tools a connection sees follows its scopes (ADR-0092's groups; a new connection gets `make`,
  `models` and `read`). The conformance tests drive it with the SDK's client on the legacy, auto and 2026-07-28
  modes (`services/api/tests/test_mcp_server.py`).
- **Decisions 7 and 8 as the amendment reads them:** a long action becomes a job after 25 s with progress at least
  every 5 s; an action that needs the person's yes is parked on the **approval desk**, the window gets an event on
  `GET /desktop/events` and shows a card (Allow once / Deny; never "always"), the answer runs the action with the
  approval the executor recorded (as a job when long), and the agent follows it with `approval_status` and `job_wait`.
  A call that is not answered within 25 s returns `needs_approval` with the id, as the amendment says.
- **Decision 2:** `wasify-mcp` is a second binary of the shell's crate (`src/bin/wasify_mcp.rs`, about 330 lines of
  Rust): reads `engine.json` on every request with the checks on the open descriptor (`O_NOFOLLOW`, owner, mode
  0600, the folder not writable by others, loopback host, live pid), derives the three headers of 2026-07-28,
  carries a legacy session and re-initializes it after an engine restart, streams server-sent events to stdout,
  closes the request on `notifications/cancelled`, and answers `initialize`, `server/discover`, `tools/list` and
  `tools/call` itself when the app is closed ("Open Wasify AI, then restart your agent"). Tested through the SDK's
  stdio client on both eras, with the app closed, and with a readable-by-others, stale and non-loopback file.
  `engine.json` is written by the **engine**, not the shell: the switch creates a launcher connection whose secret
  lives in the secret store (ADR-0092), and each launch rewrites the file with the new port and pid.
- **Decision 3:** Settings > Other apps (`packages/ui/src/connections/`): the switch, the generated snippets for the
  three clients (the launcher's path comes from the shell, `WASIFYAI_MCP_LAUNCHER`), the connections with scopes in
  words and the approval setting, a new secret shown once, revoke.
- **Not built in M1:** the `library`, `notebooks` and `voices` groups are choosable but `library_export` and file
  inputs (decision 6's folders) wait for M2; the opt-in fixed HTTP port; `input_required` as a courtesy; the
  launcher is built beside the shell but not yet placed in the bundle (release work, Q2); Windows and Linux not run;
  the `notifications/tools/list_changed` refresh after the app starts (open question 5) is still open.
- **The three real clients, driven 2026-10-27** (`docs/spikes/mcp-m1-clients.md`): Claude Code 2.1.302, Codex 0.163.0
  and OpenCode 1.19.3 through `wasify-mcp` against a desktop engine, with S1's scripted model: the tour (status,
  models, a picture approved in the window, the job followed), a late approval (`needs_approval`, then
  `approval_status`, then the job) and the app closed, all three clients, all three scenarios. The run changed two
  things: the launcher's path is read from `WASIFYAI_MCP_LAUNCHER` (the name the shell sets), and every result's
  sentence carries its `job_id` and `approval_id`, because OpenCode hands its model the text alone.
