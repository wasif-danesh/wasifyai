# Spike S1: the `mcp` SDK 2.x in the engine, and Claude Code, Codex and OpenCode as clients

Date: 2026-10-19. Machine: MacBook Pro, Apple M5 Pro, macOS (Darwin 27.0.0), Python 3.13.16 in the scratch virtualenv.
Plan: `docs/phase4-agent-plan.md`, stage 0, row S1. Decisions tested: ADR-0069 (MCP server) and, through it, ADR-0068.
Nothing here changed an ADR; where a finding contradicts one, it is listed under "What this forces on ADR-0069".

Scratch folder (outside the repo, kept): `~/Projects/wasifyai-spikes/s1/` (toy server `toy_server.py`, launcher
prototype `launcher.py`, scripted fake model `fake_model.py`, run scripts, and every log under `logs/` and `state/`). Every
number below comes from a file there. Anything not run is marked **not verified**. No real model and no login was used:
each client was pointed at a fake model endpoint I wrote (it emits scripted tool calls and logs every tool result it is
sent back), each in its own config home. The owner's real Claude Code, Codex and OpenCode configuration was not touched.

Versions measured: `mcp` **2.3.0** (with `mcp-types` 2.3.0), FastAPI 0.142.2, Starlette 1.7.0, uvicorn 0.54.0 (the engine's
locked versions), Claude Code **2.1.302**, Codex CLI **0.163.0**, OpenCode **1.19.3**.

## Result in one screen

| Question | Answer |
|---|---|
| SDK serves 2026-07-28 and older from a route in a FastAPI app | **Yes.** 2026-07-28 (stateless, `server/discover`), and by `initialize`: 2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05. All five answered `tools/call quick` in a FastAPI 0.142.2 / Starlette 1.7.0 app with the engine's CORS and request-id middleware |
| Which revision each client negotiates | Claude Code **2026-07-28** (HTTP and stdio). Codex **2025-06-18**. OpenCode **2025-11-25**. **The two others are not on the new revision**, and both open sessions (`Mcp-Session-Id`, a GET stream, DELETE) |
| Works over stdio through a launcher | **Yes, all three**, with a Python prototype of `wasify-mcp` reading an `engine.json`. But it cannot be a byte pipe (see "The launcher") |
| Works over HTTP with a static bearer from config | **Yes, all three** (env-variable reference in each config) |
| `input_required` | **Claude Code only** (on 2026-07-28). Round trip verified end to end. Codex and OpenCode never see it |
| Tasks extension (`io.modelcontextprotocol/tasks`) | **No client advertises it** (capabilities captured). The SDK has types and an extension hook but no tasks server |
| Job-handle pattern (`job_start`, then `job_status` with a bounded wait) | **Works in all three** (70 s job, 45 s waits) |
| Tool-call timeout | Very different, see the table. **Codex did not enforce its documented 60 s** (a 250 s silent call completed); OpenCode enforces 60 s unless progress arrives or `timeout` is set; Claude Code has an idle limit of 300 s |
| Output size | Differences are large (50 KB passes in two, is cut to a file in one; 500 KB is cut in all three). Details below |
| Go or no-go for M1 | **GO**, with the changes listed at the end. None of them is a reason to change the plan's shape |

## 1. The SDK in the engine

### Version, size, licence, what it adds

`mcp==2.3.0` (PyPI, wheel 369 KB, MIT, requires Python 3.10 or newer). `uv pip install mcp==2.3.0 fastapi==0.142.2
starlette==1.7.0 uvicorn==0.54.0 httpx` into an empty virtualenv resolved 33 packages, 38 MB of site-packages in all.
Compared with `uv.lock`, the **new** packages are: `mcp`, `mcp-types` (MIT), `sse-starlette`, `jsonschema`,
`jsonschema-specifications`, `referencing`, `rpds-py` (compiled), `attrs`. Already locked: `httpx2` (BSD-3, the SDK's own
HTTP client, 2.13.1 in the lock, 2.14.0 here), `httpcore2`, `opentelemetry-api`, `python-multipart`, `truststore`,
`cryptography`, `cffi`, `pycparser`, `pyjwt`. Not verified: resolution against the engine's locked `pydantic` 2.13.5 (the
fresh install picked 2.14.1; the SDK asks for 2.12 or newer) and the hashed engine bundle (`scripts/build-engine-bundle.sh`)
with these added.

