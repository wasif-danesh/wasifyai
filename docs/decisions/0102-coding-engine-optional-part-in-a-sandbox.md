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

## Amendment (2026-11-14, owner): "Allow for this project", and where a rule is decided

Decision 6 said a marked request is asked. The owner decided that asking must not make the agent unusable:
"Permissions should have an option to "accept all for a project" or similar so users don't need to allow 20
different permissions. [...] We need to make the agent flexible and not an unusable one." The mockups drew it
(`docs/spikes/coding-mockups.md`, choices 12 and 24 to 27) and were approved on 2026-11-14. Stage C2 builds it.

1. **Three answers on every approval card:** yes, no, and "Allow for this project". The third is a yes, and that
   *kind* of request is not asked about again in that project.
2. **An allowance covers a kind, not one request.** The kinds are a fixed list in v1; a person cannot write a rule.
   The list: changing a file Undo cannot put back (added by the owner on 2026-11-14 for stage C2, where the agent
   edits and cannot run a command), deleting files and installing packages (asked once the agent can run commands,
   stage C3).
3. **An allowance is for one project and one person.** A new project starts with nothing allowed. There is no
   "allow in every project".
4. **It can be taken back** in "What this project may do", which lists every kind with Allow or Remove.
5. **Three modes.** Plan: the agent only reads. Ask me: it changes files, and a kind that is not allowed is asked.
   Work on its own: nothing of the list is asked. What is asked in every mode (deleting something of the person's
   outside the project, going on past the cost limit) arrives with the tools that can do it.
6. **Where a rule is decided.** The module loaded into the Agent Server (`services/coding-engine/wasify_rules.py`)
   only makes every use of a tool that changes something wait, before anything has run. Which kind a waiting step
   is, whether it is allowed, and whether a person is asked is decided in the Wasify engine
   (`wasifyai_code/rules.py`), outside the sandbox. So nothing inside the sandbox knows or can change an allowance.
7. **After a no** the agent is told what was refused and goes on another way; **Stop while a card waits** refuses
   what waits and ends the turn.
8. **A project with no git of its own does not get one.** The Agent Server runs `git init` in a workspace by
   itself. The sandbox profile closes `<project>/.git` to writing when the project has none at the engine's start.

Measured in `docs/spikes/coding-c2.md`.

## Amendment (2026-11-15, owner): commands, installs through a proxy, and the agent's own `git init`

Stage C3 gives the agent a terminal. The owner's answers of 2026-11-15: the terminal library may be downloaded;
the install proxy is approved ("I approve it, no need to ask"); the agent may "create the files necessary for a
project", a git repository included. What that comes to:

1. **The agent's terminal is the Agent Server's own, inside the same sandbox as the server.** A session in "Ask
   me" or "Work on its own" gets it beside the file editor. A session in Plan gets neither.
2. **Every command waits before it runs**, like every change to a file: the module loaded into the Agent Server
   marks every use of the terminal as one that waits, and the answer is given outside the sandbox
   (`wasifyai_code/rules.py`), at once or after a card.
3. **The kinds `delete` and `install` are now asked in "Ask me".** A command is judged by its words (`rm`,
   `git clean`, `git reset --hard`; `pip install`, `npm install`, `cargo add` and the like). That is a help to the
   person and not a wall: a script can delete a file without the word `rm`. The wall is the sandbox, which keeps
   every command inside the project, and Undo, which puts a deleted file back unless the project ignores it.
4. **Installs go through a proxy of our own** (`wasifyai_api/coding_proxy.py`). The sandbox still lets a program
   reach this computer only. The programs inside are given a proxy on loopback, which opens a tunnel only to the
   hosts in `coding_install_hosts.txt` (the package indexes of Python, Node, Rust, Go and Ruby; no code hosting
   site), and only on port 443. Two names with a random password each, made at every start of the engine:
   - **the agent's commands and the check** are let through only for ten minutes after an install step was let
     through by the rules. A command that was not judged an install finds the proxy closed.
   - **the person's own terminal** is always let through, to the same hosts.
   The proxy keeps a count and the host of each request, never a path or a body.
