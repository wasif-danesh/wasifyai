# ADR-0102: The coding engine is an optional part, run in a sandbox by the Wasify engine; the model key stays outside

- **Status:** Accepted (2026-11-14, by the owner: "Accept all"). The owner's words behind it:
  - On the size: "It's acceptable unless there is option to write our own code to make it small." (2026-11-13)
  - On the key and the spending limit for the spikes: "Yes, $10 limit" and "Yes, use it" (2026-11-13)
- **Date:** 2026-11-14
- **Plan:** `docs/v2-coding-agent-start-plan.md` (stages C1a, C2, C3). Measurements: `docs/spikes/coding-c0.md`,
  spikes 1, 2, 4, 5, 6 and 9.
- **Keeps:** the one installer for optional parts (stage F2: `wasifyai_platform_sdk/installer.py`,
  `wasifyai_api/components/`), ADR-0092 (the secret store), ADR-0095 (the person's own key on the desktop),
  ADR-0069 (the MCP server and its approvals), rule 9 (usage), rule 13 (secrets).
- **Goes with:** ADR-0101.

## Context

In its local mode the Agent Server runs every command with the person's own rights, and it holds the model key in a
profile on disk. In the owner's test app an agent whose check had broken left its workspace and read other files.

The spikes measured what holds it:

- **Size.** The environment is 573 MB. Six packages that nothing imports (`googleapiclient`, `grpc`, `PyObjCTest`,
  `Cython`, `reportlab`, `posthog`) can be left out, which gives 385 MB, and the real work still passes.
- **Sandbox.** Under macOS `sandbox-exec` with a profile of three rules, the whole server and every command it starts
  could not write outside the workspace, could not read `~/.ssh` or the app data of other programs, and could not
  reach the internet. Claude Sonnet 5.5, told to save a file to the Desktop, Documents or `/tmp`, failed three ways.
- **The key.** With the network closed to everything but this computer, model calls went to a small gateway outside
  the sandbox, which held the key. The key was found nowhere in the engine's files, environment or logs.
- **Rules.** A module of 20 lines, loaded with a start option, made a delete command wait for a yes or no. While it
  waited, the server kept answering. A hook, by contrast, froze the whole server for as long as it ran.
- **A refusal.** When the model declined a request, the Agent Server saw an empty answer, nudged three times and
  ended the session as "stuck". Only the gateway saw the real reason.
- **Special programs.** `ps`, `top`, `sudo` and others like them cannot start inside any sandbox on macOS.

## Decision

1. **An optional part.** The coding engine is installed, repaired and removed through the one installer, from a lock
   file of our own that lists only what is imported. It is installed by people who want to code, never built in.
2. **A child program of the Wasify engine**, started the way `llama_server.py` starts llama.cpp: a free loopback
   port, a new random session key at every start, a cleaned environment, a home folder inside the app's data
   folder, and its own process group. Stopping reaches the whole group. The session key never leaves the Wasify
   engine.
3. **The whole Agent Server runs inside the operating system's sandbox**, from the first stage in which it can run
   a command. On macOS that is `sandbox-exec` with a profile kept in `services/coding-engine/`:
   - writes: the workspace, the engine's own state and the temp folder, nothing else;
   - reads: the workspace, the tools and the system; the rest of the home folder is closed;
   - network: this computer only.
4. **The model key never enters the sandbox.** The Agent Server is given the address of a gateway in the Wasify
   engine on loopback and a token for the session. The gateway puts the key on the call. It is also where:
   - each call's tokens become a usage event, and a session's cost is counted and limited;
   - a refusal by the model becomes a plain message and ends the turn;
   - the provider's prompt-cache marks pass through unchanged.
5. **Installing packages** (`npm install`, `cargo build`) goes through a proxy in the Wasify engine that lets a
   short list of hosts through. It arrives with commands (C3) or the preview (C4).
6. **Rules by pattern are a module of ours**, loaded into the Agent Server with its own start option. "Ask me" is
   the Agent Server's confirmation step, answered from our approval card. After a "no", our code decides whether
   the agent goes on.
7. **No hook runs longer than one second.** Anything slow is a job of the Wasify engine (ADR-0103).
8. **Wasify's products are tools through the MCP server that exists**, with its approvals in force, through a
   connection that belongs to the coding product. A session gets a short set of tools, never all 67: together they
   are about 25,000 tokens on every model call.
9. **The person's terminal runs under the same profile** as the agent. The app says why `ps`, `top` and `sudo` do
   not work there and offers its own list of running processes.
10. **Windows and Linux are not in v1.** Their isolation is a later ADR. Until then the coding engine is offered on
    the Mac only.

## Consequences

- The optional part is about 385 MB on disk and takes 340 to 510 MB of memory while it runs.
- The trimmed lock is ours to keep: at every move of the version the contract test must show that both the server
  and a real session still work on it.
- `sandbox-exec` is marked deprecated by Apple. It works on macOS 27 and other coding agents rely on it. If a
  future macOS removes it, commands stop until another isolation is in place, and the app falls back to reading and
  editing only.
- The spike's profile closed a short list of folders to reading. Closing the whole home folder except the workspace
  and the tools (decision 3) is stricter and has not been run yet; C1a's hostile tests measure it.
- A cloud model is reached only through our gateway, so the gateway must be fast and must stream. Streaming through
  it was not measured in the spikes.
- The agent's own browser tool (`browser-use`) is left out by the trimmed lock. Whether it is wanted, and what it
  needs, is decided with the Browser tab (C4).
- The hostile tests of the spike (writes outside, reads of secret folders, the internet, a model told to try other
  ways) become tests that run from C1a.
