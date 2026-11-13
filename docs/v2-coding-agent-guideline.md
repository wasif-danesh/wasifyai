# Wasify AI v2: a guideline for the coding agent

Version 2, written 2026-11-13. This is a guideline, not a decision: nothing here is built and no ADR is
accepted. It answers the owner's request to turn Wasify AI into a coding agent with the features of
Claude Code or Codex (build a desktop, web or mobile app, build a 2D or 3D game, analyse and fix a
codebase; a web browser, a file browser, a terminal, file changes, and a Scheduled module that runs
agents on a timer).

**What changed from version 1.** Version 1 advised building our own agent core and gave OpenHands one
line: "measure its SDK in a spike". That was too thin. The owner asked for a proper read of OpenHands,
and it changes the main advice. OpenHands today is not a small library. It is a full product in four
parts that already does most of the roadmap. The new advice is to build on its engine and spend our
time on what it lacks.

It is based on:

- the owner's rough roadmap ("Wasify AI V2 Roadmap", seven phases);
- Wasify's own code as it is today;
- **OpenHands, read in full on 2026-11-13**: the clone at `~/Projects/OpenHands` (commit `754abee4f` of
  2026-11-12), the Python packages the running app installed on this Mac (Agent Server, SDK and tools
  1.62.0; automation 1.32.1), the running app on `localhost:8000`, and its API description (151 paths);
- the source of OpenCode (`~/Projects/opencode`), and the public repositories and documents of Codex
  CLI, Hermes Agent, Aider, Cline, Goose, pi, the Agent Client Protocol and Claude Code.

The folder `~/Projects/ClaudeCode` holds leaked Claude Code source. It was not read.

## 1. In short

1. **Build on OpenHands' engine. Do not write our own agent core.** Its Agent Server gives the loop, the
   tools, sessions, long-session handling, sub-agents, skills, plugins, connectors, hooks and outside
   agents, tested by a large community. Writing these again would take months and stay behind.
2. **Run it as an optional part, beside our engine.** A separate program in its own environment, started
   and stopped by Wasify, reachable only from this computer. People who never code never download it.
3. **Our screens, their engine.** The session view and the workspace panel are built in Wasify's own
   design, fed by the Agent Server's API. Their ready-made screens are the fallback, not the plan.
4. **Spend our time on the five things OpenHands does not have** (section 4): a sandbox on the person's
   own computer, undo, our approval rules, Wasify's products as tools, and everything that helps people
   who are not developers.
5. **Scheduled comes from their automation service**, behind our own Scheduled screen, with our
   unattended rule on top.
6. **Models and the roadmap order stay as in version 1**: cloud first for coding, a measured gate for
   local models, the coding core and the panel before vision, games and plugins.
7. **The price is real and the owner should accept it knowingly**: about 600 MB for the optional part
   (the size class that ended Hermes on 2026-10-28), a project that ships several releases a week, and
   a second safety system beside the action catalogue.

## 2. What OpenHands is today

The repository `OpenHands/OpenHands` (93k stars) no longer holds the agent. It holds the screen. The
product is four parts in four repositories:

| Part | What it is | Size read |
|---|---|---|
| **Agent Canvas** (`OpenHands/OpenHands`) | The screen: React 19 and TypeScript. Shipped as an npm program, a Docker image and an Electron desktop app. Its pieces can also be imported into another app | 210,000 lines |
| **Agent Server and SDK** (`OpenHands/software-agent-sdk`) | The engine, in Python: the agent loop, the tools, sessions, and a REST and WebSocket API over them | 145,000 lines |
| **Automation** (`OpenHands/automation`) | A Python service that starts agent runs on a timer or when an outside event arrives | 38,000 lines |
| **Extensions** (`OpenHands/extensions`) | Public skills, plugins and automation templates | a package |

What the running app on this Mac is: a Node launcher that starts the Agent Server (`127.0.0.1:18000`),
the automation service (`:18001`), the screen (`:3001`) and a small proxy that joins them on `:8000`.
The two Python services were downloaded by `uv` on first start.

### What the engine does (read in the code)