### The API that works

```python
from mcp.server.mcpserver import MCPServer, Context          # the high-level server (FastMCP's successor)
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp

server = MCPServer("wasify", instructions="...")
@server.tool(annotations={"readOnlyHint": True})
async def quick(ctx: Context) -> str: ...

server.streamable_http_app(stateless_http=True, json_response=False)   # call once: builds server.session_manager
                                                                        # (loopback Host/Origin protection is switched on here)
app = FastAPI(lifespan=lifespan)                                        # the engine's own lifespan must do:
#   async with server.session_manager.run(): yield                    # (run() can be entered only once per instance)
app.router.routes.append(Route("/mcp", endpoint=BearerOnly(StreamableHTTPASGIApp(server.session_manager))))
```

- `streamable_http_app()` returns a Starlette app with its own lifespan. FastAPI does not run a mounted sub-app's
  lifespan, so I did **not** mount it; I took its `session_manager`, ran it in the host's lifespan and registered one
  `Route("/mcp")` whose endpoint is a pure-ASGI wrapper. `StreamableHTTPASGIApp` lives in a module that is not part of the
  documented surface: pin the version and test on upgrade.
- A Starlette `Route` is outside FastAPI's dependency system, so the engine's `get_identity` does not apply: **the ASGI
  wrapper does the bearer check** (my toy: constant secret, `401` otherwise). The SDK also has its own `auth=` /
  `token_verifier=` (OAuth resource-server style); **not tested**.
- Tools, `structured_output`, `meta`, `annotations`, progress (`ctx.report_progress`), `Context.protocol_version` and
  `Context.client_capabilities` all work as documented.
- stdio: `server.run("stdio")` also works (SDK client against it, both eras). Not what ADR-0069 uses (the launcher
  talks to the engine), but a free fallback.

### Protocol revisions, measured

| Probe | Result |
|---|---|
| SDK client `mode="legacy"` | negotiated 2025-11-25, list and call work |
| SDK client `mode="auto"` | tried `server/discover`, got 2026-07-28 |
| SDK client `mode="2026-07-28"` | works |
| Raw `initialize` with 2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25 | all answered, then `tools/call` works |
| Raw `server/discover` | `supportedVersions: ["2026-07-28"]` only. Older revisions are reachable by `initialize`, they are not listed |
| 2026-07-28 request without `Mcp-Method` / `Mcp-Name` headers | **HTTP 400, code -32020** "mcp-method header does not match the request body's method" |
| No bearer / `Origin: http://evil.example` / `Host: evil.example` | 401 (my wrapper) / **403** / **421** (SDK; on by default for a loopback host, patterns `127.0.0.1:*`, `localhost:*`, `[::1]:*`). A request with no `Origin` passes |

Statefulness is a flag, `stateless_http=True|False`:

- **2026-07-28 is stateless whatever the flag** (no session id, one POST per request). Tested with the flag both ways.
- **Legacy revisions with `stateless_http=False`** create sessions (`Mcp-Session-Id`, in memory, 30 min idle timeout,
  10,000 sessions by default). A restart of the engine loses them: a client that holds an old id gets **"Session not
  found" (404)**; measured through the launcher with the SDK client (legacy: error; 2026-07-28: fine).
- **Legacy revisions with `stateless_http=True`** work for ordinary calls with all three clients (quick, 1 KB blob, a 12 s
  tool with progress), but the server **cannot send requests to the client**: an elicitation fails inside the tool with
  "this transport context has no back-channel" (JSON-RPC -32600). Progress delivery on this combination was not checked
  against a client's timeout (**not verified**).
