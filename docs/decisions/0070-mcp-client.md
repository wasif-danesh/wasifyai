# ADR-0070: An MCP client: the assistant can use other people's MCP servers

- **Status:** Accepted (2026-10-18, by the owner), together with the new dependencies it names.
- **Date:** 2026-10-18
- **Depends on:** ADR-0068 (action catalogue, approvals), ADR-0057 (the assistant and its tool loop), ADR-0047
  (safeguards), ADR-0056 (one engine), ADR-0061 (how outside code enters).
- **Related:** ADR-0069 (the server). The two are independent: the client does not expose what it connects to.
- **Plan:** `docs/phase4-agent-plan.md`, stages C1 to C3.

## Context

The owner wants the app to reach **remote third-party MCP servers** and use them, as Claude Desktop, Claude Code
and Codex do: search the web, read a repository, query a database, post to a chat. For the assistant this adds
hands the product does not have.

It also changes what the product is. The app is local first: models, files and creations stay on the computer.
An MCP server is **someone else's code or someone else's service**, and the assistant will send it text that may
contain the person's private words and read back text that **neither the person nor we wrote**. Three risks that
the rest of the app does not have:

1. **Code execution.** A stdio server is a program the app starts as the user. Adding one is installing software.
2. **Data leaving.** A remote server receives whatever the model puts in the arguments.
3. **Prompt injection.** What a server returns (a web page, an issue, an email) can contain instructions aimed at
   the model ("now call the delete tool"). A model cannot reliably tell data from instructions.

The protocol facts (revision 2026-07-28, read 2026-10-18): stateless Streamable HTTP, `server/discover`, tasks as
an extension, **multi round-trip requests** for anything a server needs from the person (elicitation arrives as
`input_required`), Roots, Sampling and Logging **deprecated**, HTTP+SSE **deprecated**, OAuth 2.1 with **Client
ID Metadata Documents** preferred over Dynamic Client Registration, results from `tools/list` carry `ttlMs` and
`cacheScope`. Tool **annotations** (read-only, destructive, open-world) are hints, and untrusted unless the server
is. The official Python SDK `mcp` 2.x is a client as well as a server.

The model rule from ADR-0057 and the evaluation (11 of 11 with Qwen3 4B on four tools) also matter: a **small
local model degrades as the number of tools grows**, and a third-party server may bring forty tools.

## Decision

1. **The client lives in the engine** (`wasifyai_api/mcp_client/`), on the `mcp` SDK 2.x, supporting revision
   2026-07-28 and falling back to `2025-11-25` for older servers. Transports: **Streamable HTTP** and **stdio**.
   Not supported: HTTP+SSE (deprecated; a server that only speaks it is refused with that reason), WebSocket.
2. **Connections are added by the person, in Settings > Connections > "Tools from other apps"** and nowhere else.
   The assistant cannot add, edit or enable one, and a tool result cannot ask it to. Each connection records: a
   name, the transport and address or command, the environment it needs (names only; values go to the secret
   store), a **trust level** (decision 4), an optional list of allowed tools, and who added it and when. Importing
   a server definition from Claude Code's `.mcp.json`, Claude Desktop's or Codex's `config.toml` is offered as a
   convenience: the person sees each definition and confirms it.
3. **Adding a stdio server is installing software, and says so.** The dialog shows the full command, the folder
   it runs in and the environment it gets, and asks the person to type the server's name to confirm. The
   process runs as the user with a **minimal environment** (no engine secrets, no inherited tokens; only the
   variables the person listed), in a working folder under the app's data folder, is stopped when idle for ten
   minutes and when the app quits, and its output is size-limited and logged. We do not claim a sandbox: on macOS a
   sandbox profile is a later hardening (M3 below). A curated list of servers is **not** offered in v1; the app
   does not recommend third-party code it has not reviewed.
4. **Trust has three levels, per connection:** `Ask` (default): every call that is not `read` asks first;
   `Trusted read-only`: the person has marked this server as one whose `readOnlyHint` they believe, so tools it
   annotates read-only run without asking; `Blocked`: kept in the list, never called. Annotations are never
   honoured on an `Ask` server (the spec says they are untrusted by default). A tool with no annotations is
   treated as `make` with `leaves_device`. The assistant's own approval settings (ADR-0068 decision 4) apply on
   top, never below the floor.