| Area | What is there |
|---|---|
| Tools | Terminal (tmux, plain subprocess, or PowerShell on Windows), file editor, `apply_patch`, `glob`, `grep`, a task list, a browser the agent drives (browser-use), a planning editor, sub-agents (`task`, `delegate`, child conversations) |
| Sessions | Kept on disk as events; resume, fork, pause, interrupt, condense; a stuck detector; a step limit and a cost limit per run |
| Long sessions | A condenser that summarises old turns with a model |
| Models | Any provider through LiteLLM; saved model profiles; switching model inside a session; a ChatGPT subscription login |
| Safety | Each action gets a risk (low, medium, high) from analysers: the model's own estimate, patterns, and rules that parse the shell command (fetch-then-run, raw disk writes, catastrophic deletes). A confirmation policy then decides: always ask, never ask, or ask when risky |
| Where it works | The local folder, a Docker container per session, Apptainer, Kubernetes, or their cloud. A git worktree per session on request |
| Outside agents | Claude Code, Codex, Gemini CLI, Pi, OpenCode and any custom agent over the Agent Client Protocol |
| Skills and plugins | The Agent Skills format, plugins, a marketplace, hooks with the same events as Claude Code (before a tool, after a tool, on prompt, on start, on stop) |
| Connectors | MCP servers with sign-in, and a library of about thirty ready ones (GitHub, Slack, Linear, Figma and others) |
| Secrets | A store, with secrets hidden in output |

### What the screen does (seen in the running app)

- A chat per session, a list of sessions grouped by folder, a command search.
- A side panel with tabs: **Files** (tree and viewer), **Commits** (changes and diffs from git),
  **Planner**, **Terminal**, **Browser**, **Usage**.
- **Automate**: a dashboard of automations and runs, a set-up screen (schedule or event; once, hourly,
  daily, weekdays, weekly or custom; time zone; prompt; repositories; plugins; a test run), templates.
- **Customize**: skills, plugins, connectors, and "apps" (extensions that add pages).
- Settings for models, the agent, the condenser, verification, secrets.

### How it lines up with the roadmap