- Mid-call elicitation on a legacy revision needs `stateless_http=False` (verified: the SDK client answered, the tool
  continued).

### `input_required`, as the SDK does it

A tool parameter written as `Annotated[T, Resolve(fn)]` where `fn` returns `Elicit(message, Model)` is served as
`InputRequiredResult` on 2026-07-28 (the client retries the same call with `input_responses`; the tool function runs again,
which is why the toy's resolver is idempotent) and as a mid-call `elicitation/create` on older revisions. The SDK client
did both (two POSTs on the new revision, no session; one POST with a back-channel on the old one). The `Elicit` helper is
about asking the **client's user**; it does not by itself wait for a decision made in the Wasify window. In the toy it
only says "decide in the app, then accept here"; the actual decision came from a separate HTTP channel.

### Tasks

`mcp-types` contains the 2025-11-25 and 2026-07-28 task types, and `mcp.server.extension` lets a server add methods
(`MethodBinding`), tools and resources as an extension. I found **no tasks implementation in the server** (the only
hits for `tasks/get` and `io.modelcontextprotocol/tasks` outside the types are a docstring example). Anything to do with
tasks would be hand-built. No client asked for it (below), so nothing is lost.

## 2. The three clients

All runs: a toy server in a FastAPI app (`toy_server.py`, tools `quick`, `slow` with progress every 5 s, `slow_silent`
with none, `needs_approval`, `needs_approval_elicit`, `approval_status`, `job_start`, `job_status`, `blob`, `blob_plain`,
`blob_big`, `image`), a separate "human" channel (`POST /approvals/{id}/decide`), `engine.json` written 0600 by the toy.

### Config snippets that worked

The toy's secret is random per launch; the clients get it from an environment variable, never from the file. These are
the snippets that ran, with the toy's names replaced by `wasify`, and the launcher path an example.

**Claude Code** (`.mcp.json` in the project, or `--mcp-config file`; `claude mcp add --scope project ...` writes the same):

```json
{"mcpServers": {"wasify": {"type": "http", "url": "http://127.0.0.1:8765/mcp",
  "headers": {"Authorization": "Bearer ${WASIFY_BEARER}"}}}}
```
```json
{"mcpServers": {"wasify": {"type": "stdio", "command": "/Applications/Wasify AI.app/Contents/MacOS/wasify-mcp",
  "args": [], "env": {"WASIFY_ENGINE_JSON": "${WASIFY_ENGINE_JSON}"}}}}
```
CLI equivalents, tested: `claude mcp add --scope project --transport http wasify http://127.0.0.1:8765/mcp --header
'Authorization: Bearer ${WASIFY_BEARER}'` and `claude mcp add --scope project wasify -e 'K=V' -- /path/to/wasify-mcp`
(**the name must come before `-e`/`--env`**: the documented form with `--env K=V --transport stdio` before the name
answered "missing required argument 'commandOrUrl'" in this version).
`${VAR}` expands in `command`, `args`, `env`, `url`, `headers`. The documentation says some credential-like names
(`ANTHROPIC_API_KEY`, `NPM_TOKEN`, ...) read as empty in remote `url`/`headers`: use an own name.

**Codex** (`$CODEX_HOME/config.toml`, or `.codex/config.toml` in a trusted project):

```toml
[mcp_servers.wasify]
url = "http://127.0.0.1:8765/mcp"
bearer_token_env_var = "WASIFY_BEARER"
default_tools_approval_mode = "approve"     # see "Codex approvals" below
```
```toml
[mcp_servers.wasify]
command = "/Applications/Wasify AI.app/Contents/MacOS/wasify-mcp"
env = { WASIFY_ENGINE_JSON = "/Users/me/Library/Application Support/wasify/engine.json" }
```
`codex mcp add NAME --env K=V -- COMMAND` writes the stdio block (tested); for HTTP it has `--url` and
`--bearer-token-env-var` (help text read, **not run**).

**OpenCode** (`opencode.json`, or the file named by `OPENCODE_CONFIG`):

```json
{"mcp": {"wasify": {"type": "remote", "url": "http://127.0.0.1:8765/mcp",
  "headers": {"Authorization": "Bearer {env:WASIFY_BEARER}"}}}}
```
```json
{"mcp": {"wasify": {"type": "local", "command": ["/Applications/Wasify AI.app/Contents/MacOS/wasify-mcp"],
  "environment": {"WASIFY_ENGINE_JSON": "/Users/me/Library/Application Support/wasify/engine.json"}}}}
```
OpenCode needed no package download for the provider I used (`@ai-sdk/openai-compatible`; no network call other than to
my fake model was seen with `OPENCODE_DISABLE_MODELS_FETCH=1` and `autoupdate: false`). Tools are named
`<server>_<tool>` (`toy_quick`); Claude Code `mcp__<server>__<tool>`; Codex shows a namespace `mcp__<server>` with the bare
names inside.

### What each client does

| | Claude Code 2.1.302 | Codex 0.163.0 | OpenCode 1.19.3 |
|---|---|---|---|
| Transports tested | HTTP and stdio, both pass | HTTP and stdio, both pass | HTTP and stdio, both pass |
| Revision negotiated | **2026-07-28** on HTTP (`server/discover`, no session). Over stdio it sent `server/discover` (a probe, then again), `subscriptions/listen`, then list and call, no `initialize` | **2025-06-18** (`initialize`, session id, GET stream, DELETE on exit). Over stdio plain `initialize` | **2025-11-25** (`initialize`, session id, GET stream). Over stdio plain `initialize`; it sends `notifications/cancelled` after calls that already finished |
| Client capabilities sent | `roots.listChanged`, `elicitation {form, url}` | `elicitation {form, url}` | `roots {}` only |
| Sends a `progressToken` | yes | yes | yes |
| `input_required` | **yes**: a retry with the answer was sent (below) | no (older revision) | no |
| Elicitation | yes, form and url declared; in `-p` it is cancelled at once; with an `Elicitation` hook that returned `accept`, the call completed | declared; mid-call `elicitation/create` reached the client and was declined (non-interactive `exec`) | **not declared**; the SDK refuses at once with MCP error -32021 "Client did not declare the form elicitation capability" |
| Tasks extension | not advertised | not advertised | not advertised |
| Static bearer from config | yes (`headers`, `${VAR}`) | yes (`bearer_token_env_var`) | yes (`headers`, `{env:VAR}`) |
| Call that passes the limit: what the model gets | `MCP server "toy" tool "slow_silent" sent no response or progress for 300s; aborting.` (+ advice to set a per-server `timeout`), `is_error` | `tool call error: tool call failed for toy/slow_silent ... timed out awaiting tools/call after 30s` (with `tool_timeout_sec = 30`) | `MCP error -32001: Request timed out` (after 60.0 s) |
| Does the server see the abort | yes in all three: the HTTP stream is closed and the toy logged the cancel at 300.1 s (Claude Code), 30.0 s (Codex, with the explicit limit) and 60.0 s (OpenCode) | same | same |
| Job handle (`job_start`, then `job_status` with `wait_seconds` 0, 45, 45) | works | works | works |

### Timeouts, measured

| Call | Claude Code | Codex | OpenCode |
|---|---|---|---|
| 90 to 150 s, **with** progress every 5 s | 150 s completes (`-p`) | 90 s completes (default config) | 90 s completes |
| 90 s, **no** progress | not run | completes | **fails at 60.0 s** (-32001) |
| 130 s and 250 s, no progress, default config | not run | **both complete** (documentation says 60 s default) | not run |
| 330 s, no progress | **aborted at 300 s** (idle limit, documented as 5 min for HTTP) | not run | not run |
| Explicit limit | not run (documented: `timeout` per server, `MCP_TOOL_TIMEOUT`) | `tool_timeout_sec = 30`: aborts at 30.0 s, **progress does not extend it** (a 60 s call with progress failed at 30 s) | `"timeout": 200000` in the `mcp` entry: a 90 s silent call **completed** (documented as the tool-discovery limit; measured, it also covers calls) |
| Progress resets the limit | resets the idle timer (documented; not tested on its own: the 150 s call with progress passed, the 330 s call without progress was aborted at 300 s) | no | yes (90 s with progress passed at a 60 s default) |
| Backgrounding | `-p`: no. `CLAUDE_AUTO_BACKGROUND_TASKS=1`: at **exactly 120 s** the model got "still running after 120s. It was moved to the background as task ... and keeps running" and the call continued (progress "80% · step 24/30" shown); ending the session cancelled it. Interactive default (not run here, documented): backgrounds the same way | none | none |

Discovery: OpenCode's 5 s "timeout" was not tested (the toy answers in milliseconds). Codex's `startup_timeout_sec` 10 s:
not tested. What the person sees in the interactive screens of the three clients was **not verified** (all runs were
non-interactive: `claude -p`, `codex exec`, `opencode run`); the texts above are what the model receives, I did not look at what the person is shown.

### Approvals: what works per client

- **`needs_approval`** (tool waits up to `wait_seconds`, polls a flag set by `POST /approvals/{id}/decide`, returns
  `approved` / `denied` / `{status: needs_approval, approval_id}`): worked in all three. The call returned 6.5 s after the
  "person" decided (Codex), the second call timed out on its own bounded wait and returned the `needs_approval` object,
  and `approval_status(approval_id)` then reported `pending`.
- **`needs_approval_elicit`** (SDK `Elicit`): Claude Code on 2026-07-28 round-tripped it (the retry reached the server
  with the answer; with the hook, the whole call returned `approved` after the 3 s the hook slept while the person
  "decided"). In `-p` without the hook the elicitation was cancelled at once (the tool then errors: **"elicitation was
  cancelled" must be treated as "no answer yet", not as "denied"**). Codex: declined in `exec`. OpenCode: refused (-32021).
  The interactive dialogs were **not seen**.
- **Codex's own approval for MCP tools**: with `approval_policy = "never"`, a tool without `readOnlyHint` failed with
  "MCP tool call requires approval, but approval policy is never" until `default_tools_approval_mode = "approve"` was set.
  So the annotations matter to Codex: `quick` (read-only) ran, `slow` (not marked) was blocked. Claude Code and OpenCode
  runs used their bypass modes (`--permission-mode bypassPermissions`, `--auto`), so their own prompts were not exercised.
  A documented Claude Code `_meta` key, `anthropic/requiresUserInteraction: true`, forces its own prompt on a tool: **not
  tested**; it is a way to make Claude Code ask for tools such as `destroy`.

## 3. Output size

Tool result as text (`blob` uses `structuredContent` plus text; `blob_plain` only text), then an image content item
(PNG noise, the second is 500 KB). "Model got" is what my fake model received back from the client.

| Result | Claude Code | Codex | OpenCode |
|---|---|---|---|
| 1 KB | whole | whole | whole |
| 20 KB and 45 KB (plain text) | whole | not run | not run (50 KB passed whole) |
| 50 KB (`blob`, 51,200 chars) | `<persisted-output>`: saved to a file under the session folder, the model gets a **2 KB preview** and the path (documented threshold: over 50,000 characters) | **cut in the middle to 12,020 characters** with "...37047 chars truncated..." (head and tail kept) | whole (51,200 chars, `truncated: false`) |
| 120 KB plain | persisted to file, 2 KB preview | not run | not run |
| 120 KB and 450 KB plain with `_meta["anthropic/maxResultSizeChars"] = 500000` on the tool | **whole** (122,880 and 460,800 chars) | | |
| 500 KB (`blob`, 512,000 chars) | **`Error: result (512,013 characters) exceeds maximum allowed tokens`**, output saved to a file, an instruction to read the file | cut in the middle to 12,020 characters | **cut**: a 389-char notice "512000 bytes truncated ... Full output saved to: <path>", the full text is a file under the OpenCode data folder |
| Image 20 KB / 500 KB | the model gets the image inline plus a line "[Image: source: <path>]"; the original is saved under `tool-results/`. The 500 KB image reached the model as 546 KB of base64 text (re-encoded, about 20% smaller than the 682 KB original encoding); 20 KB as 27 KB | passed **whole inline** as `input_image`: 27,661 and 682,845 characters | attached as a data URL in a follow-up user message "Attached media from tool result:" |
| Wrapper | with `structuredContent`, Claude Code showed the JSON text (`{"result":"..."}`) rather than the text content; OpenCode showed the plain text content | Codex printed the JSON from structured content | |

Reading: a text result under about **10 KB** is safe everywhere; over 12 KB Codex cuts the middle, over 50 KB Claude
Code and OpenCode send a file path instead of content. Returning ids and `wasify://creation/<id>` links, as ADR-0069
decision 6 says, is the right shape. The optional 256 KB preview image passed in all three (real model image limits were
not exercised: the model was fake). A tool that returns a `str` gets `structuredContent: {"result": ...}` from the SDK
(it infers an output schema): return a dict or turn `structured_output` off on purpose, and put the sentence for the model
in the text content, because the clients disagree on which channel they show the model.

## 4. Auth and the runtime file

- All three pass a static bearer from their config to a loopback HTTP server (table above). Without the secret the toy
  answered 401 and no client sent it unprompted.
- For the stdio launcher the secret is never in the client's config: the launcher reads `engine.json` (pid, host, port,
  secret) on **every request**, so a restart of the engine (new port, new secret) is picked up without restarting the
  client (HTTP era 2026-07-28 verified through the launcher; legacy needs the re-initialize below).
- The prototype's checks before it trusts the file, each tested with a hostile file (all four answered with
  "Open Wasify AI, then try again." and wrote the reason to its log): path is not a symlink and is a regular file; owned by
  the current user; no group or other permission bits (a 0644 copy was refused); the folder is owned by the user and not
  writable by group or other; `host` is loopback (a `10.0.0.5` copy was refused); the `pid` is alive (a stale file with
  pid 99999 was refused). The toy writes the file with mode 0600 through a temporary file and an atomic rename, and removes
  it at exit. For the Rust launcher: check on the **open file descriptor** (`fstat`), open with `O_NOFOLLOW`, rather than
  `lstat` and then `open`, to close the check-then-use gap (the prototype does `lstat` first; not exploited, not tested).
