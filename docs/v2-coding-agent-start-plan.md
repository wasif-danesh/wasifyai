# Wasify AI: how the coding work starts

Written 2026-11-13, changed the same day and on 2026-11-14 after the owner's answers (section 10). Nothing here is built
in the repository, and no dependency is added. ADR-0101 to ADR-0105 were accepted by the owner on 2026-11-14. It says how the first work on the
coding agent goes into this repository, in what order, and what each piece must prove.

**Scope (owner, 2026-11-13).** Coding, automation and extensions are part of **v1**, with the web
browser, the file browser, the file changes and the result preview. Desktop first, Mac first. The file
keeps "v2" in its name because the documents it follows do.

It follows `docs/v2-coding-agent-guideline.md` (version 2: build on OpenHands' engine, keep our own
screens) and uses its stage names (C0 to C10). `docs/v2-cloud-and-engine-plan.md` is a wish list; the
only thing taken from it here is the "place" interface, so the cloud stays possible.

The owner built a test app outside this repository, `~/Projects/openhands-integration` (Tauri and Rust
on Agent Server 1.62.0, Automation 1.32.1, extensions 0.42.0, the local Qwen 27B). It was reviewed on
2026-11-13 with real runs. **No code is copied from it.** What it showed is used twice below: as answers
to some of the C0 spikes (section 3) and as a list of faults that become rules (section 4).

## 1. In short

1. **The window never talks to the Agent Server.** The window talks to the Wasify engine; the engine
   talks to the Agent Server. The test app's window called the Agent Server directly, which leaves no
   place for our rules, our search, our usage records or a team later.
2. **The implement, check, fix loop is ours and lives in the Wasify engine.** The Agent Server does the
   implementing. The Wasify engine runs the check, decides whether the work is done, counts the rounds and
   keeps the result. Nothing slow runs inside an Agent Server hook.
3. **The engine's "finished" means "the turn ended", not "the work is done".** Done is a row we write
   after a check passed. The screen shows one of four words: passed, failed, not checked, could not check.
4. **The Agent Server comes as pinned packages through the one installer**, as an optional part, started
   and stopped by the Wasify engine, inside a sandbox. No server source is copied into the repository.
   A lock of our own leaves out what nothing imports: 385 MB in place of 573 MB (measured).
5. **Extensions: the catalogue is taken, the module is ours.** OpenHands' catalogue is data in an open
   format and comes as a pinned copy. What lists it, switches it on, asks before a plugin is trusted and
   shows it on a screen is our code (section 7).
6. **Tests come first.** A fake Agent Server for unit tests, a contract test against the real pinned one,
   and one real-model run of the loop. The test app had none, and its loop had never run before the review.
7. **The first model is Claude Sonnet 5.5**, reached through the Wasify engine so the key never enters
   the sandbox.

## 2. What v1 holds