| Roadmap phase | OpenHands |
|---|---|
| 1. Vision in the loop and Blender | Not there (the agent's browser takes pictures; nothing for Blender) |
| 2. Outside agents | **There**, five agents and custom ones |
| 3. Workspace panel | **There**, with two limits (section 4) |
| 4. Coding-agent core | **There** |
| 5. Skills and connectors | **There** |
| 6. Games | Not there |
| 7. Plugin platform | **There** (plugins, a marketplace, extensions that add pages) |
| Scheduled | **There** (the automation service) |

Five of the seven phases, and Scheduled, exist. That is why the plan changes.

## 3. The recommended shape

```
window (Tauri)                 Wasify engine (Python)                coding engine (optional part)
┌────────────────────┐         ┌───────────────────────────┐        ┌──────────────────────────────┐
│ session view       │◄───────►│ coding sessions: start,   │◄──────►│ OpenHands Agent Server       │
│ changes  files     │         │  send, approve, stop      │  REST  │  loop · tools · sessions     │
│ preview  scheduled │         │ approval cards, audit     │  + WS  │  sub-agents · skills · hooks │
└───────┬────────────┘         │ keys, model choice        │        │  outside agents (ACP)        │
        │ PTY (Rust shell)     │ jobs, tray, search        │        │  + Wasify policy module      │
        ▼                      │ MCP server (the catalogue)│◄───────│  (calls Wasify's actions)    │
  person's terminal            └───────────────────────────┘  MCP   │ automation service           │
                                                                    └──────────────┬───────────────┘
                                                              inside an operating-system sandbox:
                                                              writes only in the open workspaces
```

**Why a separate program and not their Python library inside our engine.**

- No clash of packages. Their environment has 386 packages; ours has none of LiteLLM, tree-sitter, the
  tmux bindings or browser-use.
- Nobody pays for it who does not use it. It installs like the training parts do, on first use.
- We get their whole API: sessions, events, files, git changes and diffs, skills, plugins, connectors.
  With only the library we would write that server again.
- A separate program can be put inside a sandbox as a whole (section 5).
- The same shape works on the web later: a worker runs the same server in a container.

**Why our screens and not theirs.**

- The two stacks fit (both React 19, Tailwind 4.3.3, Vite 8), and their pieces are made to be imported:
  `ConversationView`, `FileExplorer`, `TerminalPanel`, `BrowserPanel`, with their own scoped styles.
- But they bring a second look (HeroUI), a second chat beside ours, fonts loaded from Google at run
  time, analytics code that the host must switch off, and a tie to a screen that ships four releases a
  week. They are tested in Chromium; our window is WebKit on the Mac.
- The session view and the panel are the face of the product. Wasify already has the chat on
  assistant-ui fed by an outside store, approval cards, a job tray and a design system with an
  accessibility check. The Agent Server sends typed events; showing them in our chat is the smaller job.
- So: ours first. In the spike we also import one of their pieces into the Tauri window, to know the
  real cost of the fallback.

**How Wasify stays in charge.**

- Wasify starts every session and sets its confirmation policy. A confirmation arrives as an event, is
  shown as our approval card, and our answer is sent back (`respond_to_confirmation`).
- A small Wasify module is loaded into the Agent Server (it supports extra modules at start). It adds
  our rules by pattern as one more analyser, and a hook that refuses what a rule denies.
- Wasify's own products reach the agent through our MCP server, so `image.create` or `speech.speak`
  called from a coding session still passes our executor, our card and our audit.
- Starting, sending to, approving and stopping a session are catalogue actions (ADR-0068). The tool
  calls inside a session are OpenHands events, kept in its store and mirrored into our audit.

This is two layers, not the single executor version 1 promised. It needs an ADR that says so plainly.

## 4. What OpenHands does not have

These are where our work goes. Each was checked in the code or the running app.

| Gap | What I found | What we build |
|---|---|---|
| **A sandbox on the person's own computer** | The local workspace runs commands straight on the host. Their answer is Docker, and their own README warns that local mode has full access to the files | Start the Agent Server inside an operating-system sandbox (section 5). People who are not developers will not install Docker |
| **Undo** | Only "undo the last edit of this file" in the file editor. No checkpoints, no rewind. The Commits tab needs a git repository | Checkpoints per turn on git that Wasify manages for the person (section 5) |
| **Rules by pattern** | Risk is a level, not a rule. No "allow `git *`, ask for `rm *`, never touch this folder" | The policy module (section 3) |
| **Approvals for outside agents** | Every permission request from an outside agent is approved automatically | Outside agents run only in "work on its own" mode inside the sandbox, and the screen says so |
| **A terminal for the person** | The Terminal tab is read-only: it shows what the agent ran | Our own terminal (a PTY in the Rust shell), as in version 1 |
| **A live preview** | The Browser tab shows pictures of the agent's browser. The person cannot use it | Our Preview tab (a Tauri child webview), as in version 1 |
| **Help for people who are not developers** | It assumes Node, git, `uv` and often Docker are installed | Starters, managed tools, "run and see" (section 8) |
| **Wasify's products as tools** | Not its business | Our MCP server; assets land in the project |
| **Unattended runs that are safe on a home computer** | Automation runs use the same full access as a session | The unattended profile (section 7) |
| **Vision with Blender, and games** | Not there | Roadmap phases 1 and 6, after the preview stage |
| **Windows without Docker** | The SDK has a PowerShell terminal. Their Windows guide covers Docker only, and containers per session need WSL 2 | Measure it natively in the spike |

## 5. Safety

The aim from version 1 stands: **a boundary the model cannot cross, so that inside it little needs
asking.** How it is reached changes.

1. **Sandbox around the whole coding engine.** Because the Agent Server is a separate program that
   Wasify starts, Wasify can start it inside the operating system's sandbox: it may write only in the
   open workspaces and its own data folder, and may not read key stores or the app's data. macOS has
   `sandbox-exec`. Linux needs bubblewrap. Windows has no simple equivalent, so Windows stays in "Ask
   me" until it has one. This is coarser than a sandbox per command, and far simpler. It is the largest
   unknown and the first spike.
2. **Rules.** The policy module turns our rules into a risk: reading in the workspace is low, a denied
   path or command is refused by the hook, the rest follows the mode.
3. **Their analysers.** Kept switched on. The shell rules that catch fetch-then-run and catastrophic
   deletes are good work we should not rewrite.
4. **Approval and taint.** What must be asked shows our card. The taint rule stays ours: after the
   session has read outside content, actions that leave the device or destroy something ask.

Three modes for the person, unchanged in words:

| Mode | In OpenHands terms | Needs |
|---|---|---|
| Plan | Their planning agent: reads, writes only the plan | nothing |
| Ask me | Confirmation policy "always ask" | nothing |
| Work on its own in this folder | "Ask when risky", inside the sandbox | the sandbox on this system |

**Undo.** A workspace Wasify creates is always a git repository, with git as a managed tool the person
never sees. After each turn that writes, Wasify saves a checkpoint on a hidden branch. The Changes tab
reads the Agent Server's git changes and diffs; "undo this turn" returns to the checkpoint. This is how
Cline and Claude Code do it, and it also covers what shell commands change. It replaces version 1's own
snapshot store. A folder the person opens that is not a git repository gets the same hidden checkpoints
without changing what the person sees.

Other points, kept from version 1: secrets stay out of the agent's shell; files in a cloned project
(`AGENTS.md`, skills, hooks, connector settings) are outside content until the person trusts the
workspace; this is security, not censorship (ADR-0094).

Their analytics are off for us: the Agent Server's exporter is "none" unless switched on, and we do not
ship their screen.

## 6. Models

Unchanged in substance from version 1.

- **Measured.** The local default (Qwen3 8B) passes 50 of 78 on Wasify's tool evaluation; the
  real-window walk on Qwen3.8 27B did 19 of 25. Coding sessions are far longer than those.
- **Cloud first for coding**, with the person's key (ADR-0095, ADR-0100). Recommended: Claude Opus 5.5
  for the main loop, Sonnet 5.5 as the cheaper choice, Haiku 5.5 for side work (titles, the condenser,
  the explorer). List prices on 2026-11-03 per million tokens, in and out: Opus 5.5 $4 and $20,
  Sonnet 5.5 $2 and $10, Haiku 5.5 $0.10 and $0.50.
- **How the key reaches the engine.** Wasify keeps the keys. It passes the chosen model and key to the
  Agent Server per session. The person never fills in OpenHands' own model settings.
- **Changed: the model layer is theirs.** OpenHands calls models through LiteLLM, with prompt caching
  for Claude models. Version 1's separate native path for Claude is dropped.
- **Local models behind a gate.** The Agent Server can call our local llama.cpp server as an
  OpenAI-compatible address. It is offered for coding only when it passes the coding evaluation on this
  computer.
- **Show the cost.** The engine reports cost per session and accepts a limit per run.

## 7. The Scheduled module

**Use their automation service for agent schedules.** What it does today:

- a schedule (cron with a time zone) or an event (GitHub, Slack, Jira, Bitbucket, Azure DevOps and a
  custom webhook);
- the action is a prompt for an agent, with a model, repositories and plugins;
- a draft and a test run before it is switched on;
- each run in its own folder, with its session, its cost and its result kept;
- limits: 10 minutes by default, 30 at most; a watchdog for stuck runs; a schedule that fails three
  times is switched off with the reason shown;
- a run missed while the service was off fires once when it is back, not once per missed slot;
- on one computer it keeps everything in a SQLite file.

What Wasify adds:

- **Our Scheduled screen** over its API: the list, the next run, the last result, pause one, pause all,
  run now.
- **The unattended rule.** A scheduled run uses a Wasify agent profile: anything that would ask is
  refused and written in the report. It never waits for a person and is never allowed silently.
- **Work on a copy.** A run on a project uses a git worktree and ends as changes to review.
- **One at a time**, after any job the person started (the memory budget).
- **The app must be running.** "Keep running in the menu bar" and "start when I log in". A sleeping
  laptop is not woken.

What is left out of the first version: event triggers. They need an address the outside world can
reach, which a desktop app does not have. They fit the web version later.

Not covered: scheduling a plain Wasify action with no agent ("make this picture every Monday"). Through
the automation service that would spend model tokens for nothing. If wanted, it is a small scheduler of
our own over `action_jobs`, later.

## 8. Building apps and games for people who are not developers

Unchanged from version 1, and now most of what makes Wasify different from OpenHands itself.

1. **Starters, not blank folders**: a web app, a desktop app, a mobile app, a 2D game, a 3D game, one
   tested stack each.
2. **Managed tools**: Node and git installed as optional parts, pinned, never on the person's `PATH`.
   Outside agents need Node too (they start through `npx`).
3. **Run and see**: one button starts the project in the Preview tab. The agent looks at the same page.
4. **Assets from Wasify**: "a jumping fox sprite", "a 10 second loop for the menu", "a 3D crate" call
   the products the app already has.

Order: web apps, then 2D and 3D games in the browser, then desktop apps, then mobile apps, then Godot
and Blender through their MCP servers.

## 9. Changes suggested to the V2 roadmap

| Roadmap | Suggestion | Why |
|---|---|---|
| Phase 1: vision in the loop and Blender | After the preview stage | Vision pays most when the agent can look at the app it just built |
| Phase 2: outside agents | Comes with the engine. Our work is the choice of agent, its credentials, and the sandbox-only rule | Five agents already work. Hermes stays out (2026-10-28) |
| Phase 3: workspace panel | Keep, in our design: Changes first, then Files, Terminal, Preview. The editor last | The data comes ready from the Agent Server |
| Phase 4: coding-agent core | Replace "build the core" with "run OpenHands' Agent Server as an optional part" | Section 2 |
| Phase 5: skills and connectors | Screens over the engine's skills, plugins and connector library | Already built there |
| Phase 6: games | Keep. Browser games before Godot | The preview is already there |
| Phase 7: plugin platform | Use the engine's plugins and marketplace. Decide later about extensions that add pages | They need OpenHands' own screen |
| Scheduled | The automation service behind our screen | Section 7 |
| The web | Desktop only in v2 | The engine is ready for it (a container per session), the cost and risk are ours |

## 10. Stages and gates

Each stage ships on its own. A gate is a measured result that must hold before the next stage starts.
Each stage with a screen starts with a mockup.

| Stage | What is built | Gate to pass |
|---|---|---|
| **C0 Spikes** (outside the repository) | 1. The Agent Server installed and started by a script the way Wasify would: size, start time, memory. 2. One session driven from Python over its API, with a cloud key and with our local llama.cpp. 3. A coding evaluation of about 30 tasks run through it, per model. 4. The server inside the sandbox on macOS and Linux; a native run on Windows. 5. The policy module: a rule that denies, and a confirmation shown and answered. 6. Wasify's MCP server as tools in a session. 7. Its events in our chat; one of their screen pieces in the Tauri window. 8. The automation service through sleep and restart. 9. A PTY and a child webview in Tauri. 10. A checkpoint and an undo on a hidden git branch | A go or no-go written for each. The first, the fourth and the fifth decide whether this plan stands |
| **C1 The engine in the app** | The "Coding" optional part, start and stop, the key hand-over, workspaces, the session view, the Files tab, Plan mode | "Analyse this codebase" gives a correct map of three real projects. Nothing is written anywhere |
| **C2 Edits with undo** | The Changes tab, managed git, checkpoints, Ask me mode with our cards, the policy module | Every change in the evaluation can be undone exactly. No write outside the workspace in a hostile test |
| **C3 Commands** | The sandbox, the third mode, the person's Terminal tab, background processes shown | Bug-fix tasks pass with tests run by the agent. The hostile test cannot write outside |
| **C4 Preview and assets** | The Preview tab, managed Node, the first starter, Wasify's products as tools | "Build a to-do web app with a logo" ends in a running app with a picture made by Wasify, on a clean computer |
| **C5 Long sessions** | The engine's condenser, sub-agents and task list shown in our screen; sessions in the job tray; cost and limits | A two-hour session keeps working after condensing and after an app restart |
| **C6 Scheduled** | The automation service, the unattended profile, the Scheduled screen, menu bar and start at login | A nightly run on a real project for a week: no missed or doubled run, no change outside its copy |
| **C7 Outside agents** | Choosing Claude Code, Codex and the others; their credentials; sandbox-only | Two outside agents each finish a task with our Changes tab |
| **C8 Skills and connectors** | Screens for skills, plugins, hooks and the connector library | A public skill and one connector work unchanged |
| **C9 Apps and games** | The other starters, playtests by pictures, then Godot and Blender | Each starter builds and runs from one sentence on a clean computer |
| **C10 Plugins** | The roadmap's phase 7 | To be set later |

Compared with version 1: C5, C7 and C8 shrink from building to showing, and C1 to C3 lose the engine
work. The gates did not get easier.

## 11. What it costs

| Cost | What I measured or read | What reduces it |
|---|---|---|
| **Size** | The Agent Server's environment is 604 MB on this Mac (LiteLLM 124 MB, Google's API client 110 MB, gRPC 41 MB, AWS 25 MB). Automation as a second environment is 425 MB, mostly the same packages; in one shared environment it adds little. Wasify's own engine is 495 MB | An optional part, installed on first use. Never in the installer. The owner refused a 660 MB part once; this is the same size and is the owner's call |
| **Pace** | Four releases of the screen in the week before 2026-11-12; 504 commits in 30 days; the screen already refuses servers older than 1.59 | Pin one version of the engine. Upgrade on our schedule. A test for each of the roughly twenty endpoints we use |
| **Two safety systems** | The action executor does not see the engine's tool calls | The policy module, the sandbox, our cards, the audit mirror. An ADR that says what is and is not under ADR-0068 |
| **Prerequisites** | Their launcher wants Node 24 and `uv`; the best terminal wants tmux; outside agents want `npx` | Wasify starts the server itself with its own installer. Managed Node. tmux measured in the spike (there is a plain fallback) |
| **Their defaults** | Full access to the host in local mode; outside agents approved automatically | Sections 4 and 5 |
| **Dependence** | The engine's direction is set by a company with a paid cloud | The parts we use are the open, self-hosted ones. Our screens and our policy are ours, so the engine could be replaced behind them |

