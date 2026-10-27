# Phase 4 plan: the app as a tool for agents, and an assistant that knows the app (desktop first)

Written 2026-10-18. The desktop app is the top priority; the web catches up after (`docs/backlog.md` holds what is
left open there). This plan refines three requests from the owner:

1. An **MCP server** so Claude Code, Codex and OpenCode can use every feature and skill of the app.
2. An **MCP client** so the app can use remote third-party MCP servers.
3. An **assistant "trained" on the product** that guides ("How can I do a text to speech?" gives steps, then asks
   for the text and offers a button that makes the file) and executes.

Decisions are in four ADRs, **Accepted 2026-10-18**: ADR-0068 (action catalogue), ADR-0069 (MCP server),
ADR-0070 (MCP client), ADR-0071 (assistant that knows the product).

**Status (2026-10-19):** stage A1 is built and unstaged for review: the catalogue (38 actions), the executor, the
audit and approval stores, the help drafts and the tests that tie them to the menu. See `docs/actions.md`. Stages A2
onward are not started; the spikes S1 and S3 run on their own.

## What the refinement changed

| The idea | What it became, and why |
|---|---|
| Three features | **One foundation and three surfaces.** What the product can do is described in four places today (screens, routes, the assistant's four tools, docs). Building a server, a client and a smarter assistant on that would make six. A single **action catalogue** (ADR-0068) is the one description; the server, the assistant, the help text and the approval rules are all generated from it. It is the one addition to the three asked for, and everything depends on it |
| "Train the assistant" | **Do not fine-tune.** The knowledge is small, changes weekly, differs per chat model the person picks, and must include the truth about *this computer* (is a speech model installed?). So: a versioned **help corpus** (one Markdown file per action), live `app_status`, a fixed set of **meta-tools**, and an **evaluation** that proves it. Fine-tuning is gated on the evaluation failing (ADR-0071 decision 9) |
| "It executes the product" | **Action cards, not immediate runs.** The assistant proposes; a card shows the fields filled in from what the person said, editable, with an estimate and badges and a Run button. The click is the approval. Today's `generate_image` runs at once; the card fixes wrong parameters and costly surprises, and it is how ADR-0057's unused `interrupt` gets used |
| "All features" for MCP | **About 40 actions, grouped, and private groups off by default.** Library and notebooks send the person's own data to the agent's model provider, so they are opt-in. Consent actions (voice cloning, lip sync) and deletes need a person in the window every time. The agent cannot approve for itself: approvals appear in the Wasify window |
| MCP server in the app | **A stdio launcher plus an endpoint in the engine.** The engine's port changes every launch and the engine is a child of the shell, so a static client config needs a small launcher (`wasify-mcp`). It is off by default, with revocable connections and an activity log |
| MCP client for third parties | **Staged last, with a taint rule.** Remote servers bring code execution (stdio), data leaving, and prompt injection. After the assistant has read anything from a remote server, every non-read action asks in the window. Three trust levels per connection. No curated store, no passthrough through our server |
| Many tools for a small local model | The model sees **the same six or seven tools however many actions or remote tools exist**; the catalogue is searched, not listed |

## The picture

```
                    ┌──────────────── Wasify AI desktop app ────────────────┐
 Claude Code ─┐     │  window (React)                                       │
 Codex ───────┼─ stdio ─► wasify-mcp (launcher) ─► engine /mcp (ADR-0069)   │
 OpenCode ────┘     │                                   │                    │
                    │  assistant (ADR-0071) ────────────┤                    │
                    │   how_to · app_status · propose_action ·               │
                    │   open_screen · search_* · external_tools              │
                    │                                   ▼                    │
                    │            ACTION CATALOGUE + EXECUTOR (ADR-0068)      │
                    │   schema · effect · flags · requires · help · ui       │
                    │   approvals (in the window) · safeguards · audit       │
                    │                                   ▼                    │
                    │   child runs of the products: image, video, voice,     │
                    │   notebooks ... (one memory slot, one job at a time)   │
                    │                                                        │
                    │  MCP client (ADR-0070) ─► remote / local third-party   │
                    │   servers the person added; taint rule; keychain       │
                    └────────────────────────────────────────────────────────┘
```

## Stages

Sizes: S under a week, M one to two weeks, L two to four, for one person working with tests. Each stage ends with
something a person can use, and each can be reviewed alone.

### Stage 0. Spikes (S, before anything is built)

Each spike answers one question with a measurement, written to `docs/spikes/`. None changes the product.

| Spike | Question | Done when |
|---|---|---|
| S1 | Does the `mcp` SDK 2.x serve revision 2026-07-28 and the older ones from a route of our FastAPI engine? Do **Claude Code, Codex and OpenCode** (current versions) connect through a stdio launcher? Which of them support `input_required` and the tasks extension? What is the real tool-call timeout behaviour? | A toy server with three tools (one slow, one that needs approval) is driven by all three clients; a table of results per client version |
| S2 | How does an agent hand the app a file and get one back without an arbitrary-path hole? Allowed folders, symlinks, `..`, macOS permissions for Documents and Desktop | The rules of ADR-0069 decision 6 hold under a test of 20 hostile paths |
| S3 | How many tools can Qwen3 4B, a larger local model and a hosted model choose among? Does the meta-tool design (`propose_action`) beat one-tool-per-action at 12, 40 and 80 actions? Is the hash embedder enough for help retrieval? | The numbers, from the existing evaluation runner extended with the new case types (ADR-0071 decision 8) |
| S4 | Secrets: Python `keyring` in the engine, or the shell as owner? OAuth with a loopback callback in a Tauri app; Client ID Metadata Documents support in the SDK | A working login against one real remote server and the decision |
| S5 | A macOS sandbox for stdio servers: possible without breaking the app's own sandbox and notarisation? | A yes/no with a test profile, or "later" with the reason |

### Stage A1. The action catalogue and executor (M) — foundation — **built 2026-10-19** (`docs/actions.md`)

- `wasifyai_platform_sdk.actions`: the `Action` model, registry, `requires` resolver, `run_action` with approvals,
  audit and `origin`; the `ActionResult` type; `docs/contracts/actions.json` export.
- Per-product `actions.py` for **image, video, speech, voice, music, notebooks, library, models, app, job**
  (about 40), bound to the existing child runs and checks. No product code changes except small `check_*` exports.
- The four assistant tools re-implemented as actions; the existing 11-case evaluation still passes.
- Help files for every action (first drafts), and the tests that tie them to the menu and screens.
- **Acceptance:** every menu item with a screen has an action or an explicit exemption; running each action through
  the executor with a fake engine produces the documented result; `destroy` and `needs_consent` cannot be set to
  auto; usage and audit entries exist; no change visible to the person yet.

### Stage A2. The assistant guides and proposes (M) — first thing the owner sees — **first slice built 2026-10-27** (ADR-0071, "Built 2026-10-27")

> **Note (2026-10-19, ADR-0082):** the chat UI moves to assistant-ui. Build A2's backend (help corpus, `propose_action`, `confirm_action`) as planned, but write its **cards as assistant-ui tool UIs** after chat stage CU1 (`docs/chat-ui-migration-plan.md`), not as new `ToolCard` code.
> **Update (2026-10-20, CU1 built behind Labs):** tool UIs are registered by tool name in `packages/ui/src/chat/thread/tool-uis/index.tsx`
> (`toolUIs`), and `confirm_action` already has a placeholder card there (`ConfirmActionCard`). An `interrupt` event already becomes a tool
> part with an `approval` (`packages/client/src/chat-tree.ts`); what CU2 adds is answering it (`POST /runs/{id}/resume`), the stored
> `interrupt` part, and the card itself. Write the action card as a new entry of `toolUIs`, using `ToolCallMessagePartProps.respondToApproval`.

- The meta-tools (`how_to`, `app_status`, `propose_action`, `open_screen`), the help retrieval, the system prompt
  map generated from the catalogue.
- `interrupt` `confirm_action` and the **action card** in `packages/ui` (schema-driven fields, estimate, badges,
  Run, Edit, Cancel, result with player and Save as), shared by the desktop and the web.
- Auto-run settings per conversation; the "pauses the chat model for N seconds" note.
- **Acceptance:** "How can I do a text to speech?" gives the real steps with the real labels and says what this
  computer is missing; "make it say hello world in a calm voice" shows the card with the text filled in; Run makes
  the speech and the card turns into a player; the same flow works for an image, a song, a transcript.

### Stage A3. The assistant evaluation, and the gate (S to M) — **built and run 2026-10-27** (`docs/spikes/assistant-a3.md`)

- `guide`, `action`, `status`, `safety` and `tool-count` cases (60 to 150), scored for three model tiers.
- Acceptance thresholds, fixed **before** A2 is declared done: no regression on the existing 11; at least 90
  percent on guide and action cases with Qwen3 4B; the safety cases pass for every tier. If a tier misses, the card
  path stays but carries "this model may be unreliable", and the fine-tune gate (ADR-0071 decision 9) opens a new
  ADR.
- Runs on demand and in the release checklist.

### Stage M1. The MCP server, make-only (M) — **built 2026-10-27** (ADR-0069, "Built 2026-10-27"; `docs/desktop/connections.md`)

- The endpoint in the engine on the `mcp` SDK; the `wasify-mcp` launcher; the runtime file `engine.json`.
- Settings > Connections: the switch, the first connection, the secret, "Copy for Claude Code / Codex /
  OpenCode", the activity log, revoke.
- Tools: `make` group (image, video, speech, music, transcribe) and `models`, `app_status`, `job_*`. No library,
  notebooks, voices, deletes.
- Approval cards in the window; `input_required` where the client supports it.
- **Acceptance:** each of the three clients (current versions) installs the config from the Settings button and
  makes a picture and a speech file, finds the job when it takes longer than its timeout, and a request that needs
  approval shows a card in the app and waits. Conformance suite green for each protocol revision we claim.

### Stage M2. The rest of the tools, and files (M to L) — **built 2026-10-27** (ADR-0069, "Built 2026-10-27 (stage M2)")

- `library` (search, list, get, **export** to allowed folders), `notebooks`, `voices` (design, clone with
  consent), `audio` tools, `dub`, `audiobook`, `lipsync` (consent), `admin` (rename, delete).
- Allowed folders (read and write) per connection; image previews of at most 256 KB; `resource_link` results.
- Scope presets: "Make things" (default), "Make and use my library", "Everything".
- **Acceptance:** an agent can transcribe a file under its allowed folder and cannot read outside it; delete and
  clone need the window; a library search is refused unless the scope has it; the 20 hostile-path test passes.

### Stage M3. Hardening and reach (M) — built 2026-10-27 (ADR-0069 "Built"; the review is `docs/mcp-security-review.md`)

- Rate limits and per-connection quotas; a visible "from Codex" label on jobs and creations; notifications for
  background approvals.
- Optional: start the app without a window for a launcher call (a shell decision); a fixed-port HTTP option; a
  generated skill file and example prompts for Claude Code; Windows and Linux launchers (after the Mac ships).
- A security review against the checklist below.

### Stage C1. The MCP client, read-only (M)

- Engine module on the SDK; Settings > "Tools from other apps"; HTTP (https and loopback) and stdio; keychain;
  OAuth 2.1 with CIMD; `tools/list` caching; activity log; the `external_tools` and `call_external` meta-tools.
- Trust levels `Ask` and `Blocked`; every call that is not annotated read-only on a `Trusted` server asks.
- **Acceptance:** a real remote server (read-only) works through the assistant; a malicious fake server (huge
  result, hidden instructions, redirects, lying annotations, slow) cannot make the app act or leak.

### Stage C2. Taint rule, trust, evaluation (M)

- The taint rule with provenance on cards; `Trusted read-only`; stdio confirm dialog and minimal environment.
- Evaluation: external-tool selection with 5 and 40 remote tools; the per-tier decision on whether remote tools
  are offered to local models.

### Stage C3. Reach (S to M)

- Resources attached to a message; prompts as templates; elicitation forms; the tasks extension; import from
  other clients' configs; sandbox for stdio if S5 says yes.

### Suggested order

`S1, S3` (in parallel) → **A1** → **A2 and M1 in parallel** (two sessions: both need only A1) → **A3** → **M2** →
`S2` is done before M2 starts → **M3** → `S4, S5` → **C1** → **C2** → **C3**.

Why: the catalogue unblocks everything; the assistant card is what the owner sees first and exercises the catalogue
with real people; the server reuses the same approvals; the client carries the most risk and so goes last, behind
an evaluation that decides whether local models should get remote tools at all.

## Rules these stages follow

- Nothing is exposed to a surface that is not in the catalogue's `surfaces` (ADR-0057, ADR-0068).
- Safeguards, quotas, upload hardening and the one-job-at-a-time rule are the app's, not the surface's.
- Approval is shown in the Wasify window and cannot be answered by the agent. The floor (`destroy`,
  `needs_consent`) cannot be lowered from any surface.
- Results are references, never bytes; files leave only through `library_export` to a folder the person allowed.
- Off by default, per connection, revocable, with an activity log that holds no content.
- Every feature has its action, help file and `ui` pointer before it counts as done (a rule for CLAUDE.md on
  acceptance), as every creation is searchable (ADR-0041).
- English only in v1; multilingual from the start in the sense that user text in any language works.

## Security checklist (the review in M3, and before C1 ships)

| Threat | Control | Where |
|---|---|---|
| A web page calls the local endpoint (DNS rebinding, CSRF) | Bearer connection secret, `Origin` refused, `Host` checked, no CORS | ADR-0069 decision 11 |
| Another local user or program reads the secret | Runtime file mode 0600, secret shown once, stored hashed, per-connection revoke | ADR-0069 decisions 2, 3 |
| An agent tricked into harm (prompt injection through what it reads) | Effects enforced by the engine, not by hints; approvals in the window; `destroy` and `needs_consent` always ask | ADR-0068 decision 4 |
| Our assistant tricked by a remote tool result | Taint rule, labelled and truncated external text, provenance on cards | ADR-0070 decision 5 |
| Arbitrary file read or write | Allowed folders, resolved paths, symlinks followed and checked, `..` refused | ADR-0069 decision 6 |
| Private data sent to an agent's provider without the person knowing | `library` and `notebooks` opt-in with plain wording; the connection card says who receives it | ADR-0069 decision 5 |
| A stdio server steals secrets or the library | Minimal environment, working folder under app data, typed confirmation, idle stop; a sandbox only if S5 proves one | ADR-0070 decision 3 |
| SSRF through a remote server address | https only, private and link-local ranges refused, no cross-host redirects with credentials | ADR-0070 decision 6 |
| Token or key in a log | Secrets only in the keychain; logs hold no content or secrets; tests grep for them | ADR-0070 decisions 7, 11 |
| Resource exhaustion (an agent loops) | One running job and eight waiting per connection, rate limits, the executor's quotas | ADR-0069 decision 10 |
| Voice cloning or lip sync without a person's word | `needs_consent`: the statement is shown in the window every time | ADR-0066, ADR-0068 |
| Memory slot fights (agent and window) | One slot, FIFO queue, jobs labelled and cancellable by the person | ADR-0056, ADR-0069 decision 10 |

## Test strategy

- Unit: the catalogue's schema and `requires` resolution; every action through the executor with a fake engine
  (the voice and image test rigs already have fakes); approval floors; path checks (hostile list); the taint rule.
- Contract: conformance of the endpoint with the SDK's client per protocol revision; golden recordings of one
  session from each of the three clients, replayed.
- Evaluation: the assistant cases (stage A3), run on demand per model tier; the security cases are also unit
  tests with a scripted model.
- End to end on a Mac: the desktop self-test gains a step that makes a speech file through the launcher.
- A malicious fake MCP server for the client (stage C1).
- Manual release gate: the three real clients, a screen-recorded run, kept with the release evidence.

## Decisions needed from the owner

1. **Accept or change** ADR-0068 to 0071. In particular: the extra foundation ADR (0068); no fine-tuning in v1;
   the card (click to run) as the default for the assistant; library and notebooks off by default for agents.
2. **Dependencies (CLAUDE.md: ask first):** the Python `mcp` SDK 2.x (MIT, official) for the server and the
   client; a keychain library for the client (Python `keyring`, MIT, or the shell as owner; spike S4). The
   launcher needs nothing new beyond what the shell builds with, to be confirmed in M1.
3. **Order:** the suggested order puts the assistant card (A2) beside the MCP server (M1) and the client last.
   Say if the client should come earlier.
4. **App closed:** in v1 an agent cannot start the app. Accept, or make "start the app without a window" part of M1.
5. **Names:** the launcher `wasify-mcp` and the tool names (`image_generate`, `speech_speak` ...). Easy to change
   now, hard after people have configs.
6. **Platforms:** Mac first, as the desktop is. Windows and Linux launchers after.

## What I would not do

- Generate MCP tools from the API routes, or expose every graph.
- Let any surface lower the approval floor, or let the assistant add an MCP connection.
- Return files or large content inside tool results.
- Run the server when the app is closed, or give it a public address.
- Recommend third-party servers from inside the app before they are reviewed.
- Fine-tune before the evaluation says prompts and retrieval cannot do it.
