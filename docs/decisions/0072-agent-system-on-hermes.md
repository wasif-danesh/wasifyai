# ADR-0072: An agent system for long tasks, built on Hermes Agent

- **Status:** Accepted (2026-10-18, by the owner), together with the components it names. The owner's answers
  (2026-10-18) and the amendment after spike G0 (2026-10-19) are part of the decision: the sentences marked *amended*
  are read with them. Stage G1 has not started; `docs/improvement-plan-2026-10-27.md` section 7 is the current design.
- **Date:** 2026-10-18
- **Depends on:** ADR-0068 (action catalogue, approvals), ADR-0069 (our MCP server), ADR-0070 (MCP client),
  ADR-0071 (the assistant), ADR-0056 (one engine; one memory slot), ADR-0047 (safeguards), ADR-0041 (everything
  made is searchable), ADR-0061 (how outside code enters).
- **Plan:** `docs/phase5-agent-training-video-builder-plan.md`, stages G0 to G4.

## Context

The owner wants people to type a goal in the app and have an agent do it. The example: "explore GitHub for the
top starred repo and make a report with what it does, technologies, and results." The owner proposed **Hermes
Agent** (Nous Research, MIT) as the engine.

**Is the example possible? Yes.** It needs only a web search or the GitHub API, reading a README and a few
files, and writing a document, which is well inside what Hermes does (web search, web extraction, file
operations, subagents, skills). What decides quality is the **model** behind it, and what decides safety is
**which tools it may use**. The plan (section "The GitHub example") walks through it, including the questions the
agent should ask first ("top starred of all time, this week, or in one language?") and GitHub's rate limits.

What Hermes is, from its repository and documentation read on 2026-10-18 (the documentation is young, and some
pages disagree with each other; spike G0 re-reads and tests every claim before anything depends on it):

- An agent loop with **40+ tools** in toolsets, **subagents**, a built-in **scheduler**, **skills** it can write
  and refine after hard tasks (`SKILL.md` files), layered **memory** (files injected into the prompt, full-text
  session search), an **MCP client**, seven terminal backends (local, Docker, SSH, Singularity, Modal, Daytona,
  Vercel Sandbox), a messaging gateway (Telegram, Discord, Slack and others). MIT. Installs with a script for
  Linux, macOS and Windows.
- **Three ways to drive it from another program:** ACP (JSON-RPC over stdio, for editors), the **TUI gateway**
  (JSON-RPC over stdio or WebSocket, which its own documentation recommends for custom desktop hosts and says its
  desktop app uses), and an **OpenAI-compatible HTTP API**. Through the gateway and the API the host can answer
  **approval requests** and read streamed events (`message.delta`, `tool.start`, `tool.complete`).
- It **requires a model with at least 64,000 tokens of context** (smaller models are rejected at start-up).
- Its **security**: dangerous-command approval (`manual`, `smart`, `off`), a hard-line blocklist, path guards for
  secrets, SSRF protection on web tools, environment stripping, container isolation on the `docker` backend, and
  a skills scanner. Its own documentation is explicit that with the **local terminal backend there is no
  isolation**: commands run as the user, the path guards can be bypassed from the shell, and approval prompts can
  be switched off.

What that means for this app:

- A desktop app for non-technical people cannot hand an agent an unsandboxed shell. The container backend needs
  Docker or Podman, which the desktop does not require.
- The 64,000-token minimum collides with our local chat setup (8,192 tokens of context; the recommended Qwen3 4B
  evaluated at 11 of 11 tool cases). The memory for that context is real (the key-value cache grows with it) and
  is shared with image and audio models through the one slot (ADR-0056).
- The agent should not be a second, parallel way to do things: it should use the app's own actions (ADR-0068)
  through the MCP server (ADR-0069), so approvals, limits and audit are the same ones.
- Self-writing skills and persistent memory are **persistent instructions**: a prompt injection that lands in
  them survives the session. They need a decision.

## Decision