## 12. New dependencies to approve

None is added without the owner's yes.

| For | Dependency | Stage |
|---|---|---|
| The coding engine | `openhands-agent-server`, `openhands-sdk`, `openhands-tools` as an optional part | C1 |
| Its API from our engine | Our own small client (REST and WebSocket), or `@openhands/typescript-client` in the window | C1 |
| Undo and the Changes tab | git as a managed tool | C2 |
| Diff view | CodeMirror 6 or Monaco, chosen at the mockup | C2 |
| Linux sandbox | bubblewrap | C3 |
| Terminal | `xterm.js` (window), `portable-pty` (Rust shell) | C3 |
| Preview | Tauri's multi-webview feature | C4 |
| Managed tools | Node LTS as an optional part | C4 |
| Scheduled | `openhands-automation` in the same optional part; Tauri's tray and autostart plugins | C6 |

No longer needed from version 1: ripgrep, the `anthropic` package, tree-sitter, a cron parser and an ACP
library of our own. They come inside the engine.

## 13. ADRs to write

The last number in use is 0100. Proposed, in the order they are needed:

1. **0101 The coding engine is OpenHands' Agent Server, run as an optional part** (and why not our own
   core, their library inside our engine, or their screen).
2. **0102 Workspaces, the policy module and the three modes** (and what ADR-0068 covers in a coding
   session).