| In v1 (owner, 2026-11-13) | Stage | Screen |
|---|---|---|
| Coding: a chat that reads, edits and runs code, with the check loop | C1a, C1b, C2, C3 | The session view |
| File browser | C1b | Files tab |
| File changes, with undo | C2 | Changes tab |
| Web browser | C4 | Browser tab |
| Result preview | C4 | Preview tab |
| Automation | C6 | Scheduled |
| Extensions | X1 to X3 (the guideline's C8, moved forward) | Extensions |

**Not in v1 unless the owner says so:** outside agents such as Claude Code and Codex (C7), the starters
for apps and games with Godot and Blender (C9), the roadmap's plugins phase (C10), the extras of long
sessions (C5: sub-agents shown, sessions in the job tray), the web version of coding, Windows and Linux,
teams and the cloud.

## 3. What is known before any code

The guideline's C0 has ten spikes. The test app answered parts of six. Four more were run on 2026-11-13
after the owner's yes; their results are in `docs/spikes/coding-c0.md`.

| C0 spike | State | What is known | What is still open |
|---|---|---|---|
| 1. Install and start by a script | **Go, partly open** | Runs from the pinned packages alone, answers in 5 to 9 s, 340 to 510 MB of memory. 573 MB on disk, 385 MB with six unused packages left out, and the real loop passes on the trimmed set | The same through our installer on a clean account; the download size |
| 2. A session over the API | **Go** | Sonnet 5.5 through a gateway on loopback with the engine in the sandbox: the real loop in 18 s, a correct read-only analysis in 21 s, a module with 19 tests in 30 s; $0.36 counted for five sessions; the key found nowhere inside the sandbox | Nothing that blocks |
| 3. A coding evaluation | **Go for Sonnet 5.5** | 36 tasks with hidden checks (`docs/spikes/coding-eval-tasks.json`). Sonnet 5.5: 36 of 36 in two runs, median 13 s and $0.07 a task. The local Qwen 27B: 33 of 36, median 61 s | The set cannot show where Sonnet 5.5 stops; real projects in C1b to C3 will. Node and Rust tasks once their tools are inside the sandbox |
| 4. The server inside the sandbox | **Go on macOS** | No write outside the workspace, no read of the secret folders, no internet; the real loop passes inside it; a model told to write to the Desktop failed four ways | Linux and Windows (not v1) |
| 5. The policy module | **Go** | Our module loads with a start option; a rule by pattern stops a delete command for a yes or no; both answers work; the server keeps answering while it waits | Nothing that blocks |
| 6. Wasify's MCP server as tools | **Go** | The existing launcher works as a tool server inside the sandbox; a read ran, a make waited for the person's approval | Its 67 tools are about 25,000 tokens on every call: a short set for coding, and a connection of the product's own |
| 7. Its events in our chat | **Go** | The live socket delivers every event in order within milliseconds, streams words as written, and a listener that drops misses nothing | The new event kinds in our SSE contract (C1b) |
| 8. Automation through a restart and a pause | **The clock is a go; the stock run is a no-go** | One run per mark, one catch-up after a stop or a freeze, never doubled. Its stock run installs packages from the internet at run time (552 MB a run) and bypasses the Wasify engine; the server itself takes about 430 MB of memory | **Decided (owner, 2026-11-14): a scheduler of our own**, ADR-0105 |
| 9. A terminal and a child webview in Tauri | **Go** for the terminal | A shell in a real terminal under the sandbox: resize, Ctrl-C, colours, and the same refusals as the agent. A second webview window as a browser works (the test app) | The terminal view in the window (C3). `ps`, `top` and `sudo` cannot start inside the sandbox |
| 10. A checkpoint and an undo | **Go for files** | A git store outside the workspace restores edits, deletes, new files, binaries, modes and links exactly; 3 s for this repository | Ignored files, empty folders and the person's own git are not restored: three choices for C2 |

The three spikes that decide the plan (1, 4 and 5) are all a go, and so is the first model (spikes 2 and 3). All ten have now been run.

## 4. Faults in the test app, and the rule each one becomes

Each fault was seen in a real run or read in the code. The rule is what this repository does instead.

| Fault in the test app | How it showed | Rule here |
|---|---|---|
| The check runs inside the Agent Server's Stop hook | The whole server stopped answering while a check ran: a 23 s check held an unrelated call for 22.7 s, and Stop only worked after the check ended | **No hook runs longer than one second.** The check is a job of the Wasify engine, in its own process group |
| "Finished" was trusted | A finish on the last allowed step skipped the check and the chat still said finished | Done is our record, written only after a check passed. The step limit ends a turn as "stopped at the limit, not checked" |
| The check ran after every turn | A plain question was refused, and the agent edited a file it was told not to touch, to get through | The check runs only when files changed since the last pass |
| The gate was a script file beside the workspace, one per chat | When a file went missing every later message was blocked (Python's exit code 2 means "block" to a hook). The agent then read other chats' scripts | No script files. The check command and its results are rows in our store. Nothing of the gate is inside the agent's reach |
| No gate unless a command was typed | A blank box meant nothing was checked, and nothing said so | A check is suggested from the project's files and shown. "Not checked" is a state the person sees |
| No gate on scheduled runs | Automations were created without it | Chat and Scheduled call the same function |
| No result kept | The screen said "Ready" whatever happened | A row per check; one of four words in the session header and a card in the chat |
| No limit on fix rounds | A check that can never pass ran until the step limit; the agent re-ran it in its own terminal | Three rounds by default, then stop and say what still fails |
| A broken gate let the work through | Any failure of the hook itself, other than exit code 2, counted as allowed | A check that could not run is "could not check". It is never "passed" |
| Child processes outlived a timeout | Two were left alive | The check's whole process group is stopped on a timeout and on Stop |
| No sandbox | The agent ran commands with the person's own rights and read files outside its workspace | The whole Agent Server runs inside the sandbox from the first stage that can run a command |
| The window's own code called the Agent Server | Rust commands held the session key and the model settings | The window calls Wasify actions only. The session key never leaves the Wasify engine |
| Asking every 1.5 s, last 100 events, 15 s limit | Errors on the screen during any long step | One live stream from the Agent Server to the Wasify engine, relayed over our SSE contract; nothing is asked on a timer |
| Fixed ports | A second copy cannot start | A free loopback port chosen at start, as the other helper servers do |
| Server source copied into the project | Two packages' source sat in `servers/` | Pinned packages and a lock only. We never patch them |
| The extensions folder copied in by hand | A copy of the catalogue sat in the project with no pin | The catalogue is a pinned archive in the installer's manifest, checked by size and SHA-256 |
| State inside the project folder | Logs, the database and the workspace side by side | Engine state under the app's data folder; a workspace is a folder the person chose |
| No tests | The loop had never run before the review | Section 8 |

Three things the test app did well are kept as rules: a new random session key at every start, a cleaned
environment for the child program, and a process group per helper so that quitting stops everything.
A fourth is kept too: it set `EXTENSIONS_PATH`, without which the engine fetches the catalogue from
GitHub's `main` branch at run time.

## 5. Where the first code goes

Nothing below exists yet. Folders are created only when there is code to put in them.

| Path | What it holds | First stage |
|---|---|---|
| `services/coding-engine/` | The one version pin, the lock files per platform (our trimmed list), the sandbox profile, the policy module, later the container build | C1a |
| `services/api/src/wasifyai_api/components/coding.py` and the five manifests | The optional part "Coding engine" and the extensions catalogue: install, repair, uninstall, through the one installer | C1a |
| `services/api/src/wasifyai_api/coding_server.py` | Start, health, stop of the Agent Server as a child program inside the sandbox, the way `llama_server.py` runs llama.cpp | C1a |
| `products/wasifyai-code/wasifyai_code/` | The product. `client.py` (the only file that knows the Agent Server's API), `place.py` (the interface, with one implementation: this computer), `store.py`, `events.py`, `actions.py`, `routes.py`, later `loop.py`, `checks.py`, `checkpoints.py`, `extensions.py`, `schedules.py` | C1b |
| `extensions/` | Wasify's own catalogue, in the OpenHands format | X2 |
| `packages/ui/src/code/` | The session view and its tabs, Scheduled, Extensions; shared by the desktop and the web | C1b |
| `docs/help/`, `docs/contracts/actions.json`, the search corpus | One help file and one row per action; a session is a creation and is found by search | C1b |

**Who talks to whom.**

```
window -> Wasify engine (wasifyai-code: actions, store, loop, checkpoints) -> Agent Server (in the sandbox)
            |  runs the check itself, as a job                                 |  edits files, runs the agent
            |  keeps sessions, turns, checks, usage                            |  knows nothing about "done"
            |  the model gateway on loopback  <--------------------------------+  model calls, no real key
            +-> the model provider (Sonnet 5.5), with the key from our secret store
```

**Rules that hold from the first line.**

- The Wasify API never imports the OpenHands SDK. Types for the events we show are generated from the
  Agent Server's API description at the pinned version, so an upgrade that changes them fails the build.
- **The model key never enters the sandbox.** The Agent Server is given the address of our gateway on
  loopback and a token for the session. The sandbox allows the network to this computer only.
- **A refusal by the model is shown, not hidden.** The gateway sees the provider's stop reason. The
  Agent Server alone turns a refusal into three empty answers and a "stuck" session (seen with Sonnet 5.5).
- The gateway is where a session's cost is counted and limited; it passes the prompt-cache marks through
  unchanged (85% of the input in the spike was read from the cache).
- Every route resolves a person and carries `tenant_id` and `product_id`; every model call and every
  check writes a usage event. The cost of a session is shown in its header from the first stage.
- **A coding session never gets all of Wasify's 67 tools.** It gets a short set through a connection of
  the product's own; an approval it causes is shown in the session.
- **Stopping reaches the whole process group** of the Agent Server, of a check and of a scheduled run.
- Every feature is an action with a help file. The first actions: `code.session.start`,
  `code.session.send`, `code.session.stop`, later `code.check.run`, `code.session.undo`,
  `code.schedule.*` and `code.extension.*`.
- No feature switch. The menu item appears when the optional part is installed, as other parts do.
- The session stream needs new event kinds in `docs/contracts/sse-events.md` (a tool step, a check, a
  session state). That is a change to the SSE contract, so it is proposed and agreed in C1b before any
  code sends them.

## 6. The implement, check, fix loop

**The states of a turn.**

```
working -> turn ended -> files changed since the last pass?
                           no  -> done (the last result stands)
                           yes -> checking -> passed            -> done
                                           -> failed, round < 3 -> the output goes back -> working
                                           -> failed, round = 3 -> stopped: needs you
                                           -> could not check   -> stopped: needs you
stopped by the person, or at the step limit -> not checked
```

**Rules.**

1. **Who runs the check.** The Wasify engine, as a job, in its own process group, inside the same
   sandbox profile as the agent's commands. Never the Agent Server, and never a hook.
2. **What the check is.** One command per workspace to begin with (`cargo test`, `npm test`,
   `python -m pytest`). It is suggested from the project's files, shown to the person, and can be changed.
   It is stored in our store with the workspace's record. Build, lint and test as separate steps come
   later, in the same table.
3. **When it runs.** After a turn ended and the workspace differs from the last one that passed. The
   comparison uses the checkpoint store of C2, so a question or a chat about the code costs nothing.
4. **What goes back to the model.** The command, the exit code and the end of the output (a fixed
   number of characters). The full output is kept as a file through the storage interface.
5. **Rounds.** Three by default. After the third failure the turn stops and the card says what still
   fails. The person can say "try again", which starts a new count.
6. **Time.** A limit per check (ten minutes by default). At the limit the whole process group is
   stopped and the result is "could not check".
7. **Stop.** Stops the check at once, because it is our process, and interrupts the Agent Server.
8. **The result.** A row per check: workspace, session, turn, round, command, result, seconds, the
   output file. One event on the stream, one card in the chat, one word in the session header.
9. **Honesty about tests.** If the agent changed or deleted a test file during the turn, the card lists
   the files. We do not try to forbid it; we make it visible.
10. **One function.** Chat and Scheduled both call it. A scheduled run that ends "failed" or "not
    checked" is shown that way in its history.

**Gate for the loop (measured in C3).**

- The review's case passes from the app: a workspace with an old bug, a task that adds a function, a
  check that covers both. One refusal, one fix, one pass, and the check file untouched.
- A check of two minutes runs while the screen stays live and every other call answers within a second.
- Stop during a check ends it within one second and leaves no process behind.
- A question in a workspace whose check fails is answered, and no file changes.
- A check that cannot pass ends after three rounds with "needs you".
- A check command that does not exist ends as "could not check".
- The same task as a scheduled run gives the same rows.

## 7. Extensions

**What OpenHands' Extensions is.** A catalogue, not a program: the package `@openhands/extensions`
(0.42.0, MIT, about 10 MB). It holds 73 skills (a folder with a `SKILL.md`), 13 plugins (a folder with
`.plugin/plugin.json` that can bring skills, hooks and tool connections), 27 automation templates, a list
of 79 integrations (tool servers for GitHub, Slack and others), two "marketplaces" (lists that say which
entries are offered) and three small apps for OpenHands' own screen.

**How the engine uses it.** A skill is offered to the agent and switched on when a message matches it.
A plugin is attached to a session by its folder. With `EXTENSIONS_PATH` set, the engine reads that folder.
Without it, the engine copies the catalogue from GitHub's `main` branch and keeps it up to date at run
time, which we do not allow.

**Copy or implement: both, each for its part.**

| Part | Decision | Why |
|---|---|---|
| The catalogue's content | **Take it as it is**, as a pinned archive in the installer's manifest. Never fetched at run time | It is data in an open format. Rewriting 73 skills gains nothing, and the format lets a public skill work unchanged |
| The short list we show | **Ours.** A marketplace file of our own names the entries offered in Wasify AI, a few to begin with | Most of the 73 are for developers on GitHub, Jira or Slack. A person who is not a developer should not meet them first |
| Wasify's own skills and plugins | **Ours**, in `extensions/` in this repository, in the same format | "Make a logo for this app with Wasify", "explain this project in plain words" |
| The module: list, search, switch on per workspace, add from a folder, trust | **Ours**, in `wasifyai_code/extensions.py` with its own screen | Their screen for this is part of Agent Canvas, which we do not use. Our module reads the format with a small reader of its own and tells the Agent Server what to load |
| Their three apps (kanban, whiteboard, editor) | **Left out** | They are pieces of their screen |
| The integrations list | **Later**, as entries for Settings › Other apps › Tools from other apps | That screen and its trust levels exist already (ADR-0070) |
| The automation templates | **Used by Scheduled** as "start from a template", through our short list | Same reason as the skills |

**Rules.**

- A skill's text is outside content: it can steer the agent, so it is shown before it is switched on
  and it never widens what the agent may do.
- A plugin that brings a hook or a tool connection is approved by the person once, with what it brings
  listed. Hooks from plugins fall under the one-second rule.
- Nothing is fetched while a session runs. Adding from the internet is a later stage with its own approval.
- Every extension the person adds or switches on is found by search, like any other thing they keep.

**Stages.**

| Stage | What is built | Gate |
|---|---|---|
| **X1** (with C1a) | The pinned catalogue installed with the optional part; `EXTENSIONS_PATH` set; our short list as the only marketplace loaded | With the network closed, a session starts and only the short list's skills are offered |
| **X2** (after C3) | The Extensions screen (mockup first): list, details, on and off per workspace, add from a folder; the first of Wasify's own skills | A public skill from the catalogue and one of ours each fire in a real session; switching one off stops it |
| **X3** (with C6) | Plugins with the approval card; templates in Scheduled | A plugin with a hook is refused until approved; a schedule made from a template runs |

## 8. Tests from the first day

| Test | What it is | Runs |
|---|---|---|
| **The fake Agent Server** | A small program that answers the endpoints we use and replays recorded event streams, recorded once from the real one at the pinned version | In `make test`, no model and no network |
| **Loop unit tests** | Every arrow of section 6's states, with the fake server and a fake check: pass, fail then pass, three fails, a timeout, Stop in each state, no change since the last pass, a missing command, the step limit | In `make test` |
| **Contract test** | The same calls against the real pinned Agent Server with a scripted model: every endpoint and event kind we rely on still has the shape our generated types expect, and the trimmed lock still imports | Opt-in, `make test-coding`, and on every change of the pin |
| **The real-model run** | The review's case with a real model, cloud and local | Opt-in, like `make test-comfyui`. It took 54 s with the local Qwen 27B |
| **Hostile tests** | The spike's list: writes outside the workspace, reads of the secret folders, the internet, a model told to try other ways | From C1a for the sandbox, from C2 for the checkpoint store |
| **The evaluation** | The 36 tasks of `docs/spikes/coding-eval-tasks.json` (C0 spike 3), moved into the product with a runner of its own in C1b, as the measure for every later stage and every upgrade of the pin. Sonnet 5.5 must stay at 36 of 36 | Opt-in, before each stage's gate |

## 9. The order of the work

Each piece is its own branch and pull request (`main` is protected). Each piece with a screen starts
with a mockup. A piece is done when its gate is measured, not when its code is written.

| # | Piece | What is done | Gate |
|---|---|---|---|
| 1 | **C0** (outside the repository) | Done: all ten spikes have a result in `docs/spikes/coding-c0.md`. Left over: the install through our own installer on a clean account, which C1a's gate measures anyway | Done |
| 2 | **The ADRs**, after the spikes (owner) | Written and accepted 2026-11-14: ADR-0101 (built on OpenHands' Agent Server), ADR-0102 (an optional part in a sandbox, the key outside), ADR-0103 (the check loop and undo are ours), ADR-0104 (extensions: their catalogue pinned, our module), ADR-0105 (a scheduler of our own) | Done |
| 3 | **C1a The engine in the app, and X1** (no screen of its own) | The pin and the trimmed locks; the optional part in Settings › Optional parts; start in the sandbox with a free port, a new key and a clean environment; health; stop with the app; logs under the data folder; the catalogue pinned; the fake Agent Server for tests | Install, start, stop, repair and uninstall on a clean Mac from Settings. A second copy of the app starts beside it. Nothing is left running, and nothing is left in `/tmp`, after quit. The hostile tests pass. Size, start time and memory written down |
| 4 | **C1b A session that only reads** | The product, the store, the three first actions, the gateway for the model, the live stream relayed over SSE, the session view (mockup first), the Files tab, Plan mode. The agent has no tool that writes or runs anything | The guideline's C1 gate: "Analyse this codebase" gives a correct map of three real projects, and nothing is written anywhere. Stop works within one second at any moment |
| 5 | **C2 Edits with undo** | The checkpoint store outside the workspace, the Changes tab, Ask me mode with our cards and our rules module. `loop.py` and `checks.py` are built here against the fake server, with the check itself not yet allowed to run | The guideline's C2 gate: every change in the evaluation can be undone exactly. The loop's unit tests pass |
| 6 | **C3 Commands, and the loop switched on** | The agent's terminal, the person's Terminal tab, the check run inside the sandbox, package installs through an allow-listed proxy | The guideline's C3 gate, and section 6's gate |
| 7 | **X2 Extensions screen** | Section 7 | Section 7 |
| 8 | **C4 Browser and preview** | The Browser tab, the Preview tab for a running result, the first starter | The guideline's C4 gate, without Wasify's products as tools if spike 6 is not a go yet |
| 9 | **C6 Scheduled, and X3** | Our Scheduled screen on our own scheduler (ADR-0105), each due time calling the same function as the chat; one run of a schedule at a time; the unattended rule, a run on a copy, templates as prompt text, plugins with approval | The guideline's C6 gate: a nightly run on a real project for a week, no missed or doubled run, no change outside its copy |
| 10 | **The v1 gate for coding** | The evaluation with Sonnet 5.5, the hostile tests, a walk of every screen in the real window | Written results; the owner's yes |

## 10. The owner's answers (2026-11-13)

| Question | Answer | What it changes |
|---|---|---|
| Is an optional part of about 600 MB acceptable? | "Acceptable unless there is option to write our own code to make it small." | There is one that is not a new engine: a lock of our own that leaves out unused packages. Measured: 385 MB in place of 573 MB, and the real loop passes |
| (added by the owner) | "I don't see anything about the Extensions module in OpenHands. We need to copy or implement it." | Section 7 |
| May the open spikes start? | "It can start." | Spikes 1, 4, 5 and 10 were run the same day |
| The first model | "Use Sonnet 5.5 first" | The gates are measured with Sonnet 5.5; the local Qwen 27B is the second run |
| A key and a limit for the Sonnet 5.5 spike | "Yes, $10 limit" (the key in Settings › Your keys) | Spike 2 ran; $0.36 spent |
| May the evaluation use what is left? | "Yes, use it" | Spike 3 ran; $5.84 counted in all |
| Scheduled: their automation service or our own scheduler? (2026-11-14) | "We will write our own optimised scheduler" | ADR-0105. No automation service on the desktop in v1; the `/tmp` exception leaves the sandbox profile |
| The five ADRs (2026-11-14) | "Accept all" | ADR-0101 to ADR-0105 are Accepted. The next piece is C1a |
| Desktop and Mac first? | "Coding, automation and extensions will be part of v1. Do desktop and mac first." Also in v1: web browser, file browser, file changes, result preview | Section 2; C6 and the extensions stages move forward |
| The ADRs | "Write after the spikes." | Piece 2 of section 9 |

**Still needed from the owner.**


1. **Nothing about money for now.** The owner allowed $10 under the key in Settings › Your keys; spikes 2
   and 3 used $5.84 as counted, and the gateway is stopped. Later gates on real projects will need a new limit.
2. **Checkpoints (C2):** restore the person's own git state too, or stop the agent from committing?
   Keep `.env` in checkpoints or leave ignored files out?
3. **The short list for Extensions:** the owner picks, or a first proposal comes with the X2 mockup?

## 11. What can go wrong

- **Their release pace.** OpenHands shipped five versions in one week of November. The pin moves about
  monthly, as its own small piece, and only when the contract test and the evaluation pass. The trimmed
  lock makes each move a little more work.
- **Our own scheduler means our own edge cases**: a computer asleep at the time, a change of time zone, the
  hour that does not exist or comes twice when the clocks change. ADR-0105 names them and its gate tests them.
- **`sandbox-exec` is marked deprecated by Apple.** It works on macOS 27 and other coding agents rely on
  it. If a future macOS removes it, commands stop until another isolation is in place; the app must say
  so and fall back to read and edit only.
- **A second safety system.** Their analysers and our rules both judge a command. Ours is loaded as
  their analyser, so there is one answer per command; their other analysers stay off until measured.
- **v1 grows.** Coding, automation and extensions are large additions to a release that was close.
  Section 9's order lets v1 ship after any piece from 6 onwards with the later ones following.

## 12. Sources

- `docs/spikes/coding-c0.md`: the spikes run on 2026-11-13.
- The review of `~/Projects/openhands-integration`, 2026-11-13: its code, the OpenHands SDK 1.62.0 hook
  code in its environment (`openhands/sdk/hooks/`, `conversation/impl/local_conversation.py`,
  `skills/skill.py`), and real runs against a private copy of the Agent Server with the local Qwen 27B.
- `docs/v2-coding-agent-guideline.md`, `docs/v2-cloud-and-engine-plan.md`.
- This repository: `wasifyai_platform_sdk/installer.py`, `wasifyai_api/components/`,
  `wasifyai_api/llama_server.py`, `docs/actions.md`, ADR-0068, ADR-0070, ADR-0092.