1. **A product `wasifyai-agent` and a screen "Agent".** A person types a goal in plain words; the screen shows a
   plan, a live feed of what the agent does (steps, tools used, pages read, files written; details collapsed),
   inline approvals, a Stop button, and, when done, the **result**: a report or files, opened in the app. Tasks
   run in the background and a notification says when one needs the person or has finished. Starting points are
   offered ("Research a topic", "Compare things", "Summarise a GitHub repo", "Turn these notes into a report"),
   each a goal with fields, not a script. The assistant (ADR-0071) may offer an Agent card (`agent.run`,
   ADR-0068) when a request is too big for a chat turn.
2. **Hermes runs as a managed component, not inside our engine.** *(amended below: pre-built from the lock, about 660 MB)* Like the notebooks' reader and ComfyUI, it is
   installed on request after showing its size and source, into `<app data>/components/agent/` in a virtual
   environment of its own, from a **pinned version with a hashed lock** (never a `curl | sh`), with its own data
   folder (`HERMES_HOME`) inside the app data. The engine starts it as a child when a task starts and stops it when
   idle or when the app quits, as it does for ComfyUI. This keeps Hermes's Python version and dependencies
   (it names Python 3.14) away from the engine's.
3. **One adapter, `AgentEngine`, so Hermes can be replaced.** *(decided by G0: the TUI gateway over stdio, one process per task)* The engine talks to the agent through an interface
   (start a task with a goal, tools and limits; stream events; answer approvals; cancel; list artifacts). Hermes
   through its **TUI-gateway JSON-RPC over stdio** is the first implementation, chosen because its own
   documentation recommends it for desktop hosts and because it lets the host answer approvals; spike G0 checks
   the alternatives (ACP, the HTTP API) and confirms or changes this. A second, small **native** implementation
   (a LangGraph loop over our actions and the MCP client of ADR-0070) is kept possible as the fallback if Hermes
   proves unfit or unstable. Its events are translated to ours: `node`, `token`, `tool_call`, `tool_result`,
   `interrupt`, `job_progress`, `done`, so a task is an ordinary run with a replayable log (ADR-0021).
4. **Tool profiles decide what an agent can do, chosen per task and shown before it starts.** *(amended below: the profile is a toolset allow-list; file reads only through our MCP server)*

   | Profile | Tools | Backend | Default |
   |---|---|---|---|
   | **Research** | web search and page extraction, file read and write **inside the task's workspace folder**, our actions through the MCP server (scope chosen per task), the `document` actions to export a report | none needed | yes |
   | **Build** | Research plus a terminal and code execution | **container only** (Docker or Podman, if installed) | off until a container engine is found |
   | **Local terminal** | Build on the host | none | **not offered in v1** |

   No profile has a shell on the host. The workspace is a folder per task under the app data folder; writes
   outside it are refused by Hermes's write-root setting and the profile; reads of the person's own files need an
   attached folder the person picked for that task.
5. **Approvals are ours.** Hermes's approval requests become `interrupt` cards in the Wasify window (the command
   or action, why it is flagged, the profile, Allow once / Deny; "always" is not offered for commands). The
   mode is **`manual`, fixed**: the app cannot set `smart` or `off` or the "yolo" flag, and an unanswered request
   is denied after the timeout. Our own floor applies on top for our actions (ADR-0068 decision 4); an agent
   reaches our actions only through the MCP server under a dedicated connection whose scope is the task's, so
   `destroy` and `needs_consent` always ask a person.
5a. **Taint** (ADR-0070 decision 5) applies from the first web page the agent reads: from then on every action
    that is not a plain read asks in the window, with where the request came from.
6. **Limits on every task**, set on the start card, with defaults and ceilings: wall time (30 minutes), steps,
   tokens (a hosted model shows an estimated cost range first and stops at the cap), pages fetched, workspace size,
   files written. A task that reaches a limit stops and says so. A watchdog stops a task that has made no progress
   for five minutes.