3. **0103 The sandbox around the coding engine on macOS, Linux and Windows.**
4. **0104 Undo by checkpoints on managed git.**
5. **0105 The workspace panel** (changes, files, terminal, preview, editor).
6. **0106 Models for coding** (cloud first, the gate for local models, keys handed over per session).
7. **0107 Scheduled runs on the automation service, and the unattended rule.**
8. **0108 Outside agents** (which, how they sign in, sandbox-only).
9. **0109 Skills, plugins, hooks and connectors from the engine.**
10. **0110 Managed tools and project starters.**

## 14. Risks

| Risk | What reduces it |
|---|---|
| The sandbox around the engine does not hold, or breaks its tools | It is the first spike. If it fails, the fallback is "Ask me" everywhere, or a sandbox per command inside our module |
| An upgrade of the engine breaks us | A pinned version, endpoint tests, upgrades as their own small stage |
| The model is not good enough, and the product gets the blame | The evaluation and the gate; cloud first; honest wording in the model picker |
| Cost surprises on the person's key | The engine's cost per session and limit per run; a cheaper model for side work |
| A command destroys files | Sandbox, rules, checkpoints that also cover shell changes |
| Outside text takes over the agent | Taint rule, their shell analysers, untrusted project files |
| An outside agent does harm, since its requests are approved automatically | Sandbox-only, and said in the screen |
| Windows has no sandbox for a long time | Windows stays in Ask me until it does |
| Memory: a local model, the engine, a dev server and a browser at once | One job at a time; cloud model for coding; measured in C0 |
| Scheduled runs do damage while nobody looks | The unattended profile, work on a copy, their limits and auto switch-off, one week's trial as the gate |
| 600 MB puts people off | Optional, with the size shown before the download |

