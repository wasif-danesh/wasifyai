# Improvement plan: the architecture, the features, and the four agent surfaces (2026-10-27)

Written 2026-10-27 from a read of the source, the ADRs (0001 to 0091), the plans, the spikes and the backlog, for both the
desktop app and the web app. Every number below was taken from the checkout on that day; anything not read or run is marked
**not verified**. The agent surfaces the owner asked about (an MCP server and an MCP client) have their own sections (5
and 6) with a concrete design each, on top of the Accepted ADRs 0068 to 0071 and the spike that tested them
(`docs/spikes/mcp-s1.md`). Two more were dropped by the owner on 2026-10-28: an agent on Hermes (section 7; a component
of about 660 MB is not practical in the app) and API keys for the products (section 8; not wanted).

Nothing here changes an Accepted ADR. Where a recommendation needs a new decision it says so and names the ADR that would
record it. The working tree holds uncommitted Train-on-the-web work (`docs/train-web-plan.md`, stage WT0); this plan does
not touch those files.

## Contents

1. [What is there, in one screen](#1-what-is-there-in-one-screen)
2. [What is strong](#2-what-is-strong)
3. [Findings: where the architecture hurts](#3-findings-where-the-architecture-hurts)
4. [The improvement plan, in stages](#4-the-improvement-plan-in-stages)
5. [The MCP server](#5-the-mcp-server)
6. [The MCP client](#6-the-mcp-client)
7. [The agent on Hermes (dropped)](#7-the-agent-on-hermes-dropped)
8. [API keys (dropped)](#8-api-keys-dropped)
9. [Order, dependencies and sizes](#9-order-dependencies-and-sizes)
10. [Decisions the owner must make](#10-decisions-the-owner-must-make)

## 1. What is there, in one screen

| Layer | Desktop (Tauri window) | Web (Next.js + containers) | Shared |
|---|---|---|---|
| Shell | `apps/desktop/src-tauri` (Rust, AGPL-3.0): engine supervision, provisioning (uv, Python, hashed lock), ComfyUI and llama.cpp installers, updater skeleton, a per-launch HS256 token | `apps/web` (Next.js App Router): Auth.js sign-in, the BFF that mints a 5-minute HS256 token per request and proxies to the API, admin pages | `packages/ui` (every screen), `packages/client` (typed engine client, SSE, message tree, flow reducers), `packages/contracts-ts` (generated) |
| Engine | `services/api` in the `desktop` profile: SQLite, in-process queue and event log, local files with signed links, loopback only | the same engine in the `web` profile: Postgres + pgvector, Redis Streams, S3 storage, LiteLLM; media worker, engine workers (ADR-0087), notebooks worker | `packages/platform-sdk`: capabilities, providers, storage, usage, slots, the action catalogue and executor, engine jobs |
| Products | image, video (with Video Builder), voice (speech, music, tools, dub, audiobook, lip sync), notebooks, assistant, 3D, training | the same products; what has no web home runs as a job on an engine worker | `products/*`: `product.yaml`, graphs, routes, `actions.py`, `models.yaml`, prompts, workflows |
| Agent surfaces | the catalogue (51 actions, help file each) and the executor are built; the assistant runs six of them; MCP server, MCP client: **not started** | same catalogue; the web assistant does not offer `models.*` | ADR-0068 to 0072 Accepted; spikes S1 and G0 done |

Sizes that matter for the plan: `services/api/src/wasifyai_api/` has about 95 files and 19,200 lines (`main.py` 808,
`audio_runtime.py` 1,109, `desktop_discovery.py` 1,117); the SDK 9,300 lines; `products/wasifyai-voice/wasifyai_voice/actions.py`
1,224 lines and its `routes.py` 920; the Rust shell about 5,000 lines (`provision.rs` 927, `comfyui.rs` 831, `engine.rs` 802);
`packages/ui` and `packages/client` about 55,000 lines including tests. Tests: about 1,900 Python test functions and 230
TypeScript test files, Playwright specs for the chat and the shared screens, a kind smoke test, and a desktop self-test that
drives the real window on three operating systems. 22 Alembic migrations.

## 2. What is strong

These are the parts to build on, not to change.

- **One engine, two profiles, one set of screens** (ADR-0056, ADR-0087). The same product graphs, routes and `packages/ui`
  screens run in the window and in the browser; the differences are adapters behind interfaces that already existed. The
  parity gate (`apps/web/lib/parity.ts`, the `parity` CI job) keeps it honest: only two rows are not live today.
- **The action catalogue and executor** (ADR-0068, `docs/actions.md`). One description of everything the app can do, with
  effect, flags, requirements, help, UI pointer and surfaces; one choke point with approvals, an audit log that holds no
  content, usage events and job handles; a floor (`destroy`, `needs_consent`) that no setting can lower. This is exactly the
  foundation the four agent surfaces need, and it is already tested with fakes per product.
- **Confirm-first, measured, pinned.** Every download shows its size and waits for a click; every component is a pinned
  release with a hash; every ADR carries measurements from this Mac; licences travel with weights (`commercial_use`). The
  spikes answer questions before code is written.
- **Security habits.** Loopback only, a per-launch secret, signed file links, upload hardening, a sandboxed render for
  Video Builder, a redirect-refusing loopback HTTP client in the shell, write-only keys, the taint rule for web results in
  the chat, the markdown safety test.
- **The design system** (ADR-0081): one `DESIGN.md`, generated tokens, a lint that fails on hard-coded values.
- **Documentation discipline.** ADRs with status, plans with exit criteria, a backlog that says what was never verified.

## 3. Findings: where the architecture hurts

Each finding names the evidence and the cost it causes. Section 4 turns them into stages.

### 3.1 The engine is assembled by one 800-line factory over a bag of attributes

`create_app` in `main.py` builds every store, service and router inside one lifespan, and hands them around as
`app.state.<name>`: 50 distinct attributes are set there, and product and API code reads them back with `getattr(state, ...)`
in 128 places (`tool_host.py`, `actions_engine.py`, the products' `routes.py`). A missing service is a `None` at run time, not
a type error; a test must know which attributes to fake. The desktop and web halves are interleaved `if desktop ... else`
branches, which is the rule-1 smell ("no `if env` paths") inside the engine itself.

### 3.2 Nine components, nine installers, two languages

Optional components are installed by hand-written code per component: ComfyUI and llama.cpp in the **Rust shell**
(`comfyui.rs`, `llamacpp.rs`, `provision.rs`); audio.cpp, MuseTalk, Pixal3D, Video Builder, the three trainers and the
notebooks reader in **Python** (`audio_runtime.py`, `lipsync_runtime.py`, `model3d_runtime.py`, `video_builder_runtime.py`,
`training_setup.py`, `language_setup.py`, `decision_setup.py`, `video_setup.py`, `reader_install.py`), each with its own
`*_pins.json` (nine of them), its own consent-bytes check, progress shape, repair path, slot ownership and status route.
The pattern is the same every time; the code is not shared. Consequences: a new component costs a week of copying; the shell's two installers cannot be reused by an engine worker on the web (ADR-0087 had to
re-implement fetching for workers in `admin_wire.py`); and the engine bundle script already misses pieces (backlog D29: no
3D product, no prompts for video and 3D in a packaged app).

### 3.3 Two store families and no migration runner on the desktop

Postgres has Alembic; SQLite has `ensure_tables` and `ensure_columns`, so every desktop schema change must be additive for
ever (`docs/desktop-profile.md`, "Schema changes"). Each product that reached the web wrote a `pgstore.py` subclass of its
SQLite store (notebooks, 3D, training next). That is the right shape, but there is no shared base that owns the dialect
differences, so each subclass repeats them.

### 3.4 Jobs: three queues, two patterns, one in-memory job book

- Image and video use the pause-and-resume pattern (the graph checkpoints, the worker resumes it). The voice graph **awaits
  the engine job inside the run** (ADR-0087 "a compromise, to be revisited"): no queue position, and Stop does not stop the
  worker. 3D and Video Builder have their own per-person job managers.
- (Fixed in J3, 2026-10-28: jobs are kept in `action_jobs` and answered from their run after a restart.) The
  executor's `JobBook` (the handles `job.status` and `job.wait` follow) is in memory: after a restart a handle only
  knows how the job ended from the audit log. An MCP client that waited 25 seconds and comes back after an engine restart
  gets "unknown job".
- ADR-0088 (one job per person before go live) is Accepted and not built; today a second press of Create queues a second
  job for images, video, music and speech.
- Two API replicas resuming the same long job is a known gap (ADR-0087, "Not covered").

### 3.5 Identity knows one kind of caller

`Identity(tenant_id, user_id, role)` comes from one HS256 token whose subject is a sign-in provider or `desktop:local`.
There is no notion of a **principal kind** (a person in the window, an MCP connection), no
**scopes**, and no second credential type in `get_identity`. The executor already carries `origin` (`window`, `assistant`,
`mcp:<connection>`), so the seam exists on the action side but not on the request side. Every surface needs it.

### 3.6 Secrets: a Fernet file, no keychain, no interface

Keys are encrypted with `SecretBox` (Fernet) under `MEDIA_SECRETS_KEY` on the web and a `secrets.key` file in the data
folder on the desktop. There is no `SecretStore` interface, no OS keychain (ADR-0070 decision 7 and ADR-0058 decision 4
both want one), and the Hugging Face token is read from the environment only (`desktop_hub.py`). The MCP client (OAuth
tokens, API keys for remote servers) and hosted models on the desktop all need the same thing.

### 3.7 Observability stops at the web profile

Prometheus metrics exist for the web (ADR-0048). ADR-0050 (Langfuse) is Accepted and CLAUDE.md says "instrument with
OpenTelemetry", but there is no `opentelemetry` or `langfuse` import anywhere in `services/` or `packages/`. On the desktop
the only diagnostic is `logs/engine.log`; a person reporting a bug has no "send diagnostics" button and the run events are
not kept beyond seven days.

### 3.8 The assistant is one step from the design

The assistant runs six catalogue actions through hand-written tool definitions, with `MAX_ROUNDS = 4` and an interim
sentence listing the screens (`features.json`). ADR-0071's meta-tools (`how_to`, `app_status`, `propose_action`,
`open_screen`), the action card and the evaluation gate (stage A2 and A3) are not built. Until they are, the assistant
cannot guide ("how do I") or propose with a card, and every new action means a
new hand-written tool definition, which is the drift ADR-0068 was written to stop.

### 3.9 Web-only debts that block a public service

From `docs/backlog.md` and ADR-0087: no usage events for hosted speech seconds (B1); no licence filter for a public
service; no cloud GPU (P7); no Helm `engineWorker`; the notebooks worker image never built here; Terms of Use and takedown
handling (B4, blocks release); billing (ADR-0029) proposed with no `cost_usd` on usage events; a GPU-seconds quota; the
per-resource BFF route files the catch-all made redundant (B8); the dev Postgres confusion (B12).

### 3.10 Desktop debts that block a first release

ADR-0056 "Before the first public release": signing and notarisation, installers, offline install, the updater key and feed.
Backlog D18 and D21: `window.confirm` and `window.prompt` still used in four voice screens and the chat home, and a saved chat
cannot be renamed or deleted in the window. D29: the engine bundle misses the 3D product and the prompts. The desktop
checklist (`docs/testing/desktop-window-checklist.md`) has lines that were never ticked in the real window (the model
picker, the Tauri dialogs, the title bar).

### 3.11 Documentation drift

`CLAUDE.md` still says "Status (2026-10): Phases 0-1 done (walking skeleton on the Mac)" while the roadmap and README
describe a much later state; `docs/desktop-profile.md` has grown to about 1,100 lines and is the only place several
components are described; ADR-0069 has not been amended with the eight changes `docs/spikes/mcp-s1.md` says it forces (the ADR index itself is
complete: 89 rows, 0001 to 0091).

## 4. The improvement plan, in stages

Sizes: S under a week, M one to two weeks, L two to four, for one person with tests. Each stage can be reviewed alone and
ends with something that can be checked. The first four are the foundation the agent surfaces stand on; they are small
because the seams already exist.

### Foundation (before or beside the agent surfaces)

| Stage | What | Size | Done when |
|---|---|---|---|
| **F1 Engine services** (built 2026-10-29: `EngineServices` in `wasifyai_platform_sdk/services.py` (what products reach, the old attribute names as typed fields, `need()` for one that must exist) and `ApiServices` with `services_of(request)` in `wasifyai_api/services.py`; `wasifyai_api/assemble.py` builds them (`_shared`, `_web_services`, `_desktop_services`); `main.py` 176 lines; tests hand in `Injected(...)`; 94 `getattr(state, ...)` reads became typed fields; pyright 0 errors) | A typed `EngineServices` dataclass (stores, executor, runs, index, language, models, audio, web, workers, settings, secrets) built by one `assemble(settings, profile)` function with two small profile builders (`desktop_services()`, `web_services()`); `app.state.services` is the only attribute; `RouteDeps` and `ApiToolHost` take it. `getattr(state, ...)` is replaced by typed access; a missing service is a `None` field with a type, not a surprise. No behaviour change | M | `main.py` under 250 lines; pyright finds every use; the test apps inject `EngineServices` instead of twelve keyword arguments |
| **F2 Components** (built 2026-10-29: the one installer, `wasifyai_platform_sdk/installer.py` (resumable hash-checked `download`, safe `unpack`, `make_environment` from a hashed lock, `Installer` progress and `provision.log`, `install_and_wait`); every part through it: ComfyUI and llama.cpp moved from the shell (owner's yes of 2026-10-29; `comfyui.rs`, `llamacpp.rs` and their helpers deleted), the speech runtime, lip sync, 3D, Motion graphics, the four trainers and the notebooks reader fetch through its steps and are listed as components (`components/service.py`); the ten `*_pins.json` became `components/manifests/<platform>.yaml` (installs made before are still recognised); `/components` and `component` events; one "Optional parts" list in Settings; an engine worker's `admin.fetch_engine` is `install_and_wait` over the same components; D29 fixed. Checked with real installs of ComfyUI, llama.cpp and the video trainer and with the owner's eleven parts recognised as before. Not done: the per-part cards still use their own routes for what only they show; the Models screen's file downloader is its own; no packaged-app run) | One `Component` protocol in the SDK: `manifest` (pins, sizes, hashes, platforms), `status()` (missing, installing with progress, ready, problem), `install(confirm_bytes)`, `repair()`, `uninstall()`, `fit()`, `slot_owner`, `start()`/`stop()`; one installer (download with resume and hash, unpack safely, uv environment from a hashed lock, verify, `state.json`, `provision.log`), one `/components` route family (`GET /components`, `GET/POST /components/{id}/install`, `/cancel`, `/uninstall`), one tray in the window. Move audio.cpp, MuseTalk, Pixal3D, Video Builder, the trainers and the reader onto it first; then move **ComfyUI and llama.cpp from the shell into the engine** so the shell keeps only the engine's own provisioning and the window's token. The nine `*_pins.json` become one `components.yaml` per platform (still data, still hashed) | L | every component installs through the same code and the same screen; `scripts/build-engine-bundle.sh` reads the component list (fixes D29); an engine worker installs components with the same code (`admin.fetch_engine` becomes a call to it); the Rust shell loses about 1,500 lines |
| **F3 Principals and scopes** (built 2026-10-27, ADR-0092) | `Principal(kind, tenant_id, user_id, role, scopes, origin, connection_id?)` replaces `Identity` at the request edge (`Identity` stays as the tenant-and-user pair product code uses). `get_identity` dispatches on the credential: an HS256 token (today), a connection secret (section 5). Scopes are the catalogue's groups (`make`, `library`, `notebooks`, `voices`, `models`, `admin`) plus `read`; the executor refuses an action outside the principal's scopes with `not_offered`. Audit and usage carry `origin` from the principal | S | a route called with a principal of the wrong scope answers 403 with a sentence; every existing test passes unchanged |
| **F4 Secret store** (built 2026-10-27, ADR-0092) | A `SecretStore` interface (`put(name, value)`, `get(name)`, `delete(name)`, `names()`), never a list of values; three implementations: the Fernet file (today, kept), the OS keychain on the desktop (the shell owns it, Tauri command `secret_set/get/delete`, or Python `keyring` after spike S4 decides), and env or External Secrets on the web. Web search keys, the Hugging Face token, hosted-model keys, MCP client secrets and agent tokens all go through it. Logs and audit never hold a value; a test greps for them | S | the HF token is entered in Settings, kept in the keychain, never shown again; spike S4 of the phase 4 plan is answered by this stage |

### Data and jobs

| Stage | What | Size | Done when |
|---|---|---|---|
| **J1 SQLite migrations** (built 2026-10-28: `migrate` and `Migration` in `wasifyai_platform_sdk/sqlite/engine.py`; the version is kept per store in a `schema_versions` table, not in `PRAGMA user_version`, because the stores share one file; every `ensure_tables`/`ensure_columns` became migration 1; checked on a copy of the owner's data folder, 8,162 rows in 21 tables kept, then a rename of `images.prompt` with a backup; see `docs/desktop-profile.md` "Schema changes") | A tiny runner in the SDK: `PRAGMA user_version`, a list of `(version, statements)` per store, applied at open; `ensure_tables` becomes migration 1 of each store. Destructive changes become possible on the desktop; a backup of the file is taken before a migration runs | S | a column rename on the desktop works on a data folder from last week |
| **J2 One store base** (built 2026-10-29: `wasifyai_platform_sdk/sqlstore.py`: `SqliteStoreDb` and `PostgresStoreDb` with `one`/`all`/`exec`, `connect`, `transaction`, `open_tables` (columns a later version added; an advisory lock per schema on Postgres) and `ddl_for`; the DDL is written once in types both read (`BIGINT`, `DOUBLE PRECISION`); 3D, training, notebooks, voice and Motion graphics are each one class with `in_folder(...)` and `on_postgres(...)`, all five `pgstore.py` deleted; tested on both databases and on the owner's real data) | `SqlStore` base with the dialect helpers (`to_iso`, upserts, JSON columns, `RETURNING`), so a product's store is one class with two engines, not a SQLite class and a `pgstore.py` subclass; migrate notebooks, 3D and training (the training one is being written now for the web; write it on the base) | M | one store class per product; the contract test runs on both engines |
| **J3 Jobs that survive** (built 2026-10-28: the `action_jobs` table, a job answered from its run after a restart, Stop reaching the run and an engine worker's job, a stopped clip not left "being made"; then a stopped picture or clip stopped in the media worker too (ComfyUI is interrupted), one API replica following each resumed 3D or Motion graphics job (a held Redis key per job), and speech on the web saying its place in the line while no worker has it. The voice graph was not moved to pause-and-resume: its wait already stops with the run, and the place is read from the engine queue) | Persist the executor's job handles (`action_jobs` table: id, action, principal, status, progress, result reference, engine job id); `job.status` answers from it after a restart; cancel reaches the engine queue for jobs that are engine jobs. Move the voice graph to pause-and-resume (the image pattern) so speech jobs get a queue position and Stop; make the resume of a long job safe with two replicas (a lease on the job id in Redis) | M | an MCP client that waited 25 s, lost the engine, and asks `job_status` after the restart gets the right answer; Stop on a speech run stops the worker |
| **J4 One job per person** (built 2026-10-28: `jobpolicy.py`, leases in Redis, in memory on the desktop where the limit is 0; Helm sets 1; see ADR-0088 "Built"; the load test is not done) | ADR-0088 as written: one policy function in front of the media queue, the engine queue and the product job managers; leases in Redis (and in SQLite for the desktop, where the limit is 0); Cancel and a time-out for every kind; admins and model downloads exempt; `MAX_JOBS_PER_USER` | M | the load test with several people in `docs/` shows nobody waits behind more than one job of another person |

### Observability and quality

| Stage | What | Size | Done when |
|---|---|---|---|
| **O1 Traces** (built 2026-10-29: `wasifyai_platform_sdk/tracing.py`; spans per request (`TracingMiddleware`), run stretch, node (`NodeSpans`), action and engine or media job, the context carried in `EngineJob.trace` and `JobRequest.trace`; the BFF sends a `traceparent` but exports no spans of its own; Tempo in `scripts/monitoring-up.sh`, `tracing.otlpEndpoint` in Helm; the desktop writes `<data>/logs/traces.jsonl`; Langfuse in `wasifyai_api/run_tracing.py` and `scripts/langfuse-up.sh`; ADR-0048 amended, ADR-0050 "Built". Not yet checked on staging) | OpenTelemetry in the API, the workers and the executor (one span per run, per node, per action, per engine job), exported to the Grafana stack on the web and to a local file on the desktop; Langfuse for LLM traces behind a setting (ADR-0050). Metric labels stay bounded (ADR-0048) | M | a run on the web shows as one trace from the BFF to the worker; a prompt and its cost show in Langfuse on staging |
| **O2 Diagnostics on the desktop** (built 2026-10-29: `wasifyai_api/diagnostics.py`, `POST /desktop/diagnostics`; Settings › Advanced › Diagnostics, `apps/desktop/src/diagnostics.ts`; keys and tokens blanked in the log tails) | A "Save diagnostics" button in Settings: engine log, provision log, component states, the last 50 audit entries, the machine's fit figures, no content and no secrets, as one zip the person chooses where to save | S | the zip opens and holds what a bug report needs |
| **Q1 ADR and docs hygiene** (built 2026-10-27) | Amend ADR-0069 with the eight S1 findings; amend ADR-0072 "Owner's answers" into the decision text (ADR-0072 was removed on 2026-10-28); update `CLAUDE.md`'s status line and reading table; split `docs/desktop-profile.md` into one page per area (profile, provisioning, components, the assistant, notebooks, voice, video, 3D) | S | each page under 400 lines; a new contributor can find a component's doc from its name |
| **Q2 Release gates** | Finish ADR-0056's pre-release table: signing and notarisation, the `.dmg`, the updater key and feed, an offline wheelhouse decision; fix D18 and D21 (the four `window.prompt` and `window.confirm` uses, rename and delete a chat from Recents with `NameDialog` and `ConfirmDialog`); run the whole desktop checklist in the real window and record it | M | a signed app installs on a second Mac, updates from a feed, and the checklist has no unticked line |

### Features (what a person sees)

| Stage | What | Size | Done when |
|---|---|---|---|
| **A2 The assistant guides and proposes** (ADR-0071; built 2026-10-27: meta-tools, help corpus, schema-driven card with a measured estimate, the Ask setting, result cards; A3 decides whether it is done) | The meta-tools `how_to`, `app_status`, `propose_action`, `open_screen`; help retrieval over `docs/help/` (word index plus synonyms; the notebooks' bge-small when installed); the `confirm_action` interrupt and the **action card** as an assistant-ui tool UI (schema-driven fields, estimate, badges, the setup step as a button, Run, Edit, Cancel, result); auto-run as a per-conversation setting | M | "How can I do a text to speech?" answers with the real steps and what this computer is missing; "make it say hello in a calm voice" shows a card, Run makes the speech, the card becomes a player |
| **A3 The assistant evaluation** (ADR-0071 decision 8; built and run 2026-10-27 on Qwen3 8B: 44 of 49 guide and action, 4 of 4 safety; `docs/spikes/assistant-a3.md`) | guide, action, status, safety and tool-count cases (60 to 150) on three model tiers; thresholds written before A2 is declared done; run on demand and in the release checklist | S to M | at least 90 percent on guide and action cases with the recommended local model, safety cases pass on every tier, or the card carries "this model may be unreliable" |
| **W1 Web service debts** | B1 speech usage events and a GPU-seconds quota; the licence filter for a public service; a Helm `engineWorker`; the notebooks worker image built in CI for amd64; B8 delete the redundant BFF route files; B12 one dev Postgres | M | `make kind-up` with workers; a public overlay hides non-commercial models; usage totals show speech seconds |
| **W2 Cloud GPU (P7)** | A short trial of one serverless provider with one voice or music model on a 16 GB card; the CUDA build of audio.cpp with its own lock; then images and video through Comfy Cloud first | M to L | one real speech and one real image through staging on a rented GPU, with the price per job recorded |
| **W3 Billing** (ADR-0029) | `cost_usd` on usage events from the binding metadata; the credits ledger; reserve, spend, release in the executor (one place, every surface); Stripe Checkout and the webhook; balance in the header | L | a test purchase in Stripe test mode grants credits and a paid run spends them |
| **P1 Creative Studio CS0** (ADR-0090) and **Styles S0** (ADR-0091) | The two measured spikes the owner has not yet started, in that order | S each | the numbers the ADRs ask for |

## 5. The MCP server

ADR-0069 is Accepted; spike S1 (2026-10-19) ran the `mcp` 2.3.0 SDK inside a FastAPI app of the engine's locked versions
and drove it with Claude Code 2.1.302, Codex 0.163.0 and OpenCode 1.19.3. This section is the implementation as the ADR
plus the spike's eight corrections, in the order to build it.

### 5.1 Shape

```
Claude Code / Codex / OpenCode ── stdio ──► wasify-mcp (Rust, beside the shell)
                                                 │ reads engine.json (pid, port, launcher secret; 0600)
                                                 ▼
                                   engine  POST /mcp  (Starlette Route, outside FastAPI deps)
                                       │  ASGI wrapper: bearer -> Principal(kind=connection, scopes),
                                       │  Host/Origin (SDK), body 1 MiB, rate limit, activity log
                                       ▼
                                   MCPServer (stateless_http=True): tools generated from the catalogue
                                       │
                                       ▼
                                   ActionExecutor.run_action(id, params, origin="mcp:<name>",
                                       policy=connection.policy, wait_seconds=25, on_event=progress)
                                       │
                                   approvals -> a card in the Wasify window; jobs -> handles
```

### 5.2 Engine side (`services/api/src/wasifyai_api/mcp_server/`)

| File | Does |
|---|---|
| `connections.py` | the `mcp_connections` store (SQLite and Postgres, on the J2 base): id, name, secret hash (argon2id or SHA-256 with a per-row salt), scopes, approval policy (`ApprovalPolicy.from_settings`, so the floor cannot be stored), allowed read folders and write folders, rate limit, created, last used, revoked. `GET/POST/PATCH/DELETE /connections`, `POST /connections/{id}/rotate` (the new secret is shown once), `GET /connections/{id}/activity`, `GET /connections/{id}/snippets` (section 5.5) |
| `tools.py` | one MCP tool per catalogue action whose `surfaces` has `mcp` and whose group is in the connection's scopes. Name `domain_verb` (`image_generate`, `speech_speak`, `library_search`). Input schema: `action.input.model_json_schema()`; output schema: `action.output`. Annotations: `readOnlyHint` for `read`, `destructiveHint` for `destroy`, `openWorldHint` for `leaves_device`, `idempotentHint` for reads and `job.status`. `_meta["anthropic/requiresUserInteraction"] = True` on `destroy` and `needs_consent` so Claude Code asks too. Description = `action.description` plus one sentence on how long it takes and what it returns |
| `endpoint.py` | `MCPServer("wasify", instructions=...)`, `streamable_http_app(stateless_http=True, json_response=False)`, `max_request_body_size=1 MiB`; the engine's lifespan runs `server.session_manager.run()`; one `Route("/mcp", BearerGate(StreamableHTTPASGIApp(...)))`. `BearerGate` resolves the connection by secret, builds the principal, enforces the per-connection rate limit, writes the activity entry (connection, tool, status, duration, bytes; no content), and answers 401 without a secret |
| `calls.py` | the tool body: `run_action(..., wait_seconds=25, on_event=progress)`; a **progress heartbeat every 5 s** even without a job event (Claude Code's idle limit and OpenCode's 60 s are reset by progress; Codex's explicit limit is not); results as a `dict` with the sentence in the text content and the structured output in `structuredContent` (the SDK wraps a plain `str` as `{"result": ...}`, which the clients show differently); results kept under about 10 KB (Codex cuts the middle above 12,000 characters); `preview: true` adds one downscaled image of at most 256 KB |
| `approvals.py` | `needs_approval` becomes: store the pending approval (the executor does), raise a **window event** (`approval://pending`, section 5.4), wait up to `wait_seconds`, then return `{status: "needs_approval", approval_id}` with the sentence "asked in the Wasify AI window". Tools `approval_status(approval_id)` and `job_wait(job_id, seconds)` follow it. On the 2026-07-28 revision with `elicitation` declared (Claude Code today), the same tool may also return `input_required` as a courtesy; a cancelled or declined elicitation means "no answer yet", never "denied" |
| `files.py` | ADR-0069 decision 6 and spike S2 (to run first): paths resolved with symlinks followed, must be inside a folder of the connection, `..` refused, a 20-hostile-path test; `library_export(id, path)` writes only inside a write folder; a file input (`speech_transcribe(path=...)`) must be inside a read folder and is copied into the person's uploads through the existing hardening |

The 2026-07-28 revision needs `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` headers that a stdio message does not
carry; the launcher derives them (5.3). `stateless_http=True` means the server cannot ask a legacy client anything mid-call;
that is accepted (approvals are in the window anyway).

### 5.3 The launcher (`apps/desktop/src-tauri/src/bin/wasify_mcp.rs`)

About 300 lines of Rust, built with the shell and placed beside it in the bundle; the Python prototype in
`~/Projects/wasifyai-spikes/s1/launcher.py` is the reference. It is **not a byte pipe**; what it must do, each found by
running the three clients:

1. Open `engine.json` with `O_NOFOLLOW`, check on the **open descriptor**: regular file, owned by this user, mode 0600, the
   folder not writable by others, `host` loopback, `pid` alive. Read it on **every request**, so an engine restart (new port,
   new secret) needs no client restart.
2. Derive the three headers from the JSON-RPC body (`params._meta["io.modelcontextprotocol/protocolVersion"]`, `method`,
   `params.name`); for legacy clients carry `Mcp-Session-Id` and `MCP-Protocol-Version` from the `initialize` answer.
3. Stream: an SSE response's `data:` events go to stdout one per line; `notifications/cancelled` from the client closes the
   in-flight HTTP request (that is how a cancel reaches the engine).
4. With the app closed, answer `initialize`, `server/discover`, `tools/list` and `tools/call` itself with one tool,
   `app_status`, whose result says "Open Wasify AI, then restart your agent" (the envelope on 2026-07-28 needs
   `resultType`, `cacheScope`, `ttlMs`). Whether the three clients refresh the tool list after the app starts is **not
   verified** (S1 open problem 6); test it in M1 and change the sentence if they do.
5. `WASIFY_ENGINE_JSON` overrides the file's location (teams that commit a `.mcp.json`).

The shell writes `engine.json` (atomic rename, 0600) when the engine answers `/health`, and deletes it on stop. Its content
is the **launcher connection's** secret, which the shell asks the engine to create on first use of "Let other apps use
Wasify AI".

### 5.4 The window

- **Settings > Connections** (`packages/ui/src/connections/`, shared with the web): the switch "Let other apps use Wasify
  AI", the connections list (name, scopes as plain sentences, approval setting, folders, last used, revoke, rotate), the
  activity log, and "Copy for Claude Code / Codex / OpenCode". The snippet is generated by the engine from the launcher's
  real path, not typed; for Codex it offers `default_tools_approval_mode` as a choice, because Codex blocks tools without
  `readOnlyHint` otherwise.
- **The approval card**: the engine raises `approval://pending` on the desktop event channel (a small SSE route
  `GET /desktop/events` the window keeps open; the shell shows a system notification when the window is in the background).
  The card says who asks ("Codex wants to make a 30-second song"), shows the parameters, the consent statement if any, and
  Allow once / Always for this connection (never for `destroy` or `needs_consent`) / Deny; it calls
  `POST /actions/approvals/{id}` which is `executor.decide_approval`. Jobs an agent started show "from Codex" on the
  screens that list jobs and can be cancelled by the person.

### 5.5 Config snippets the engine generates (verified in S1)

```json
{"mcpServers": {"wasify": {"type": "stdio",
  "command": "/Applications/Wasify AI.app/Contents/MacOS/wasify-mcp", "args": []}}}
```
```toml
[mcp_servers.wasify]
command = "/Applications/Wasify AI.app/Contents/MacOS/wasify-mcp"
default_tools_approval_mode = "approve"
```
```json
{"mcp": {"wasify": {"type": "local",
  "command": ["/Applications/Wasify AI.app/Contents/MacOS/wasify-mcp"]}}}
```

The HTTP forms (a fixed port, off by default) put the secret in an environment variable the person names, never in the file.

### 5.6 On the web: the same server as a remote MCP endpoint

A remote MCP endpoint on the hosted API (`POST /mcp`) needs a credential other than a browser session. With API keys
dropped (section 8, 2026-10-28), that credential is OAuth 2.1 with Client ID Metadata Documents (ADR-0069
"Alternatives"); the SDK has `auth=` for it (**not tested** in S1). Approvals on the web go to the person's browser session (the same card, over the BFF's SSE).

### 5.7 Stages, with the spike's corrections applied

| Stage | What | Size | Done when |
|---|---|---|---|
| **S2** (spike; done 2026-10-27, `docs/spikes/mcp-s2.md`) | the file rules under 20 hostile paths; macOS permission for Documents and Desktop | S | the test passes; the rule text goes into ADR-0069 |
| **M1 make-only** (built 2026-10-27; ADR-0069 "Built"; left: the real clients end to end, the bundle, M2's files) | F3, the store, the endpoint, the `make` and `models` groups plus `app_status`, `job_*`, `approval_status`; the launcher; Settings > Connections; the approval card; the conformance suite for 2026-07-28, 2025-11-25 and 2025-06-18 with the SDK client; recorded sessions of the three clients replayed in CI | M | each of the three clients, installed from the Settings button, makes a picture and a speech file, finds a job that outran its limit through `job_status`, and an approval shows a card in the app and waits |
| **M2 the rest and files** (built 2026-10-27; ADR-0069 "Built"; left: previews and resource links) | `library`, `notebooks`, `voices`, `audio`, `dub`, `audiobook`, `lipsync`, `admin` groups; folders; previews; scope presets ("Make things", "Make and use my library", "Everything") | M | an agent transcribes a file under its folder and cannot read outside it; delete and clone need the window; a library search outside the scope is refused |
| **M3 hardening and reach** (built 2026-10-27; ADR-0069 "Built"; left: notifications (a dependency), Windows and Linux builds, the library card's label, the speech self-test) | per-connection quotas; the "from Codex" label; notifications; the fixed-port HTTP option; a generated skill file for Claude Code; Windows and Linux launchers; the security review against the phase 4 checklist (`docs/mcp-security-review.md`) | M | the review has no open row; the self-test makes a speech file through the launcher |

New dependency to approve: `mcp==2.3.0` and the eight packages it brings (`mcp-types`, `sse-starlette`, `jsonschema`,
`jsonschema-specifications`, `referencing`, `rpds-py` (compiled), `attrs`); check the hashed engine bundle resolves them.

## 6. The MCP client

ADR-0070 is Accepted and staged last on purpose: it brings code execution, data leaving and prompt injection into a
local-first app. The design below keeps the ADR's twelve decisions and adds the pieces the code already has.

### 6.1 Where it lives (`services/api/src/wasifyai_api/mcp_client/`)

| File | Does |
|---|---|
| `servers.py` | the `mcp_servers` store: name, transport (`http` or `stdio`), address or command, environment **names**, trust level (`ask`, `trusted_read_only`, `blocked`), allowed tools, added by and when, health (failures in a row), "keep the content" flag. Added only in Settings; no route an action or a model can reach |
| `session.py` | the SDK's client over Streamable HTTP (2026-07-28 with fallback to 2025-11-25) and stdio; lazy connect; `tools/list` cached for its `ttlMs`; per-call timeout (60 s default, per server); at most four calls in flight; three failures mark it unhealthy |
| `guard.py` | SSRF (https only except loopback; private and link-local refused unless the person typed exactly that address; no cross-host redirect with credentials; certificate pinning of the credential's host); result limits (20,000 characters, control characters stripped, images as thumbnails only, links never followed); the labelled block the model sees |
| `process.py` | stdio servers: a typed confirmation (the person types the server's name), the full command and environment shown, a **minimal environment** (only the names listed; no engine secrets), working folder under app data, idle stop after ten minutes, stop on quit, output size-limited and logged |
| `external.py` | the bridge to the catalogue (6.2) |
| `secrets` | through F4's `SecretStore`; OAuth 2.1 with PKCE, a loopback callback, Client ID Metadata Documents first, Dynamic Client Registration as fallback |

### 6.2 Remote tools go through the executor too

Do not build a second approval path. Add **one catalogue action**, `external.call`, with a `CallBinding` that looks up the
server and tool, validates `arguments` against the tool's schema (the SDK brings `jsonschema`), and calls it. Its effect
and flags are **computed per call** from the server's trust and the tool's annotations: `read` without `leaves_device`
only when the server is `trusted_read_only` and the tool says `readOnlyHint`; otherwise `make` with `leaves_device`. The
executor then does what it does for everything: approval by the conversation's policy, the floor, audit (server and tool,
no content), a usage event, `origin`. `external_tools(query)` is a `read` action that searches the connected servers' tool
descriptions with the local word index (and real embeddings when the notebooks' model is installed) and returns at most
five, so the model's tool list stays the same size whether zero or forty remote tools exist (ADR-0070 decision 8).

### 6.3 The taint rule, in the assistant graph

The graph already has the mechanism for web results: `taint_outcome` marks an outcome untrusted and the turn then asks
before anything is made (the checklist's section 3 tests it). Extend it: a result from `external.call` sets `tainted` in
the run state; while it is set, the executor is called with a policy of `make="ask", change="ask"` whatever the
conversation chose; the card says **where the request came from** ("after reading a result from `github`").

### 6.4 Tests

A fake MCP server in the test suite that can act badly on demand: a 5 MB result, instructions hidden in a result, a slow
answer, a redirect to another host, a server that lies about `readOnlyHint`, a stdio server that prints secrets from its
environment. Each case has an assertion that nothing was called, leaked or run.

### 6.5 Stages

| Stage | What | Size |
|---|---|---|
| **C1 read-only** (built 2026-10-27; ADR-0070 "Built"; left: OAuth, a real model and a real server) | the store, HTTP and stdio, the keychain, OAuth, `external_tools` and `external.call`, Settings > "Tools from other apps", trust `ask` and `blocked`; the malicious fake | M |
| **C2 taint and trust** (built 2026-10-27; ADR-0070 "Built"; the run is `docs/spikes/assistant-c2.md`) | the taint rule with provenance on the card; `trusted_read_only`; the stdio confirmation and minimal environment; the evaluation with 5 and 40 remote tools per model tier, which decides whether local models are offered remote tools at all | M |
| **C3 reach** (built 2026-10-27; ADR-0070 "Built"; left: the tasks extension, the sandbox (S5 not run), OAuth) | resources attached to a message; prompts as templates; elicitation as a form card; the tasks extension when a server offers it; import from Claude Code's `.mcp.json`, Claude Desktop's and Codex's `config.toml` (each definition shown and confirmed); a macOS sandbox for stdio if spike S5 says yes | S to M |

The fallback ADR-0070 names stays real: if C2's evaluation shows the local model cannot choose among remote tools safely,
remote tools are offered only with a hosted or larger model and Settings says so.

## 7. The agent on Hermes (dropped)

**Dropped 2026-10-28 (owner).** An agent for long tasks on Hermes Agent (ADR-0072, spike G0) needed a component of about
660 MB (a pinned environment of 379 MB plus a 272 MB cache), which is not practical to add to the app. ADR-0072 and
`docs/spikes/agent-g0.md` were removed, and stages G1 to G4 are no longer planned. The assistant (ADR-0071) with its cards,
the MCP server (section 5) for outside agents such as Claude Code, and the MCP client (section 6) stay as they are.

## 8. API keys (dropped)

**Dropped 2026-10-28 (owner): "We will not do it."** API keys for the products (stages K1 and K2: `wsk_` keys with
scopes, `/v1` routes for actions, jobs, the library and uploads, the key screens) are not planned. ADR-0092 keeps its
built parts (principals, scopes and the secret store, F3 and F4); its API-key decision was taken out. Outside programs
reach the app through the MCP server (section 5).

## 9. Order, dependencies and sizes

```
F1 services ─┐
F2 components ┼─► (any order, small)          A2 assistant ──► A3 evaluation
F3 principals ┼──► M1 MCP server ──► M2 ──► M3          │
F4 secrets ───┘        │                                 ▼
J1 migrations ─► J2 base ─► J3 jobs ─► J4 one job per person
                       │
                                          C1 MCP client ──► C2 ──► C3   (last; needs A2, F4)
O1 traces, O2 diagnostics, Q1 docs, Q2 release gates, W1 to W3, P1: beside the rest, as time allows
```

Suggested order for one person, three months, desktop first as the owner wants:

| Weeks | Work | Why then |
|---|---|---|
| 1 to 2 | **F3, F4, Q1**, then **A2** started | the two small seams every surface needs; A2 is what the owner sees first and what the agent hands off to |
| 3 to 4 | **A2** finished, **A3**, **S2**, **M1** started | the card path proves the catalogue with real people; M1 reuses the same approvals |
| 5 to 6 | **M1** finished, **J3**, **F1** | the three real clients make things; job handles survive restarts before agents depend on them |
| 7 to 9 | **F2** | one installer for the nine components (the agent on Hermes that was planned here was dropped on 2026-10-28) |
| 10 to 11 | **M2** | files and private groups for agents (API keys, planned here, were dropped on 2026-10-28) |
| 12 | **Q2**, **O2**, **M3** | the release gates for a signed desktop app with the server on |
| after | **J1, J2, J4, O1, W1 to W3, C1 to C3, P1** | the web service, the client last as ADR-0070 says |

Sizes add up to about 14 weeks of M and S stages for the desktop path; the web list (W1 to W3, J4) is another two
months and depends on the owner's hosting answers (P7).

## 10. Decisions the owner must make

1. **Accept the order above**, in particular A2 before M1 (the card first) and the MCP client last.
2. **New ADR-0092 (principals and scopes)**: scopes as the catalogue's groups. Its API-key part was dropped on 2026-10-28.
3. **Dependencies to approve** (CLAUDE.md "Ask before"): `mcp` 2.3.0 and its eight packages; `argon2-cffi` for connection secret hashing (or
   SHA-256 with salt and no new package); `keyring` or the shell as keychain owner (spike S4
   is answered by F4; recommend the shell, which already signs tokens and runs as the app's identity); OpenTelemetry SDK and
   exporter for O1.
4. **Move ComfyUI and llama.cpp installation from the shell to the engine** (F2). It changes `apps/desktop` (AGPL) and the
   engine (Apache); the installer logic was written for this engine, so the licence boundary does not move, but the owner
   should say yes before 1,500 lines leave the shell.
5. **A hosted text provider on the desktop with the person's key**: the ADR-0056 decision 4 "cloud provider with the
   user's key" was never built; the chat would use it.
6. ~~The agent's web search without a key~~ Dropped with the agent (2026-10-28).
7. **Names, once more before people have configs**: the launcher `wasify-mcp`, the tool names `image_generate` and the
   rest, the scope words.
8. **The remote MCP on the web** with OAuth 2.1 (5.6), since API keys were dropped.