- DNS rebinding and browser `Origin` protection come from the SDK (403 and 421 above). The body-size limit default in this
  SDK is **4 MiB** (`max_request_body_size`, a parameter), not the 1 MiB of ADR-0069; not measured.

## The launcher: what it has to do (all found by running it)

The prototype is about 210 lines of Python and passed with all three clients. It is not a byte pipe:

1. On 2026-07-28 the HTTP layer requires `MCP-Protocol-Version`, `Mcp-Method` and, for `tools/call`, `prompts/get` and
   `resources/read`, `Mcp-Name` headers that the stdio message does not carry. The launcher derives them from the body
   (`params._meta["io.modelcontextprotocol/protocolVersion"]`, `method`, `params.name`). Without them: HTTP 400.
2. Legacy clients (Codex, OpenCode) need `Mcp-Session-Id` and `MCP-Protocol-Version` carried from the `initialize`
   response. If the engine restarted the session is gone; the launcher **replays the client's `initialize` and
   `notifications/initialized`** on a 404 and retries once (tested: before the fix the SDK client got "Session not found").
   With `stateless_http=True` this problem does not exist.
3. It streams: responses can be `text/event-stream` with progress notifications (and, on legacy, server requests); each
   `data:` event goes to stdout as one line. Claude Code also sends `subscriptions/listen` (a long-lived stream) and
   `server/discover` twice; all forwarded without trouble.
