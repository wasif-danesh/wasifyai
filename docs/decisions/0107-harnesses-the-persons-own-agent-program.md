# ADR-0107: Harnesses: a coding session can run on the person's own agent program and its subscription

- **Status:** Accepted (2026-11-15, the owner: "Accept, start H1"). Proposed the same day. The owner's words behind it:
  - "We are only supporting API key for Anthropic, ChatGPT, and Gemini. I notice HyperFrames, Ollama and a few
    other apps allow already subscribed users to these providers. It asked me to login to Claude in a browser and
    then it allowed me to use claude in HyperFrames. I need the same feature."
  - "This 'Harness' feature is an absolute requirement for us. It's okay to change the sandbox rules. Investigate
    and search for any open source harness solution, if it's difficult to build from scratch. Our Extensions can
    be used for local models only. We need to add/update ADRs as necessary for Harness implementation."
- **Date:** 2026-11-15
- **Keeps:** ADR-0101 (built on OpenHands' Agent Server, our own screens, the window never talks to it), ADR-0103
  (the check loop and undo are the Wasify engine's), ADR-0105 (our own scheduler), ADR-0092 (the secret store),
  the one installer for optional parts (stage F2).
- **Changes:** ADR-0102 (the sandbox and where a credential lives, for a harness session) and ADR-0104 (which
  sessions Extensions serve). Each has an amendment that points here.
- **Goes with:** ADR-0101's amendment of 2026-11-15 (every model a saved key lists).

## Context

Today a coding session needs an API key (Anthropic, OpenAI, Google Gemini) or a model on this computer. Many
people already pay for a plan (Claude Pro or Max, ChatGPT Plus or Pro, Google AI) and have no API key. Other apps
let them use the plan: the app starts the provider's own agent program (Claude Code, Codex, Gemini CLI), and that
program signs in through the provider's own page in a browser. The app never holds the login. HyperFrames calls
this the "Harness".

### What was found (2026-11-15)

**The engine we already ship can do it.** OpenHands' packages at our pinned version (1.62.0) hold an "ACP agent":
a second kind of agent (`agent_kind: "acp"`) that hands each turn to an outside agent program over the Agent
Client Protocol (ACP), an open standard made by Zed. Read from the installed packages:

- `openhands/sdk/agent/acp_agent.py` (5,090 lines) and six files beside it; the protocol's library
  (`agent-client-protocol` 0.12.1) is already in our environment, so nothing new is installed in Python.
- A catalogue of programs it knows how to start, each a pinned npm package
  (`openhands/sdk/settings/acp_install_catalog.py`): Claude Code (`@agentclientprotocol/claude-agent-acp`
  0.99.1), Codex (`@agentclientprotocol/codex-acp` 2.2.2), Gemini CLI (`@google/gemini-cli` 0.46.0, which speaks
  ACP itself), Kimi Code, Pi and OpenCode; and any other program by its own command (`acp_command`).
- The Agent Server has a route that asks a program which models it offers (`POST /api/acp/models`), and a
  program's model can be changed in the middle of a session.
- The program reports its usage; the agent turns it into the session's cost where the program gives one.
- **It says yes to every permission the program asks for** (`bypassPermissions` for Claude Code,
  `agent-full-access` for Codex). Nothing is asked of the person by this agent.
- Skills are given to the program as text added to the prompt; hooks and tool connections of a plugin are not.

OpenHands describes the same thing in public: the ACP agent "authenticates using whatever credentials that agent
already has, including your existing subscription plan".

**Other open source ways, looked at and not chosen:**

| What | What it is | Why not |
|---|---|---|
| The ACP adapters and library alone (Zed; Apache-2.0) | The protocol, a Python and a TypeScript library, the adapters for Claude Code and Codex | It is what OpenHands' ACP agent is built on. Using it directly means writing a second engine beside the Agent Server: sessions, events, resume, usage |
| Rivet's `sandbox-agent` | A small server with one HTTP and SSE API over Claude Code, Codex, Pi and Amp | A new service and a second event shape beside the one `client.py` already reads |
| `vibe-kanban` (Rust) | A task board with its own layer that starts nine agent programs | An app, not a library; its layer is not made to be taken out |
| T3 Code | A web screen for Codex and Claude | An app; two programs only |
| Each program's own interface (`claude -p` with JSON lines, `codex app-server`) | No adapter in between | One integration per program, each kept in step with its vendor by us |

**What the providers allow** (read on 2026-11-15; rules changed several times in 2026, so they are read again
before release):

- **Anthropic** (Claude Code's "Legal and compliance" page). Running Claude Code inside a product is allowed
  under its Commercial Terms if the program is not modified, no sign-in method is removed, and each person signs
  in with their own account and is billed by Anthropic. A person may sign in to the unmodified Claude Code with
  their own plan. Not allowed: offering Claude.ai login "into their own applications", sending requests through a
  plan's credentials on a person's behalf, or collecting, storing or passing on a Claude.ai login or token;
  sign-in "must complete through Anthropic's own flow". Developers "including those using the Agent SDK" are told
  to use API keys. **Open point:** the Claude Code adapter is built on the Agent SDK, which starts Claude Code.
  Whether that counts as "the unmodified Claude Code binary" is not said on the page. Anthropic blocked plan
  logins in other tools in April 2026 and gave some access back in May on a separate credit pool.
- **OpenAI.** The Codex program signs in with ChatGPT by default. OpenAI published "Sign in with ChatGPT" terms
  for apps in 2026 and lets Plus and Pro plans be spent in taking-part tools. No plain statement was found on an
  app that starts the Codex program on the person's computer.
- **Google.** The Gemini CLI's own FAQ calls other software that uses the CLI's login "to access our backend
  services" a violation, and accounts were closed in 2026 for it (with OpenClaw and OpenCode). Starting the
  unmodified Gemini CLI itself is a different thing, but Google publishes no list of what is allowed.

**What is on the owner's Mac:** Claude Code 2.1.302 and Codex 0.167.0 are installed and signed in; OpenCode is
installed; Gemini CLI is not.

## Decision

1. **A coding session has a harness.** "Wasify AI" is the harness there is today: OpenHands' own agent, on a key
   or a model on this computer. The others are the person's own agent programs: **Claude Code, Codex and Gemini
   CLI** in the first release, each on the person's own plan or key as the program itself is set up. The harness
   is chosen for a new session, on the same button as the model, and a session keeps it.
2. **A harness runs through OpenHands' ACP agent**, on the Agent Server we already run. We write no engine of
   our own and take no other harness project. `client.py` stays the only file that knows the Agent Server; it
   starts a conversation of kind `acp` where it starts one of kind `openhands` today.
3. **The program is the person's own, unmodified, and signs in by itself.** Wasify AI starts the program's own
   sign-in (its own command and its own page in the person's browser). **Wasify AI never reads, stores, copies or
   sends a plan's login or token**, and never calls a provider with one. The model gateway is not used by a
   harness session: there is no key of ours to protect and no call of ours to count.
4. **Where the program comes from.** The program the person already installed is used when it is there. When it
   is not, it is an optional part set up through the one installer: the pinned npm packages of the adapters and
   programs, checked by size and hash, with the Node part that exists (ADR-0102's amendment of 2026-11-15).
   Nothing is fetched while a session runs (`npx` is never left to download).
5. **A harness session has a sandbox of its own kind** (the change to ADR-0102). The program must reach its
   provider and its own sign-in files, so:
   - the network is open to the provider's hosts, through the proxy of our own that installs already use, with a
     list of hosts per harness; nothing else on the internet is reachable;
   - the program's own settings and sign-in folder (for example `~/.claude`, `~/.codex`) can be read and written
     by it, and the keychain item it made for itself can be read by it;
   - everything else stays as today: it writes only in the project, it cannot read the rest of the home folder,
     the app's data or the app's keys, and it cannot send signals or open apps outside.
6. **Nothing is asked in the middle of a turn in a harness session.** OpenHands' ACP agent says yes to
   every permission the program asks for (see "What was found"), and the three modes become two: **Plan** and
   **Work on its own**. Plan is made by the sandbox, with the project open for reading only: the program's own
   plan mode does not hold, because the ACP agent also approves the program's "exit plan mode" (spike H0, run 7). "Ask me" is offered only on the Wasify AI harness, and the screen says so.
   What keeps a harness session safe is the sandbox, the checkpoint before every turn, and undo.
7. **The check loop, undo, Changes, Files, Terminal, Preview, Browser and Scheduled are unchanged.** They are the
   Wasify engine's and work on the project's folder, whatever harness wrote the files (ADR-0103, ADR-0105).
8. **Cost is said as the program reports it.** Where a program gives a cost, it is shown; where it gives none
   (a plan), the session shows "On your plan" and the tokens it reported. There is no limit of ours on a plan:
   the provider's own limits hold, and its message is shown when one is reached.
9. **Extensions serve the Wasify AI harness only** (the change to ADR-0104; the owner: "Our Extensions can be
   used for local models only"). A harness session is given no skill, plugin, hook or tool connection of ours.
   Each program has its own extensions, managed in the program.
10. **The names are used plainly.** The screen says "Claude Code", "Codex", "Gemini CLI" in plain text and "your
    Claude plan" for what pays. No provider's logo or name is part of a name of ours.
11. **Any other ACP program** can be added later by its command ("Add your own agent"). It is not in the first
    release.

## What must be answered before it is built

| | Question | Who |
|---|---|---|
| 1 | **Anthropic's terms.** Is a session that starts Claude Code through the Agent SDK adapter, signed in by the person through Anthropic's own flow, inside what the page allows? If not, Claude Code is started by its own command (`claude -p` with JSON lines) and not through the adapter, which is a second small integration | The owner asks Anthropic (the page names "contact sales"); spike H0 measures both ways |
| 2 | **Agreeing to Anthropic's Commercial Terms**, which the page requires for a product that runs Claude Code | The owner |
| 3 | **Gemini CLI in the first release or not**, given Google's unclear rule and the closed accounts | The owner. Proposed: built, and switched in only after Google's rule is read again |
| 4 | **Downloading the adapters** for the spike (two npm packages) | Answered: the owner said yes; done in H0 |
| 5 | **The size of the optional part**: about 680 MB for the two adapters on a Mac (H0), before Gemini CLI | The owner |

## Stages

| Stage | What | Gate |
|---|---|---|
| **H0, a spike** | Claude Code and Codex, each as an ACP conversation on our Agent Server, signed in with the owner's plans: one real task each. Then inside a sandbox, opened step by step until it works | It works or it does not; what the sandbox must open; whether sign-in can be started from the app; what usage is reported; what Plan can hold; how a reached plan limit looks. Written in `docs/spikes/coding-harness-h0.md`. **Done 2026-11-15:** both work, also in the sandbox with only their sign-in folders and one host each opened (`anthropic.com`, `chatgpt.com`); Plan mode does not hold; sign-in from the app and a reached limit not measured |
| **H1** | The harness in the engine: the optional parts, the sandbox profile per harness, `client.py` and the store (a session's harness), sign-in state and "Sign in" from the app | The hostile tests of the sandbox pass for a harness session; a session on each harness answers, changes a file, is checked and undone |
| **H2** | The screens: the harness on the model button, the two modes, cost as reported, what is not there (Extensions, "Ask me") said in words. A mockup first | A walk in the real window on each harness |
| **H3** | Scheduled on a harness; the evaluation's 36 tasks on each harness | The same rows as a session on a key |

## Consequences

- People with a plan and no API key can use Code. This is the reason for the decision.
- The strongest rule of ADR-0102, that no credential is inside the sandbox, does not hold for a harness session:
  the program's own login is inside it, and the program can reach its provider. The loss is bounded: it is that
  one program's own login, on hosts of that one provider, and the program is the vendor's own.
- A harness session is less guarded while it works than a Wasify AI session: nothing is asked. Undo and the
  sandbox carry the weight. The screen must say this before the first such session.
- We depend on three vendors' programs and two adapters that move fast (the adapter for Claude Code is at 0.99;
  OpenHands pins them, and we pin what OpenHands pins). A vendor can end plan use in other tools on any day, as
  Anthropic did in April 2026. The feature must fail in words, not silently.
- The 36-task evaluation was measured on OpenHands' own agent. A harness has its own prompt and tools, so its
  results are measured again (H3), and "Tested for coding" is said per harness.
- Windows and Linux follow ADR-0102, decision 10: not in v1.
- Not decided here: a harness on the web; passing a session from one harness to another; the programs' own
  extensions shown in our screen.

## Built

- **H1, 2026-11-15:** the programs as an optional part; one sandboxed server per harness; sessions, sign-in state and "Sign in" in the engine and the product. The gate passed: the hostile tests (12) pass for a harness's server, and a session on each harness answered, changed a file, was checked and was undone. The full results are in `docs/spikes/coding-harness-h1.md`.
- **H2, 2026-11-15:** the screens, built from the approved mockup: the Your agent tab with setup and sign-in, the note before the first session, two modes, the plan pill with what the program reported, the cards for an ended sign-in and a reached limit, Projects, Extensions and Settings › Code. The gate passed: the walk in the real window on each program made a real change on the owner's plan, read back from disk, and undid it exactly. The full results are in `docs/spikes/coding-harness-h2.md`.
- **H3, 2026-11-15:** Scheduled on a program (a schedule follows the project's newest session, on a copy, as on a key) and the 36-task evaluation on each program, with "Tested for coding" said per program model. The gate passed for the rows that ran: Claude Code on Haiku passed 36 of 36, every change undone and brought back exactly, $0.23 as reported; Codex on GPT-5.6 Terra passed 19 of 19 before the free ChatGPT plan's limit stopped it, undo exact, $1.05 as reported. The other 17 Codex tasks were not run; the evaluation now stops at a plan's limit instead of counting failures. The full results are in `docs/spikes/coding-harness-h3.md`.
- **H3 follow-up, 2026-11-16:** Claude Code on Sonnet and on Opus each passed 36 of 36 with undo exact ($2.84 and $6.62 as reported). A schedule's Run now on each program was walked in the real window (`code-agent-scheduled`). Fixed: a quick start after choosing a program could start on the local model; a run the plan's limit stopped is said in plain words; `main`'s CI after the merge with the Settings redesign. Installs inside a session on a program are not built: the program's sandbox holds the sign-in, so a package index there could leak it; a safe design and the owner's question are in `docs/spikes/coding-harness-h4-mockup.html`.
- **H4 installs, 2026-11-16:** The owner chose design A. When a program tries to install, Wasify AI offers to install what the project lists. It runs the install in its own sandbox (the terminal's, which cannot read the sign-in), and the program is then told. Built and tested. Our sandbox was shown, on this Mac, to keep `~/.claude`, `~/.codex` and the keychain out of reach. Walked in the real window on Claude Code: the card, the install in our sandbox, and the program told, passed. Two faults it found were fixed: a command Claude Code names only when it ends, and a change to the package list that now offers the install again (`docs/spikes/coding-harness-h3.md`).

## Sources

- OpenHands' packages 1.62.0, as installed with the coding engine: `openhands/sdk/agent/acp_agent.py`,
  `openhands/sdk/settings/acp_providers.py`, `acp_install_catalog.py`, `openhands/agent_server/acp_router.py`.
- OpenHands, "Controlling any Coding Agent with the OpenHands Agent Canvas and SDK":
  https://openhands.dev/blog/use-any-coding-agent-in-openhands-with-acp
- Anthropic, Claude Code, "Legal and compliance": https://code.claude.com/docs/en/legal-and-compliance
- Agent Client Protocol: https://zed.dev/acp
- OpenAI, Codex authentication: https://developers.openai.com/codex/auth and the Sign in with ChatGPT terms:
  https://openai.com/policies/sign-in-with-chatgpt-terms/
- Reports of Google closing accounts for the Gemini CLI's login in other tools:
  https://discuss.ai.google.dev/t/urgent-mass-403-tos-bans-on-gemini-api-antigravity-for-open-source-cli-users-paid-tier/124508