5. **What the proxy does not do.** It cannot see inside a tunnel, so it cannot tell a download from an upload.
   The list therefore holds package indexes only; none takes an upload without a key of the person's, and no key
   is inside the sandbox. A package's own install script runs inside the sandbox like any other command.
6. **Decision 8 of the amendment of 2026-11-14 is replaced.** The profile no longer closes `<project>/.git`. The
   Agent Server's own `git init` at the start of a conversation is switched off instead, in our rules module, so
   a person's folder still does not become a repository because it was opened; the agent itself may run
   `git init` when it is asked to. The name our module replaces is checked by a real test against the pinned
   version, and by an `assert` when the server starts.
7. **A sandbox of our own for each project** (`CodingServer.sandbox_for`): the same profile template, filled for
   one project's folder. The check and the person's terminal run in it, so neither depends on the Agent Server
   running, and neither can reach another project the server has open.
8. **The person's terminal** is a shell on a pseudo-terminal started by the Wasify engine inside that sandbox, not
   by the Tauri shell. `portable-pty`, named in the plan's table, is therefore not used; `xterm.js` draws it in
   the window. Its home folder is the sandbox's own, so the person's start-up files are not read, and `ps`, `top`
   and `sudo` do not work in it. The screen says so.
9. **Not decided here:** what is asked in every mode (going on past the cost limit), a list of what runs in a
   project with a way to stop each, and the same sandbox on Linux and Windows.

Measured in `docs/spikes/coding-c3.md`.

## Amendment (2026-11-15, owner): Node as an optional part, the preview, and Wasify AI's own products

Stage C4. The owner's answers of 2026-11-15: Node may be downloaded as an optional part ("Yes, download it");
the Preview tab is built now and the Browser tab after it; the agent gets "a short set now" of Wasify AI's own
products; the routes and actions may be added.

1. **"Node for coding projects" is an optional part** (`components/node.py`): the pinned Node LTS release from
   nodejs.org, size and SHA-256 checked, under `<app data>/engine/node/`. The sandbox cannot read a person's
   home folder, so a Node kept there (nvm and the like) is not found; this one is opened for reading and put
   first on the path of the agent's commands, the check, the preview and the person's terminal. Nothing writes
   it: a project's packages go into the project, npm's cache into the sandbox's own home. It is offered where
   the coding engine is.
2. **The preview is the project's own command, run by the Wasify engine inside the project's sandbox**
   (`preview.py`), like the check and the person's terminal. It is given a free port as `PORT` and
   `HOST=127.0.0.1`.
3. **A running preview is found from outside the sandbox**, by the ports the processes under it listen on
   (`lsof`), not by what the program prints.
4. **The sandbox cannot keep a program from listening on every address of the computer.** Measured: with and
   without an inbound rule in the profile, a server bound to `0.0.0.0` answered on the computer's network
   address. So the promise "only this computer can open it" is made only when the preview listens on a local
   address, and the Preview tab says in words when it does not.
5. **The page is shown in a frame from `http://localhost:<port>`**, not in a second webview. The window's
   content rule now allows frames from `localhost` beside `127.0.0.1`. The frame is the project's own page: it
   has none of the app's rights.
6. **Wasify AI's own products reach a session through one command, not through a connection.** The agent runs
   `wasify-make picture "<what>" <file.png>` or `wasify-make speech "<words>" <file.wav>` in its terminal. Like
   every command it waits; `rules.py` knows it as the kind `make`. When it is let through, the Wasify engine
   itself runs the app's own action (`image.generate`, `speech.speak`) for the person through the one action
   executor, outside the sandbox, writes the file into the project, and leaves a note; the command inside the
   sandbox only reads that note. This replaces point 3 of `docs/spikes/coding-c1b.md` ("a connection of the
   coding product's own on the MCP server"): no token of the app is inside the sandbox, the MCP server is not
   changed, and none of the 67 tool descriptions (about 25,000 tokens) is sent to the model.
7. **The kind `make` is asked in every mode**, also in "Work on its own", until the person allows it for the
   project: it uses the person's own picture or speech model, which can take time or cost money.
8. **Not decided here:** 3D models, music and video through the same command; a picture the agent can look at;
   the Browser tab; the same on Windows and Linux.

Measured in `docs/spikes/coding-c4.md`.