4. `notifications/cancelled` from the client ends the in-flight HTTP request (closing the stream is how cancellation
   reaches the engine; measured: the tool saw the cancel within the poll interval).
5. When the app is not running it must still answer `initialize` / `server/discover` / `tools/list` / `tools/call`
   itself. On 2026-07-28 these local results need `resultType: "complete"`, `cacheScope`, `ttlMs` in the envelope (the SDK
   client rejected my first local `tools/list` without them). All three clients surfaced the sentence "Open Wasify AI,
   then try again." when the model called the single local tool `app_status`.
6. **Open problem:** with the app closed the launcher can only offer a stub tool list, and the clients read the list once.
   Whether Claude Code, Codex and OpenCode refresh it after the app starts (`notifications/tools/list_changed`, or a
   reconnect) was **not tested**. Until it is, the message must say "open Wasify AI, then restart your agent".

## Table of results per client version

| | Claude Code 2.1.302 | Codex 0.163.0 | OpenCode 1.19.3 |
|---|---|---|---|
| Recommended transport | **stdio launcher** (HTTP also fine) | **stdio launcher** (HTTP also fine) | **stdio launcher** (HTTP also fine) |
| Why | the port changes per launch for all three; HTTP is only for the opt-in fixed port | same | same |
| Revision | 2026-07-28 | 2025-06-18 | 2025-11-25 |
| Sessions | none | yes (id, GET, DELETE) | yes |
| `input_required` | **usable** | not available | not available |
| Elicitation | declared | declared (legacy, needs stateful server) | not declared |
| Tasks | no | no | no |
| Tool-call limit | idle 300 s; no wall clock; auto-background at 120 s (interactive) | not enforced up to 250 s by default (docs: 60 s); explicit `tool_timeout_sec` is hard | 60 s, reset by progress, raised by `timeout` |
| Result size that reaches the model whole | about 50,000 chars (more with `anthropic/maxResultSizeChars`) | about 12,000 chars | about 50 KB |
| Job handle works | yes | yes | yes |
| Config that worked | snippets above | snippets above | snippets above |