## 15. Decisions for the owner

1. **Build on OpenHands' Agent Server** as an optional part of about 600 MB (recommended), instead of
   our own core?
2. **Our screens on its API** (recommended), or their ready-made screen pieces inside Wasify?
3. **Two safety layers**: accept that the engine's tool calls are governed by our policy module, the
   sandbox and our cards, not by the action executor itself?
4. **Wasify's products as tools through the MCP server.** It is frozen: may the coding engine use it,
   and may it change if the spike shows a need?
5. **Scheduled on their automation service** (recommended), schedules only, no outside events in v2?
6. **Undo through git that Wasify manages** (this replaces "undo never needs git" from version 1)?
7. **Cloud first for coding**, and is Opus 5.5 the recommended coding model, or should the default stay
   the cheapest (Haiku 5.5, as for the chat)?
8. **Outside agents**: offered only in "work on its own" mode inside the sandbox? Hermes stays out?
9. **Windows**: ship coding there in Ask me mode until a sandbox exists, or wait?
10. **Desktop only in v2**, and may the app stay in the menu bar and start at login for schedules?
11. **May C0 start?** It adds nothing to the app; the spikes live outside the repository.

## 16. Sources

- OpenHands: the clone at `~/Projects/OpenHands` (commit `754abee4f`, 2026-11-12): `README.md`,
  `AGENTS.md`, `docs/` (architecture, ACP agents, development, self-hosting, DefenseClaw), `config/`,
  `src/routes.ts`, `src/lib`, `src/components`, the desktop packaging notes under `.agents/skills`.
- The installed Python packages (1.62.0 and 1.32.1) under the `uv` cache: `openhands/sdk` (agent,
  conversation, security, context, hooks, sub-agents, workspace, settings), `openhands/tools`,
  `openhands/agent_server`, `openhands/workspace`, `openhands/automation` (scheduler, models, schemas,
  the local backend, the watchdog, the cron helpers).
- The running app on `localhost:8000` and the Agent Server's API description (151 paths).
- GitHub pages of `OpenHands/OpenHands` and `OpenHands/software-agent-sdk`, read on 2026-11-13.
- From version 1: OpenCode's source at commit `12a661ea40`; the repositories of Codex CLI, Hermes Agent,
  Aider, Cline, Goose, pi, the Agent Client Protocol and `anthropics/sandbox-runtime`; Claude Code's
  public documents; Wasify's own measurements (`docs/spikes/chat-everything-ce0.md` on the
  `chat-everything` branch); the owner's "Wasify AI V2 Roadmap".