7. **Models.** *(the owner's answers and G0 below: Qwen3.5-9B, "limited" for agents until G3; Hugging Face Inference Providers as the first hosted provider)* The agent needs a **model that is agent-capable**: context of at least 64,000 tokens, reliable tool
   calling, enough speed. The Models page marks each model (local or hosted) `agent-ready`, `limited` (with why:
   "context 8,192; Hermes needs 64,000") or `not suitable`, from the model's measured context, memory fit and a
   short tool-calling check (the assistant's evaluation runner, ADR-0071). For a local model the engine starts the
   language server with the larger context **for the task** and shows the memory it will take; on machines where
   that does not fit, the screen says to use a hosted model. Hosted models (the person's own key for a provider the
   app supports) are a first-class choice and the start card states plainly that **everything the agent reads and
   writes goes to that provider**. A task that needs image or audio models while the language model is resident
   waits its turn for the slot (ADR-0056) and the feed says so.
8. **Learning is off by default.** Hermes's self-written skills and agent-curated memory stay **off** in v1. The
   setting "let the agent learn from tasks" has three states: off, ask me before it keeps anything (the person sees
   the skill or note and accepts or deletes it), on. Skills are installed only from a **reviewed list we ship**,
   with Hermes's skill scanner on. `~/.hermes` is never read: the app does not adopt logins or files from other
   installs (`auth.adopt_external_logins` is false).
9. **Network.** *(secrets through the secret store of ADR-0092)* Hermes's SSRF protection stays on (private, loopback, link-local and metadata addresses blocked, redirects
   re-checked). A per-task list of allowed domains is offered in "Advanced", default "any public site". Secrets for
   a service (a GitHub token to raise rate limits) are stored in the keychain (ADR-0070 decision 7), given to the
   one tool that needs them and never put in the environment of a shell or in the prompt.
10. **Results are creations (ADR-0041).** The task's workspace is kept until the person deletes it. Reports and
    files the agent marks as results are promoted to the library as kind `report` (Markdown, with an export to PDF
    and Word through the existing writers) and indexed; the run itself is kept as kind `agent_run` (goal, plan,
    steps, sources, outcome; no hidden reasoning) so it can be found and read later. A report states its
    **sources** (URLs with the time read) and which claims came from which.
11. **Off by default, and honest about cost.** The Agent screen appears when a component is installed and a model
    is chosen. Usage events record steps and tokens; the audit log records tasks and approvals, not content.
12. **What it does not do in v1:** messaging gateways (Telegram and the rest), the built-in scheduler (recurring
    tasks wait for our own scheduler, a later ADR), voice, browser automation of logged-in sites, running code
    from the repositories it reads, and unattended runs that need approvals (they stop and wait).

## Consequences

- A large new capability whose quality depends on the model. With a hosted model it should work well; with a
  local 4B model it will not, and the app says so before the task starts instead of failing in minute twelve.
- A new component to install, pin, update and sign. A component update that changes Hermes behaviour is tested
  against the agent evaluation (plan, G3) before it ships.
- The agent and the MCP server meet: Hermes is an MCP client of ours, so everything an agent can make or read goes
  through the catalogue and its approvals. Two config stores for third-party MCP servers would be a mistake: the
  list in Settings (ADR-0070) is written into Hermes's configuration by the engine, not edited in Hermes.
- Hermes is about eight months old as a project (first released February 2026) and moves fast; pinning, the adapter and the native fallback are the
  protection. Documentation that disagrees with itself (the default approval mode differs between pages) is a
  reason to test, not to trust.

## Alternatives considered

- **Our own agent loop only.** More control, much more work, and no skills ecosystem. Kept as the fallback behind
  the same interface.
- **Embed Hermes in the engine's Python.** Version and dependency conflicts, and a crash takes the engine down.
  Rejected for a child process.
- **Give agents a local shell.** Rejected for non-technical users (Hermes's documentation says it is not isolated).
  Revisit only with a real sandbox.
- **Other agent frameworks** (OpenHands, Goose, LangGraph agents, Claude's Agent SDK). Not evaluated beyond this
  ADR; the `AgentEngine` interface is what lets us change. The owner chose Hermes.
- **Expose agents only through MCP clients** (let people use Claude Code for tasks). Valid and available with
  ADR-0069 today; it does not give a non-technical person an in-app agent.

## Open questions

1. Which integration path survives spike G0 (gateway over stdio, ACP, the HTTP API), and whether the host can set
   the toolset, the working directory and the write-root per task through it. The documentation did not say. **Answered by G0** (amendment below).
2. How much context a good local agent model needs in memory on a 32 and a 64 GB Mac, measured.
3. Windows and Linux: the container backend is easier there; the Mac comes first.
4. Whether `smart` approval (a second model judges commands) is ever acceptable. Not in v1.
5. How the agent's web search is provided without an API key (a free provider, the person's key, or ours). **Partly answered by G0:**
   a deterministic `web.github_top` read action for the example task; keyless search stays an owner decision
   (improvement plan, section 10).

## Not in v1

Messaging gateways; recurring tasks; agents that act in the person's logged-in accounts; multi-agent teams beyond
Hermes's own subagents; sharing skills between people; the web deployment (it would need the container backend and
per-tenant isolation).

## Owner's answers (2026-10-18)

- **Model.** The agent uses **Qwen3.5-9B** (Apache-2.0, multimodal, per its Hugging Face page, read 2026-10-18),
  which is expected to give the larger context Hermes needs. It also becomes the app's one default model
  (ADR-0078), so there is no second local model to download. Whether it really holds 64,000 tokens of context on a
  32 and a 64 GB Mac, and how well it calls tools, is measured in G0 and G3; the `agent-ready` check (decision 7)
  still decides per machine.
- **Hosted models, first providers: Hugging Face (Inference Providers) and GitHub (GitHub Models) only**, with the
  person's own key. Others (OpenRouter, Anthropic, OpenAI, a custom endpoint) come later. **Corrected 2026-10-19 after
  spike G0: GitHub Models was retired on 2026-07-30 (as read in the session's documents check), so the first hosted
  provider is Hugging Face Inference Providers only.** Other providers come later.

## Amendment after spike G0 (2026-10-19; report: `docs/spikes/agent-g0.md`)

Measured on the owner's MacBook Pro M5 Pro, 64 GB. Verdict for stage G1: **Go**, on the conditions below.

- **Control path (decision 3 is now concrete):** the **TUI gateway over stdio** (`python -m tui_gateway.entry`), **one
  process per task**. ACP is the fallback; the HTTP API is the weakest fit. Per task: the toolset is configuration (not
  a call argument), the working folder is set at session creation, and the write-root is a process environment
  variable. Events, approvals answered from outside, and stop (a running command ends in 0.15 s) all work on all three
  paths. Hermes's MCP client connected to a stub MCP server and its untrusted-server approval was verified.
- **What Hermes does not enforce (decides the profiles, decision 4):** the Research profile holds only because the host
  **allow-lists toolsets and leaves out `terminal`**; the write-root is **not a sandbox** and **reads are
  unrestricted**. So file reading must come only through our MCP server and the attached-folder rule, never through
  Hermes's own file tools.
- **Install (decision 2):** Hermes builds its own Python environment on first start (about 662 MB, 272 MB of it
  downloaded packages; its Python 3.14.7 comes from `~/.hermes/tools/`). The installer must build this **ahead of
  time from the pinned, hashed lock, with no first-run download**.
- **Models (ADR-0078):** Qwen3.5-9B Q4_K_M holds 64,000 tokens on this Mac in about **8 GB**; prompt reading 1,080 /
  858 / 686 tokens/s and writing 39.3 / 37.4 / 28.5 tokens/s at 8k / 32k / 62k; **thinks by default** (off with
  `--reasoning off` or `enable_thinking: false`); 10 of 10 small tool-calling cases. On the example task the local model
  finished in 71 to 143 s but **found the right repository in 1 of 3 runs**, so the local 9B stays **"limited" for agents**
  until G3 shows otherwise. Hugging Face Inference Providers serve Qwen3.5-9B at 262,144 context with tools.
- **G1 conditions:** (1) the acceptance run uses a **hosted model**; (2) G1 includes a **deterministic "repositories
  sorted by stars" read action** and a **mandatory sources section** in every report, because free web search alone found
  the right repository once in three; (3) the Models page shows "about 8 GB for 64k context"; a 16 and a 32 GB
  measurement is still needed before ADR-0078's minimum-RAM line is written.
- **Not done:** the hosted-model run (no key), the 32 GB case, the app's own llama.cpp, MLX, Windows and Linux, learning
  features, MCP over Streamable HTTP.