## When `input_required` is usable

Only when **all** hold: the client negotiated 2026-07-28 (today Claude Code only), its capabilities include
`elicitation`, and a person is there to answer (interactive, or a hook). It is **not** usable as the waiting mechanism:
the client's dialog is a second approval prompt, not the Wasify window, and headless runs cancel it immediately. It is
useful as a courtesy ("I have asked in the app, press accept when you have decided") and as a way to avoid holding a
call open, but the decision must still come from the Wasify window and the call must be correct without it.

## What this forces on ADR-0069

Go for stage M1, with these changes (each is a sentence in the ADR, none changes a stage):

1. **Decision 1 (revisions).** Say what is true: only Claude Code is on 2026-07-28; Codex speaks 2025-06-18 and OpenCode
   2025-11-25, and both open sessions. Choose `stateless_http=True` (restart of the engine loses nothing; no session
   table; the launcher needs no replay) and accept that on legacy revisions the server cannot ask the client anything.
   If a later feature needs mid-call elicitation on Codex, switch to `stateless_http=False` and keep the launcher's
   re-initialize. The conformance suite (decision 12) must test 2025-06-18 and 2025-11-25 as well as 2026-07-28, and the
   recorded sessions are three different shapes.
2. **Decision 1 and 11 (mounting and transport safety).** The route is a Starlette `Route` around the SDK's
   `StreamableHTTPASGIApp`, outside FastAPI dependencies; the engine's `/mcp` auth, rate limit and activity log are an ASGI
   wrapper written by us. Set `max_request_body_size` to 1 MiB explicitly (the SDK default is 4 MiB). The `Origin` /
   `Host` checks come from the SDK when the host is loopback.