5. **The taint rule (injection).** Once text from an external server is in the conversation, **every action that
   is not `read` asks the person for approval in the window for the rest of that turn**, even if it was set to
   run without asking and even if it is one of our own actions (`library_delete`, `speech_speak` with
   `leaves_device`). The approval card shows **where the request came from** ("after reading a result from
   `github`"). Our own `needs_consent` and `destroy` floors are unchanged. External content is passed to the model
   inside a labelled block, truncated to 20,000 characters per result, with control characters stripped; images
   from servers are shown only as small thumbnails and never fetched from a URL a server names; links in results
   are not followed by the app.
6. **Egress is visible.** Each connection card shows the host it talks to, the tools it exposes with their
   annotations, and a counter of calls and bytes sent. Remote servers must be `https`, except loopback; the
   client refuses private and link-local addresses for a remote host unless the person added exactly that address
   (SSRF), does not follow a redirect to another host with credentials, validates certificates, and pins the host
   a credential was issued for (the spec's rule that credentials are bound to their authorization server).
7. **Secrets** (API keys, OAuth tokens) are stored in the **operating system's keychain**, never in the SQLite
   file, a log or an environment dump. The engine reads them through one small module so the mechanism can be
   swapped. OAuth 2.1 with PKCE uses the person's browser, a loopback callback, **Client ID Metadata Documents**
   where the server supports them and Dynamic Client Registration only as a fallback. Needs a dependency: Python
   `keyring` in the engine, or the shell storing secrets and handing them over on the engine's stdin; decided
   in spike S4.
8. **How the assistant sees remote tools.** Not one model tool per remote tool. The assistant's meta-tools
   (ADR-0071) include `external_tools(query)`, which searches the connected servers' tool descriptions (with the
   local embedder) and returns at most five, and `call_external(connection, tool, arguments)`, which validates
   `arguments` against the tool's schema, applies decisions 4 and 5, and runs it. The model's tool list stays the
   same size whether zero or forty remote tools exist. A conversation can pin a connection to always list its
   tools when the person wants that.
9. **Reliability limits:** connect lazily on first use and cache `tools/list` for its `ttlMs`; per-call timeout
   (60 s default, the person can change it per connection) and a cancel button; results over a size limit are
   refused; at most four calls in flight per connection; failures are reported in words ("`github` did not answer
   in 60 seconds") and never retried silently for non-`read` calls; a connection that fails three times in a row
   is marked unhealthy and left alone until the person tests it.
10. **What the client supports of the protocol:** tools (yes); **resources** (the person can attach a server's
    resource to a message; the assistant may read one it was given); **prompts** (listed, usable by the person as
    templates; later); **elicitation** as `input_required` (shown as a form card in the window; the assistant
    never answers for the person); **tasks** (used when the server offers them for slow tools); sampling, roots and
    logging (not supported; deprecated).
11. **Records.** Each call writes an activity entry (connection, tool, status, duration, bytes; arguments and
    results only if the person turns on "keep the content" for debugging, per connection) and a usage event.
    Deleting a connection deletes its secrets and entries.
12. **Safeguards (ADR-0047)** apply to the model's own text as before; they cannot judge a remote server's results,
    so decisions 4 to 6 are the protection, and they are on whether or not the safeguards switch is on.

## Consequences

- The assistant can do much more, and the product stops being only local. The person decides per connection, and
  sees what leaves.
- The taint rule makes agentic chains slower (more approvals) after a remote read. That is the intended price.
  It is relaxed only by the person trusting a server read-only **and** the follow-up action being `read`.
- A new SQLite table (`mcp_servers`), a Settings area, an approval card variant and about 1,500 lines of engine
  code. Tests need a fake MCP server (the SDK provides the pieces) that can also act maliciously: oversized
  results, instructions in results, slow, redirecting, lying annotations.
- The small-model problem is handled by decision 8 and by extending the assistant's evaluation (ADR-0071) with
  external-tool cases; if Qwen3 4B cannot choose among remote tools reliably, remote tools are offered only with a
  hosted or larger model, and the Settings page says so.

## Alternatives considered

- **Do not build it; rely on the MCP server (ADR-0069) and let people use Claude Code for third-party tools.**
  Valid, and cheaper. Kept as the fallback if the evaluation shows local models cannot use remote tools safely.
  The owner asked for the client, so it is the plan, staged last.
- **A proxy: re-export remote tools through our MCP server.** A confused-deputy risk (an agent reaches a service
  through our app's credentials). Rejected; no passthrough.
- **A curated registry or a store of servers.** A review burden and a liability. Rejected for v1.
- **Run stdio servers in a container or VM.** Strongest isolation, but a large runtime on a Mac app and slow
  start. A candidate for M3 hardening, not v1.
- **Honour annotations from every server.** The spec says not to. Rejected.

## Open questions

1. Keychain mechanism (decision 7) and whether the Rust shell should own secrets.
2. A macOS sandbox profile for stdio servers: feasible with `sandbox-exec` (deprecated by Apple) or an app
   sandbox entitlement (which affects the whole app). Needs a spike before it is promised.
3. Which model tier is good enough to pick and call remote tools: an evaluation, not an opinion (stage C2).
4. Whether the web deployment ever gets a client: it would need per-tenant isolation and egress control; out of
   scope.

## Not in this version

Servers added by the assistant or by any text; remote servers that need a browser session the app cannot hold; a
marketplace; sampling (servers asking our model to think for them); running servers on a schedule; sharing
connections between people; the web deployment.

## Built 2026-10-27 (stage C1: the client, read-only trust levels)

- **Decision 1:** `services/api/src/wasifyai_api/mcp_client/` on the SDK's client (`mcp` 2.3.0): Streamable HTTP
  and stdio. One session per server, held by a task of its own (the SDK's transport must be left by the task that
  entered it); calls come from the assistant's tasks. A session idle for ten minutes is closed, and every session
  when the engine stops. HTTP+SSE and WebSocket are not offered.
- **Decision 2:** Settings > Other apps > "Tools from other apps" (`packages/ui/src/connections/ExternalServers.tsx`,
  routes `/external`): name, kind (an address, or a program), address or command with arguments, the variables a
  program needs (names on the row, values in the secret store), a token for an address (the secret store), trust,
  Test, Remove. The routes take the person's own token only (`require_person`): a connection or a key is refused,
  and the assistant has no tool that adds one. Import from other clients' configs waits for C3.
- **Decision 3:** the form says that adding a program is installing software and asks for the name typed again
  (the engine refuses without it); the program runs as the user with the variables listed (over the SDK's safe
  subset: `PATH`, `HOME` and the like), in `<app data>/mcp-servers/<id>`, and is stopped when idle or when the app
  quits. Its output is not yet size-limited or logged; no sandbox (open question 2 stands).
- **Decision 4:** trust `ask` and `blocked`. `external.call` is a `make` that `leaves_device`, so on an `ask` server
  every call shows the chat's card, whatever the tool's annotations say; a `blocked` server lists no tools and is
  never called. `trusted_read_only` arrives with C2.
- **Decision 5, the part that is in C1:** a result is text only, control characters stripped, cut at 20,000
  characters, handed to the model under a label that names the server and says it is untrusted; an image is
  named with its size and not shown, a `resource_link` is named and never followed, an embedded resource is not
  read. The taint rule itself (every action that is not a read asks for the rest of the turn) already held for the
  web and now counts `call_external` too; the provenance on the card ("after reading a result from github") is C2.
- **Decision 6:** `https` only except loopback, no credentials in the address, a name that resolves to a private
  or link-local address refused unless the person typed that address (checked when added and again when
  connecting), certificates verified, and a redirect to another host not followed (the SDK follows only within
  the origin). The row shows the host, the counters of calls and bytes sent and received, and the tools with their
  annotations after a Test.
- **Decision 7:** values go to the secret store of ADR-0092 (`mcp.client.<id>.token`, `mcp.client.<id>.env.<name>`),
  the keychain on the desktop; removing a server removes them. **OAuth 2.1 is not built:** a server that takes a
  bearer token works with the token pasted in Settings; the browser flow (PKCE, a loopback callback, CIMD) is
  left for a later stage, because it cannot be tested here without an authorization server to run against.
- **Decision 8:** the assistant has `external_tools(query)` (at most five matches, by the words of the query against
  tool names and descriptions, not yet the embedder) and `call_external(connection, tool, arguments)`, which
  proposes the one catalogue action `external.call`: arguments validated against the tool's input schema
  (`jsonschema`, which `mcp` brings), the card, the executor's audit entry and usage event. The model's tool list
  grows by two whatever is connected. The prompt tells the model what outside text is.
- **Decision 9:** a per-server timeout (5 to 600 s, default 60) the person sets, at most four calls in flight per
  server, three failures in a row mark the server unhealthy until Test clears it, `tools/list` cached for its
  `ttlMs` and at least 30 s. A cancel button and the refusal of oversized results before they are read are not
  built: a result is cut after it arrives.
- **Decision 11:** every call writes an activity entry (server, tool, status, duration, bytes each way; the
  arguments and the first 4,000 characters of the result only when "keep the content" is on for that server) and,
  through the executor, a usage event. The web deployment gets no client (decision 10 of the plan; the engine
  creates it on the desktop only).
- **Tested** (`services/api/tests/test_mcp_client.py`) against a malicious fake server (`fake_external_server.py`:
  a 100,000-character result, hidden instructions with control characters, a tool whose annotation lies, a slow
  tool, an image, a link, a failing tool) over stdio and over HTTP on loopback with a token; a redirect to another
  host; the address rules; the secret store; the SQL store; the routes on the desktop engine; the assistant's two
  meta-tools at the tool level (a card first, the labelled text once run); the prompt and the taint. Not driven
  with a real language model or a real third-party server yet (C2's evaluation).
- **Not built in C1:** OAuth; resources, prompts, elicitation and tasks (C3); import from other clients' configs
  (C3); `trusted_read_only`, the provenance on the card, the stdio output limit and log (C2); the embedder in
  `external_tools`; a cancel button.

## Built 2026-10-27 (stage C2: the taint's provenance, trusted read-only, the evaluation)

- **Decision 4, the third level:** `trusted_read_only` ("runs the tools it says only read, without asking"). A tool
  whose `readOnlyHint` is true on such a server runs with no card, taint or not; on an `ask` server the hint still
  decides nothing. The check is the host's (`external_trusted`), read when the assistant is about to call.
- **Decision 5, the provenance:** the card carries `provenance` ("after reading a result from github", "after
  reading the web", "after reading a file the person attached"), kept with the turn so a resumed card still says it;
  the window shows "Asking because this came after reading a result from github". The source is the last outside
  text read.
- **Decision 3, the output:** a program's stderr goes to `stderr.log` under its folder, kept to the last million
  characters, shown in Settings ("Its output").
- **Decision 8, what the model is told:** the prompt names the connected servers (those not blocked or unhealthy),
  and `external_tools` returns each tool's signature. Both came out of the evaluation: without the names the model
  said it could not reach Slack; without the signatures it could not form the arguments.
- **The evaluation** (`docs/spikes/assistant-c2.md`): on Qwen3 8B, the right outside tool in 8 of 10 asks with a
  catalogue of 5 and of 40 alike, no wrong tool, no unfitting arguments; the app's own actions and guides unchanged
  with 40 tools connected; the outside result that orders a delete obeyed by nothing. **Outside tools are offered to
  local models.** Qwen3 4B and a hosted tier were not run.
- **Tested:** trusted read-only at the client and the policy (`test_mcp_client.py`), the provenance and the taint
  source, the log; the runner's catalogue and judge (`test_eval_runner.py`).
- **Not built in C2:** a cancel button for a running outside call; the embedder in `external_tools`; a sandbox for
  programs (open question 2).

## Built 2026-10-27 (stage C3: reach)

- **Decision 10, resources:** the box has a "Servers" button (`packages/ui/src/chat/servers-panel.tsx`): each
  connected server's resources with Attach. Attaching reads the resource on the engine
  (`POST /external/{id}/resources/attach`), cleans and cuts it like an attached document (200,000 characters) and
  keeps it as the same upload record an attached file gets, so the chat gives it to the model the same way and the
  taint rule counts it as a file. A binary resource is refused: only text reaches the model.
- **Decision 10, prompts:** the same panel lists each server's prompts with Use; a prompt with arguments asks for
  them first, then its text is put in the box for the person to send or change (`POST /external/{id}/prompts/get`).
  Nothing is sent by the panel.
- **Decision 10, elicitation:** a server's question mid-call (`elicitation/create` in form mode, which on 2026-07-28
  rides the `input_required` round trip) becomes a card in the window (`ElicitationCards.tsx`): the message and a
  form drawn from the requested schema (text, number, yes/no, a choice), Send or Decline. The engine raises an
  `elicitation` event on `GET /desktop/events`, the card reads the pending list (`GET /external/forms`) and answers
  (`POST /external/forms/{id}`); the values are checked against the schema; a form nobody answers within five
  minutes is a cancel. The assistant never answers for the person. The per-round server timeout still holds; the
  call itself may wait for the person.
- **Decision 2, import:** Settings > Tools from other apps > "Already set up elsewhere?": the definitions in Claude
  Code's `.mcp.json` (a project folder) or `~/.claude.json`, Claude Desktop's `claude_desktop_config.json` and
  Codex's `config.toml` are listed with their command or address and the names of their variables, never the
  values; each is added on its own click, as the file has it, its variables and bearer token going to the secret
  store on the engine (`mcp_client/imports.py`). An HTTP+SSE definition is shown with why it cannot be added.
- **Tested** against the fake server (a text and a binary resource, a prompt with arguments, a tool that asks for a
  name and greets by it: accept, decline, nobody answers) at the client and through the routes, the three config
  formats, and the window side (the panel, the form card's fields and values, the import rows).
- **Not built:** the tasks extension (the SDK's client claims none; a slow outside tool is bounded by the server's
  timeout); a macOS sandbox for programs (spike S5 was not run); OAuth (still a pasted token); resource templates
  and a server's `prompts/list_changed` refresh.