3. **Decision 2 (launcher).** Add the list above to the ADR as requirements: header derivation, streaming, cancellation,
   local answers per revision, re-initialize on 404 if stateful, checks on `engine.json` on the open descriptor. It is
   about 300 lines of Rust as estimated, but not a byte pipe; the first version can be the Python prototype in the
   scratch folder as the reference. Add the open problem 6 to the open questions.
4. **Decision 7 (long work).** Keep `wait_seconds` default 25, at most 50. Add: **send progress at least every 5 s**
   (Claude Code's idle limit and OpenCode's 60 s are reset by it; Codex's explicit limit is not). The "60 seconds of
   Codex" is a documented value that this version did not enforce by default; keep the safe number. The tasks extension is
   **dropped from M1**: no client advertises it and the SDK has no server for it. Job handles work in all three; keep them.
5. **Decision 8 (approval).** Re-word: approval is decided in the Wasify window; the tool waits a bounded time and then
   returns `needs_approval` with an `approval_id` that `job_wait` / `approval_status` can follow. `input_required` is
   optional, only on 2026-07-28 with `elicitation` declared, and a cancel or decline from it means "not answered".
   Also: "clients are unaffected by their own approval prompts" is not true. Codex asks (or refuses) per tool according to
   `readOnlyHint`; Claude Code has permission rules and `anthropic/requiresUserInteraction`; the annotations in decision 4
   must be accurate, and the Settings button for Codex should show `default_tools_approval_mode` as a choice.
6. **Decision 6 (results).** Add the measured limits: text over about 12,000 characters is cut in the middle by Codex,
   over 50,000 characters is replaced by a file path by Claude Code and OpenCode, 500 KB is an error in Claude Code. Results
   stay under about 10 KB; ids and links as written. Return a dict with a sentence in the text content (the SDK wraps a
   plain `str` as `{"result": ...}`).
7. **Decision 3 (copy-for-client).** Generate the snippets in "Config snippets that worked"; the HTTP forms need a
   variable holding the secret, the stdio forms need only the launcher path (and `WASIFY_ENGINE_JSON` if the default
   location is not used). Claude Code's `claude mcp add` needs the name before `-e`.
8. **Decision 9 (dependency).** Eight packages enter the lock besides `mcp` (list in section 1), one of them compiled
   (`rpds-py`). Check the hashed engine bundle.

## Not verified

- Every interactive screen of the three clients (what the person sees on a timeout, Claude Code's elicitation dialog and
  `/tasks`, Codex's approval prompt and its interactive default tool timeout, OpenCode's permission prompt).
- Behaviour with a real model (tool selection, how a model uses `needs_approval` or the job handle).
- Windows and Linux; the Rust launcher; macOS app signing of the launcher.
- Refresh of the tool list after the app starts (open problem 6); `notifications/tools/list_changed`.
- OAuth and the SDK's own `auth=`; the engine's real `main.py` (I reproduced its CORS and `@app.middleware("http")`
  request-id wrapper in a toy FastAPI app of the same locked versions, not the engine itself).
- `stateless_http=True` with progress delivered to a legacy client under a timeout; Codex and OpenCode with
  `stateless_http=True` for anything beyond quick, a 12 s tool and a 1 KB blob.
- The 1 MiB request-body limit; the 5 s OpenCode discovery timeout; `startup_timeout_sec` of Codex.
- Claude Code's v1 runtime (`MCP_SDK_GENERATION=v1`) and `MCP_PROTOCOL_NEGOTIATION=legacy`: what the default is on the
  owner's machine in other session types is documented as varying (the runs here negotiated 2026-07-28).
- `anthropic/requiresUserInteraction`, `anthropic/alwaysLoad`.
