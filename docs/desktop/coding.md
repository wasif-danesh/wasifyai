# The coding engine on the desktop

Part of [the desktop profile](../desktop-profile.md). ADR-0101 to ADR-0105; the order of the work is in
`docs/v2-coding-agent-start-plan.md`. **Built so far: stage C1a**, the engine in the app; **stage C1b**, a
coding session that only reads, with the menu group Code, Projects, and the session view with its Files tab
(the mockups were approved by the owner on 2026-11-14); and **stage C2**, a session that changes files: the
modes "Ask me" and "Work on its own", the approval card with "Allow for this project", a checkpoint around
every turn, the Changes tab, undo and "Bring it back". The agent runs no command yet (stage C3). Measurements
are in `docs/spikes/coding-c1a.md`, `docs/spikes/coding-c1b.md` and `docs/spikes/coding-c2.md`.

## What it is

The coding agent runs on OpenHands' Agent Server (ADR-0101). The server is an optional part of the app, taken
as four pinned packages, never as source. It is set up by people who want to code, started and stopped by the
Wasify engine, and held inside the macOS sandbox for as long as it runs (ADR-0102). It is offered on
Apple-silicon Macs only. Elsewhere the part says "The coding engine is not available for this computer yet."

| Where | What |
|---|---|
| `services/coding-engine/` | The pins: the one version (`VERSION`), the hashed package list, the list of packages left out, the pinned build tool, the sandbox profile. Its `README.md` says how to move the version |
| `services/api/src/wasifyai_api/components/coding.py` | The optional part "Coding engine (OpenHands)": set up, repair, remove |
| `services/api/src/wasifyai_api/coding_server.py` | Start, health and stop of the server as a child program inside the sandbox |
| `services/api/src/wasifyai_api/desktop_coding.py` | `GET /desktop/coding-engine` and `POST /desktop/coding-engine/stop` |
| `services/api/src/wasifyai_api/coding_gateway.py`, `coding_models.yaml` | The model gateway for coding sessions and the models a session can run on (stage C1b) |
| `products/wasifyai-code/` | The product: the place "this computer" (`client.py`), the sessions in flight (`runtime.py`), the actions, the routes, the rows, search |
| `components/manifests/<platform>.yaml`, `coding` | The lock's SHA-256, the extensions catalogue's address, size and SHA-256, the size shown |

## Setting it up

Settings › Models › **Optional parts** lists "Coding engine (OpenHands)" with Set up, Stop, Repair and Remove,
through the list that every optional part uses (`/components`). Seven steps:

| Step | What happens |
|---|---|
| 1 check | A Mac with the sandbox; the build carries the package list and the profile; there is room |
| 2 uv, 3 python | The app's own uv and Python 3.12.15, as for the image engine |
| 4 environment, 5 packages | An environment of its own in `<app data>/engine/coding/venv`, from the hashed lock, with `--require-hashes --no-deps`. The lock's own SHA-256 is pinned in the manifest and checked first. One package is published as source only and is built here; its build tool is pinned by hash too (`build-constraints.txt`) |
| 6 extensions | The pinned catalogue (`@openhands/extensions` 0.42.0), one archive checked by size and SHA-256, unpacked into `engine/coding/extensions/0.42.0` (ADR-0104, stage X1) |
| 7 verify | The server is started inside its sandbox, must say the pinned version, and is stopped. Only then is `engine/coding/state.json` written |

Repair stops a running server, makes the environment again and fetches the catalogue again. Remove stops the
server and deletes `engine/coding`. It leaves `<app data>/coding`, which holds what the server wrote: that
is the person's work.

The lock leaves out packages that nothing we use imports (`services/coding-engine/leave-out.txt`). What is not
listed is never fetched.

Measured on an M5 Pro (`docs/spikes/coding-c1a.md`): 118 MB to download, 373 MB on disk (the list shows
"about 375 MB"), 19 s to set up, 3.8 s to start, about 370 MB of memory while it runs.

## Running it

`CodingServer.ensure_running(write, read_only)` starts one server per app. The coding product starts it when
a session needs it, with the folders a session may reach; the last step of the setup starts it too, to see
that it answers. Nothing else does.

| Rule (ADR-0102) | How it is done |
|---|---|
| Inside the sandbox | `sandbox-exec -f <app data>/coding/engine.sb`. The profile is `services/coding-engine/engine.sb.template`, filled in at every start. There is no start without it |
| A free port | Chosen on loopback at start, so a second engine on another data folder runs beside this one |
| A new key at every start | A random session key, given to the server in its environment and kept in the engine's memory. It is not in `state()`, a route, a log or a file. The window never has it |
| A clean environment | Built from nothing: its own `HOME`, `TMPDIR`, a short `PATH`. No variable of the engine or of the person reaches it. Its Python is started isolated (`-I`) |
| Its own folders | `<app data>/coding/home`, `state`, `tmp` and `workspace`. Output goes to `<app data>/logs/coding-server.log` (4 MB, then one earlier file is kept) |
| Its own process group | Its own session. Stop ends the group and every program under it, because the server runs each command in a session of its own |
| Nothing left behind | Stop removes its temp folder and its terminal folder |
| If the engine dies | The server holds one end of a pipe from the engine. When the engine goes away without stopping it, the server ends its own group and removes its terminal folder |
| No fetch at run time | `EXTENSIONS_PATH` is always the pinned catalogue. Telemetry is off. The sandbox has no internet anyway |

**The terminal folder.** The server keeps its terminal's sockets in `$TMUX_TMPDIR`, and a socket's whole path must
fit in 104 bytes on macOS. No folder under `~/Library/Application Support/ai.wasifyai.desktop` is short enough.
So one folder is made in `/tmp` at every start (`/tmp/wasify-coding-<8 letters>`, readable by the person only),
named in the profile, and removed at stop. It is the only thing of the coding engine outside the app's data
folder, and only while the server runs.

**Apple's developer tools.** `git` and `make` in `/usr/bin` are stand-ins that look the real program up through
a cache in the per-user temp folder, which the sandbox closes. The developer tools' own folder is therefore put
on the server's `PATH`, so the real programs are used.

## What the sandbox holds

The profile starts from "allow" and closes these. Where two rules match, the later one decides.

| | Closed | Opened again |
|---|---|---|
| Writes | Everything | `<app data>/coding`, the workspaces of sessions that may write, the terminal folder. Since stage C3 the profile no longer closes `<workspace>/.git`: the Agent Server's own `git init` is switched off in our rules module instead, and the agent may make a repository when it is asked to |
| Reads | `/Users`, `/Volumes`, the per-user temp folders, `/tmp`, the app's own data folder | The same three, and read-only: `engine/coding`, the Python it was made with, **the workspaces of sessions that only read**, and `<app data>/coding-fixed` |
| Network | Everything | This computer. Since stage C3 that includes our install proxy on loopback, which lets a program through to the package indexes on its list and nowhere else (below) |
| Other programs | A signal to a process outside the sandbox, opening an app or a file with `open`, a message to another app, a job handed to the system | Signals inside the sandbox |

The system and the tools stay readable: `/usr`, `/bin`, `/System`, `/Library`, `/opt/homebrew`, `/Applications`.
The rule on other programs is new in this stage: the profile of the C0 spikes let a command open any app, and
so run a file outside the sandbox (`docs/spikes/coding-c1a.md`).

The profile is not edited by hand at run time and never widened by a request. A workspace is a folder the
person chose; `ensure_running(write, read_only)` restarts the server when either list changes, because a
profile cannot change while its process runs.

## A session that only reads (stage C1b)

Every session of this stage is in the plan's "Plan mode": the agent finds and reads files and gives an
answer or a plan. It cannot change a file or run a command. Three things hold that, each by itself:

| | How |
|---|---|
| The tools | The session is made with three of the Agent Server's tools and no others: find files by name (`glob`), search in files (`grep`), and look at a file (`planning_file_editor`). The terminal, the file editor and the patch tool are not given |
| The one file the viewer could edit | The viewer may edit one file, its "plan". That file is `<app data>/coding-fixed/PLAN.md`, made by the Wasify engine in a folder the sandbox lets the server read and not write |
| The sandbox | The session's workspace is opened to the server for reading only. A write there is refused by the operating system, whatever asks for it |

Which folders can be a workspace is checked before anything is opened (`runtime.check_folder`): one project's
folder, never the home folder or a disk, the app's own data, the Library, or a hidden folder at the top of
the home folder. Opening one of those would hand the engine what the sandbox exists to keep from it.

**Who talks to whom.**

```
action or route -> wasifyai_code.runtime.Sessions -> wasifyai_code.client.ThisComputer -> Agent Server (sandbox)
                     rows in <app data>/code/code.db        |  one live socket per turn       |
                     the relay inside the engine (Feed)     |                                 |  model calls, with a token
                                                            +-- wasifyai_api.coding_gateway <-+
                                                                 the key, from the secret store -> the provider
```

- **`client.py` is the only file that knows the Agent Server's API.** It makes a conversation, sends, stops
  (the server's interrupt, which cancels the model call in flight), and follows one live socket. After a drop
  it connects again and asks for what came since the last event it had; an event that arrives twice is
  dropped. It listens before it sends, because words as they are written go only to who is listening.
- **`events.py` says the server's events in the place's own words** (state, text, piece, step, result,
  confirm, ended) and works out how a turn ended: finished, stopped, the step limit, an error, or a refusal
  by the model. The shapes it reads are in `agent_types.py`, generated from the Agent Server's API
  description at the pinned version (`scripts/coding-engine-types.py`; the part we rely on is kept in
  `services/coding-engine/api-excerpt.json`).
- **One server serves every session.** It is started with every folder the person has opened as a
  workspace, so a session on a known folder starts nothing. A folder that is new means the server starts
  again; that is refused, in words, while another session is in the middle of a turn.
- **A turn that only reads changes no word.** No checkpoint is taken and no check runs; the session's result
  stays what it was. The implement, check, fix loop (`loop.py`) takes over with the modes that edit (C2).
- **The session's events go to the window as one stream per session** (`runtime.Feed`,
  `GET /code/sessions/{id}/events`), in the kinds the owner agreed on 2026-11-14: `code_state`, `code_message`
  and `code_refusal` are new, `tool_call`, `tool_result`, `token` and `reasoning` are reused
  (`docs/contracts/sse-events.md`, "A coding session's stream"; ADR-0101's amendment). Words as they are
  written are not kept; a window that comes later gets the finished message.

## A session that changes files (stage C2)

A session has a mode: `plan` (it only reads), `ask` or `own`. The engine's default is `plan`; a project opened
on the Code screen starts in "Ask me". In `ask` and `own` the agent gets three tools: find files, search in
files, and the file editor. It has no terminal, no patch tool and no browser, so it runs nothing.

| Step | What happens |
|---|---|
| Before the turn | A checkpoint of the project (`checkpoints.py`) in `<app data>/code/checkpoints/<workspace id>`: outside the project, and inside the app's data, which the sandbox closes to the coding engine for reading and writing |
| A change | Every use of the editor that changes something waits in the coding engine before it runs (`services/coding-engine/wasify_rules.py`, loaded with `--import-modules`, and the policy "ask when high"). `rules.py` then decides, in the Wasify engine: no rule asks about it (let through at once), its kind is allowed for the project (let through, and marked "allowed"), the session works on its own (let through), or the person is asked |
| The card | `interrupt` on the stream with `kind: "code_ask"`. Answers: yes, no, "Allow for this project" (`POST /sessions/{id}/asks/{id}`). After a no the agent is told and goes on another way. Stop while a card waits refuses what waits and ends the turn |
| After the turn | A second checkpoint. What the turn changed is the difference; `code_state` `done` carries `changed` |
| Undo | `POST /sessions/{id}/turns/{id}/undo` puts every file back (content, permissions, added and deleted files, empty folders) and the person's own git (`HEAD`, the index). One more checkpoint is taken first, so `.../redo` ("Bring it back") returns the turn |

The kinds of request are a fixed list (`rules.KINDS`): `not_undoable` (a file a checkpoint does not hold: one
the project ignores, or one inside a `.git` folder), `delete` and `install`. Only the first can come up while the
agent cannot run a command. An allowance is kept on the workspace's row, for one project and one person.

Three things the pinned Agent Server does, each found by a real run (`docs/spikes/coding-c2.md`):

- Its file editor cannot create a file in a folder that does not exist, and the agent has no command to make
  one. The place makes the missing folders, inside the project only, at the moment a "create" is let through.
- It runs `git init` in a workspace that is not a repository. The sandbox profile refuses it (the table above).
- An interrupt does nothing to a conversation that waits for a yes or no. Stop refuses what waits first.

Undo goes back one turn at a time, the newest that stands first. Files the project ignores are not kept and not
put back. What the person changed themselves after the turn goes back with it, and the answer says so.

## Commands, the check and the terminal (stage C3)

A session in `ask` or `own` now has four tools: find files, search in files, the file editor and a terminal.
The terminal is the Agent Server's own and runs inside the server's sandbox. A session in `plan` still has
none of the last two.

| What | How |
|---|---|
| A command | Every use of the terminal waits before it runs, like every change (`wasify_rules.py`, `wait_tools`). `rules.command_kind` reads the command's words: `delete` (`rm`, `rmdir`, `git clean`, `git reset --hard`, `git checkout -- .`, `find -delete`), `install` (`pip install`, `uv add`, `npm install`, `pnpm add`, `yarn`, `npx`, `cargo add`, `go get`, `brew install` and the like), or neither. In "Ask me" a kind that is not allowed for the project is asked with the same card; in "Work on its own" nothing is asked |
| An install | The sandbox reaches this computer only. The programs inside are given `HTTPS_PROXY` and its relatives, pointing at `coding_proxy.InstallProxy` on loopback. It opens a tunnel only to the hosts of `coding_install_hosts.txt` (PyPI, npm and Yarn, crates.io, the Go proxy, RubyGems) on port 443. The agent's commands and the check are let through only for ten minutes after an install step was let through; the person's terminal always. It keeps the host of each request and whether it was let through, nothing else |
| A repository | The Agent Server's `git init` at the start of a conversation is replaced by nothing in `wasify_rules.py`. The agent can run `git init` itself |
| The turn | Run by `Loop.run_turn` (`loop.py`), through the hooks `runtime.py` gives it. The states of a turn are those of section 6 of the start plan |
| The check | One command for each project, kept on the workspace's row. `checks.suggest` reads the project's files and suggests; nothing is set until the person saves it. After a turn that changed files it runs in a sandbox of our own for that project (`CodingServer.sandbox_for`: the same profile template, filled for the one folder), in its own process group, with a time limit (ten minutes unless changed). Its whole output is a file under `<app data>/code/check-output/` |
| A failure | The command, the exit code and the end of the output go back to the agent, which goes on. Three rounds; then the turn ends "failed" and "needs you". A check that could not run (not found, the time limit, a crash) is "could not check", never "passed". A turn that changed nothing runs no check, and the last word stands |
| Stop | Ends a running check at once (its whole process group), interrupts the agent, and the turn is "not checked" |
| The person's terminal | `terminal.py`: a shell (`zsh -f -i`) on a pseudo-terminal, started by the Wasify engine inside the project's own sandbox, with its controlling terminal set by a small launcher in a child of its own. Output goes to the window as a stream, input and the size come back as calls. Up to four for a session. Closing one ends the shell and everything under it. Nothing typed or printed is kept on disk; the last 512 KB of output are held in memory so a tab can be opened again |

What a person meets in the terminal: the home folder is the sandbox's own, so their start-up files are not
read; `ps`, `top` and `sudo` do not work; `python3` is the coding engine's own Python unless the project has an
environment; a write outside the project is refused by the operating system. The tab says the first three.

## Node, the preview, a new project and Wasify AI's own products (stage C4)

| What | How |
|---|---|
| Node | The optional part "Node for coding projects" (`components/node.py`, pinned in `components/manifests/darwin-arm64.yaml`): the Node LTS release from nodejs.org under `<app data>/engine/node/<version>/`, about 53 MB to fetch and 199 MB on disk. `find_node` gives its `bin` folder; `coding_server._environment` puts it first on the sandbox's path (after our own commands) and the profile opens it for reading. The Agent Server sees it from its next start; the check, the preview and the person's terminal at once |
| The preview | `preview.py`: the project's own command (`npm run dev`), started by the Wasify engine in the project's sandbox with `PORT` (a free port) and `HOST=127.0.0.1`. The engine looks, from outside, at which ports the processes under it listen on, and whether on a local address only. One preview for a session; starting again stops the old one; Stop ends everything under it. The end of its output is held in memory |
| The page | The Preview tab shows `http://localhost:<port>/` in a frame, wide or as a phone, with "Load again", "Stop" and "Open in your own browser". It is loaded again when a turn changes files. When the program listens on every address the tab says that other computers on the network can open it: the sandbox cannot forbid that |
| A new project | `starters.py`: "Start in a new, empty folder" copies a starter's files into `<chosen folder>/<name>` (a folder that holds files is refused) and opens a session on it in "Ask me", with the starter's check and preview set. The first starter, `web`, is one page with its script, styles and tests and a small server of its own that loads the page again on a change; it needs Node and nothing installed |
| A picture or speech | `assets.py` and `services/coding-engine/wasify-make`. The agent runs `wasify-make picture "<what>" <file.png>` or `wasify-make speech "<words>" <file.wav>` alone, as the whole command. It waits like every command; its kind, `make`, is asked in every mode until allowed for the project. On a yes the Wasify engine runs `image.generate` or `speech.speak` for the person through the action executor, copies the result into the project and leaves a note under `<app data>/coding-fixed/made/`; the command then prints what the note says. What was made is in the person's library too |

## Extensions: the skills a session is taught (stage X2)

| What | How |
|---|---|
| A skill | A folder with a `SKILL.md`: a few first lines (name, what it is for, the words that switch it on) and the text for the agent. `extensions.py` reads it with a small reader of its own |
| What is offered | Our short list, `wasifyai_code/own/marketplace.json`: Wasify AI's own skills (`own/skills/`) and a few entries of the pinned OpenHands catalogue, by name. Then what the person added. The rest of the catalogue stays on disk, unused |
| On or off | Kept for one project and one person (`extension_switches` in the store); without a switch the short list's own word holds. A switch lets go of the conversations of the project's sessions that are at rest, so the next message starts with the new skills |
| What a session is given | `Sessions.skills_for`: the skills that are on, each with its whole text, in the conversation's context (`agent_context.skills`). The engine's own loaders stay off. The skills' folders are copied to `<app data>/coding-fixed/skills/`, which the sandbox reads and cannot write |
| When one fires | The engine puts a skill's text into the person's message when the message has one of its words, and says so; the stream carries it as `code_skills` and the chat shows "Using the skill ..." |
| Adding one | "Add from a folder": the folder is looked at first (its text is shown), then copied into `<app data>/code/extensions/<id>/`. A plugin (`.plugin/plugin.json`) is refused; that is stage X3 |
| Search | An added skill is in the Library as "Coding skill" (kind `code_extension`), indexed by its name and what it is for, in the same index source as coding sessions |

## The screens

| Where | What |
|---|---|
| `packages/ui/src/shell/menu.ts` | The group **Code** with Projects, Scheduled and Extensions. The window shows Projects only until the other two are built; the web hides all three (`apps/web/lib/parity.ts`: desktop only) |
| `packages/ui/src/code/Code.tsx` | The first screen (what the agent may and may not do, what leaves this computer, Choose a folder), the projects with their sessions ("Waiting for you" on one that waits), and the session view: the request, the agent's steps as quiet lines that open, its answer, what the turn changed with "Look at the changes" and "Undo this turn", an undone turn with "Bring it back", a plan with "Carry out this plan"; the box with the mode and Stop; the bar with the project, the model, the state and the cost |
| `packages/ui/src/code/Asking.tsx` | The approval card (three answers, and what was answered afterwards), the mode pill with its menu, and "What this project may do" |
| `packages/ui/src/code/Checks.tsx` | The check: its word in the session's bar (it opens the dialog), the card of each run in the chat (checking with "Stop the check", passed, failed with the end of the output and "sent back to the agent", "needs you" with "Try 3 more rounds" and "Undo this turn", not checked with "Run the check now", could not check with "Change the check"), the tests the agent changed, and the dialog: the command, the suggestions, "Try it now", "No check for this project", the time limit |
| `packages/ui/src/code/Terminal.tsx`, `xterm-css.ts` | The Terminal tab: the note about its limits, the person's terminals as small tabs, "New", and the terminal itself drawn by xterm.js, which is loaded when the tab is first opened. Its style sheet is carried as text, so no bundler has to load one from a package; a test compares it with the package's |
| `packages/ui/src/code/Preview.tsx` | The Preview tab: the suggested command and "Change the command", starting, the page in a frame with its bar, why a preview ended (its exit code and output; where Node is set up when a tool was not found), and the warning when it listens to more than this computer |
| `packages/ui/src/code/NewProject.tsx` | "Start in a new, empty folder": the starter, the project's name, the folder it is made in |
| `packages/ui/src/code/Extensions.tsx` | Code › Extensions: the list for the project chosen at the top, with a switch on each row, a search and filters; "Details" with the whole text, the note that it comes from outside and cannot widen what the agent may do, and a switch for each project; "Add from a folder" with what was found; removing one the person added |
| `packages/ui/src/code/Changes.tsx` | The Changes tab: one turn at a time, its files (a test file is marked), one file before, after or both, "Undo this turn" and "Bring it back", and what undo does not put back |
| `packages/ui/src/code/Files.tsx` | The Files tab beside the chat: the project's folders as a tree, opened a folder at a time, and one file to read with its line numbers. Reading only. On a narrow window the chat and the files are two tabs |
| `packages/ui/src/code/thread.ts`, `use-code.ts` | The stream turned into what is drawn, and the screen's state. A turn from before the app was started shows what was kept: the request, the answer and how many steps it took |
| `packages/client/src/code.ts` | The window's calls: the routes above and the stream |
| `apps/desktop/src/pages/Code.tsx` | The page in the window, with the computer's own folder window (Tauri's dialog plugin, which the app already had; the window is now allowed to open it) |

A session has an address of its own in the window (`#/code/<id>`): it is still open after a reload, and Back
leaves it. "Find a file by name" in the Files tab looks through the project's file names (not into
`node_modules`, `.git` and the like, and never through a link). The cost in the bar opens to what it is made
of (the model, its calls, what was asked) and the session's limit, which can be changed there
(`PATCH /sessions/{id}`; it holds from the next model call). A session is a card in the Library under its own
filter, "Coding sessions", and a search result opens it at its address.

A session that nobody named is called by what was asked first. Walk it for real with
`WASIFYAI_AUDIT_FOLDER=<a project> apps/desktop/scripts/ui-audit.sh light code-plan` on a throwaway
`DESKTOP_DATA_DIR` that has the coding engine (pictures `docs/ui-audit/desktop/code-*.png`). The walk of a
session that changes files is `... ui-audit.sh light code-edit` (pictures `code-edit-*.png`): it reads the
project's files on disk after each change, undo, "bring it back", yes, no, allow and Stop. The walk of stage C3
is `... ui-audit.sh light code-check` on an empty throwaway folder (pictures `code-check-*.png`): the check set
and tried, a failed round and a pass, a two-minute check, Stop, "needs you", the terminal, a delete that is
asked first, and `git init` by the agent.

## The model gateway (ADR-0102, decision 4)

The Agent Server never holds a model key and cannot reach the internet. It is given this engine's own
address on loopback and a token for one session, and every model call of that session comes to
`/coding-gateway/...` on the Wasify engine.

| What | How |
|---|---|
| The token | Made per session, kept in memory only, dead when the session is deleted or the app closes. It is the route's identity: the tenant, the product and the person come from it. An unknown token is refused. The real key opens nothing here |
| The key | Read from the app's secret store for each call and put on it (`keys.chat.anthropic`, the key saved for Chat and writing in Settings › Your keys). Never answered back, logged or written |
| The model | Only the model the session was opened with is let through. The list is `coding_models.yaml`: Claude Sonnet 5.5 first; the local Qwen 27B through Ollama second, offered only when `CODING_OLLAMA_URL` is set |
| The body | Passed on byte for byte, so the provider's prompt-cache marks arrive as the Agent Server wrote them |
| Streaming | Passed through event by event |
| Tokens and cost | Each call's tokens become usage events (`llm.input_tokens`, `llm.output_tokens`, capability `code.agent`) and its counted cost is added to the session's row. At the session's limit (5 dollars unless the session says otherwise) the next call is refused, and the turn ends saying so |
| A refusal | When the model declines (`stop_reason: "refusal"`), the Agent Server is answered with a plain message and no tool call, which ends its turn. The turn ends as "refused" with the model's own words. It is not an error |

## The product's actions and routes

| Action | What |
|---|---|
| `code.session.start` | A session on a folder. Nothing runs and nothing is read yet |
| `code.session.send` | A message; waits for the agent's answer (a long action: it can become a job, and cancelling the job stops the turn) |
| `code.session.stop` | Stops the turn at once |
| `code.session.undo` | Puts the project's files back to before a turn (the newest that changed files, when none is named) |
| `code.session.check` | Reads the project's check, sets it, and runs it now (a long action) |
| `code.session.preview` | Starts the project's preview, stops it, or says where it is (a long action) |
| `code.project.new` | A new project from a starter in a new folder, with a session on it |
| `code.extension.list`, `code.extension.switch`, `code.extension.add` | The skills offered and which are on for a project (and one skill's whole text); switching one on or off; adding one from a folder |

They are offered to the assistant and not to outside apps: an outside app that could open a session on any
folder would be handed that folder's content. Help is in `docs/help/code.session.*.md`.

| Route (under `/products/wasifyai-code/code`) | What |
|---|---|
| `GET /models` | The models a session can run on, and whether each is ready (never a key) |
| `POST /sessions`, `GET /sessions` (`ids=`), `GET /sessions/{id}`, `DELETE /sessions/{id}` | Start, list, look at (state, answer, cost) and forget a session |
| `GET /sessions/{id}/turns` | Each turn: the request, how it ended, the answer, the steps |
| `POST /sessions/{id}/messages` | Begin a turn (202); the agent works on in the engine |
| `POST /sessions/{id}/stop` | Stop the turn; answers when it is closed |
| `GET /sessions/{id}/files?path=`, `GET /sessions/{id}/file?path=` | One folder of the project, and one file to read (`wasifyai_code/files.py`). The Wasify engine reads them for the person; the coding engine is not asked. A path is always inside the project, also through a link; the project's `.git` is left out; a file over 400 kB is cut at a line and says so; a file that is not text says so |
| `GET /sessions/{id}/files/find?q=` | The project's files whose name holds `q`, at most 50 |
| `PATCH /sessions/{id}` | Change the most the session may cost (`cost_limit_usd`), or its mode (`mode`: between `ask` and `own` at once, also in the middle of a turn; to or from `plan` only when no turn runs, and the next message begins a new conversation that is given the last answer) |
| `POST /sessions/{id}/asks/{ask_id}` | Answer an approval card: `yes`, `allow` or `no` |
| `GET /sessions/{id}/changes`, `GET /sessions/{id}/changes/{turn_id}/file?path=` | The turns that changed files with their files, and one file before, after and as lines |
| `POST /sessions/{id}/turns/{turn_id}/undo`, `.../redo` | Undo a turn, and bring it back |
| `GET /sessions/{id}/project`, `PUT /sessions/{id}/project/allowed/{kind}` | What the project may do, and allowing a kind or taking that back |
| `GET /sessions/{id}/check`, `PUT /sessions/{id}/check` | The project's check (command, where it came from, the time limit, what the files suggest, the session's last checks), and setting it (`command`, empty for none; `limit_s`) |
| `POST /sessions/{id}/check/run`, `GET /sessions/{id}/checks/{check_id}` | Run the check now, outside a turn (it answers when the check has ended; Stop ends it), and one check with its whole output |
| `POST /sessions/{id}/check/again` | "Try 3 more rounds": a new turn that tells the agent the check still fails (202) |
| `GET /sessions/{id}/preview`, `PUT /sessions/{id}/preview` | The project's preview (its command, what the files suggest, and the running one: state, port, address, whether it is open to the network, the end of its output), and setting the command |
| `POST /sessions/{id}/preview/start`, `POST /sessions/{id}/preview/stop` | Start it (an optional `command` is kept as the project's) and stop it |
| `GET /workspaces` | The person's projects, the newest first |
| `GET /extensions` (`workspace_id=`, `ids=`), `GET /extensions/{id}` | What is offered, with whether each is on for a project; one extension with its whole text and where it is on |
| `PUT /extensions/{id}/on` | Switch it on or off for a project (`workspace_id`, `on`) |
| `POST /extensions/look`, `POST /extensions`, `DELETE /extensions/{id}` | What a folder holds before it is added; adding it (with `workspace_id` it is switched on there); forgetting one the person added |
| `GET /starters`, `POST /projects` | What a new project can be started from, and making one (`parent`, `name`, `starter`, `model`, `mode`) |
| `GET /sessions/{id}/terminals`, `POST /sessions/{id}/terminals` | The person's terminals in this session, and opening one (`cols`, `rows`) |
| `GET /sessions/{id}/terminals/{tid}/events` | What the terminal prints, as a stream: `terminal_output` (`data`: the bytes in base64) and `terminal_ended` (`exit_code`); `Last-Event-ID` comes back after a number |
| `POST .../terminals/{tid}/input`, `POST .../terminals/{tid}/size`, `DELETE .../terminals/{tid}` | What the person typed (`data`), the window's size, and closing it |
| `GET /sessions/{id}/events` | The session's stream, open across turns; `Last-Event-ID` comes back after a number |

A session is found by search (ADR-0041) by its title, its project's name and what was asked first (kind
`code_session`). Its card and its filter in the Library come with the screens.

## Routes

Both are under `/desktop`, need a signed-in person like every route, and never give out the session key.

| Route | What |
|---|---|
| `GET /desktop/coding-engine` | `supported`, `installed`, `version`, `extensions`, `running`, `pid`, `port`, `workspaces`, `read_only`, `start_seconds`, `memory_bytes` |
| `POST /desktop/coding-engine/stop` | Stop it and everything it started. Turns in flight end as "stopped" first. The next message of a session starts it again |

These are for diagnostics and for giving the memory back. A coding session never goes through them: the
window calls the coding product's actions, and the product calls the engine (ADR-0101, decision 4). The route
that started the server by hand (stage C1a) is gone: a start with other folders than the running server has
starts it again and cuts off every session in the middle of its turn (`docs/spikes/coding-c1b.md`).

## Tests

| Test | What | Runs |
|---|---|---|
| `services/api/tests/test_coding_server.py` | The supervisor against the fake server: the profile, the start, the key, the clean environment, the stop, the guard, the routes. One test runs the real `sandbox-exec` with a real start's profile and a shell | `make test` |
| `services/api/tests/test_components_coding.py` | The part against the fake: seven steps, refusals, repair, remove, the platforms where it is not offered, and that the pin, the manifests and the lock agree | `make test` |
| `services/api/tests/fake_agent_server.py` | The fake Agent Server: the endpoints the supervisor and the product use, started the way the real one is. Its "agent" replays event streams recorded from the real server (`tests/fixtures/coding/`) | - |
| `services/api/tests/test_coding_gateway.py` | The gateway against a pretended provider: the token, the key, the body byte for byte, streaming, tokens and cost, the limit, a refusal | `make test` |
| `services/api/tests/test_coding_sessions.py` | A session from the routes down to the fake server: the tools of a session that only reads, the events, a dropped socket, Stop at any moment, one server for several workspaces, the folders that are refused | `make test` |
| `products/wasifyai-code/tests/test_code_events.py`, `test_code_sessions.py` | The event translation and the sessions on the pretended place | `make test` |
| `products/wasifyai-code/tests/test_code_edits.py` | A session that changes files, on the pretended place with a real git: the checkpoints, the card and its three answers, allowances, the Changes data, undo and "bring it back" (files compared byte for byte, with permissions), the person's own git, the rules | `make test` |
| `services/api/tests/integration/test_coding_session_real.py` | The same against the real server in its sandbox with a scripted model: a session that only reads, and one that edits (it waits, a yes, a no, Stop while it waits, nothing outside the project, the checkpoint store out of reach, no `.git` made). It records the event streams the fake replays | `make test-coding`, opt-in |
| `products/wasifyai-code/tests/test_code_checked.py` | Sessions whose turns are checked, on the pretended place with a real check command: the review's case (one refusal, one fix, one pass, the check file untouched), three rounds and "needs you", a question in a project whose check fails, no check set, Plan, Stop during a check, a check that runs while other calls answer, the check's settings, which command is suggested, what kind a command is, and the questions before a command | `make test` |
| `products/wasifyai-code/tests/test_terminal.py` | The person's terminal without a sandbox: a real shell on a real pseudo-terminal, the size, Ctrl-C, closing ends what it started, the limit of four, and no terminal where there is no sandbox | `make test` |
| `services/api/tests/test_coding_proxy.py` | The install proxy on loopback: the person let through, the agent only while an install is allowed, every other request refused, and no password in what it says of itself | `make test` |
| `products/wasifyai-code/tests/test_code_c4.py` | The preview with a real program on a real port (found by its port, open to the network or not, why it ended, a new start replaces the old), which command is suggested, the starter (its files, its refusals, its own check and page), and `wasify-make`: how a call is read, the card in every mode, the app's action run for the person, the file in the project, the note, a no, a failure | `make test` |
| `products/wasifyai-code/tests/test_code_extensions.py` | The reader, every skill of ours, the short list and the switch for a project, what a session is started with and that a switch begins a new conversation, the skills a message switched on, adding from a folder (looked at, copied, links left out, found by search, refusals, removal) | `make test` |
| `services/api/tests/test_components_node.py` | The Node part against a fake download: four steps, the folder the sandbox is given, a wrong checksum, a Node that does not start, a state file that points outside | `make test` |
| `services/api/tests/integration/test_coding_sandbox.py` | Hostile tests against the real server in its sandbox | `make test-coding`, opt-in |
| `apps/desktop/scripts/ui-audit.sh light coding-setup` (then `coding-repair`, `coding-remove`) | The part set up, repaired and removed from the real window's Settings, with the real downloads | By hand, on a throwaway `DESKTOP_DATA_DIR` |

## Not built

- The dot for files changed in a session, in the Files tab; the Browser tab (a second webview in the real
  window; it is its own piece after C4); the approval card on other screens while a session waits (the list of projects says "Waiting
  for you"); a project's "More" menu.
- Plugins (a folder that brings hooks or tool connections), adding an extension from the internet, the
  integrations list, changing a skill's text in the app: stage X3 and later.
- "Show what is running": the list of everything started in a project by the person, the agent or a check,
  with a way to stop each (mockup `terminal-processes`). The Terminal tab says that `ps` does not work and
  offers nothing in its place yet.
- Build, lint and test as separate steps of the check; the number of rounds in the dialog; the check's output
  through the storage interface.
- What is asked in every mode (going on past the cost limit).
- Other managed tools than Node (Python with `pytest`, Rust, Go): the sandbox finds what the computer has in
  system folders and Homebrew. More starters than the one web app.
- 3D models, music and video through `wasify-make`; a picture the agent can look at.
- Dropping old checkpoints. The store under `<app data>/code/checkpoints` grows with the project.
- The scheduler: stage C6.
- A session going on after the app was closed and opened again: the session's token is gone, so its next
  message starts a new conversation with the agent, and the turn says so.
- The coding product's own connection to Wasify's tools (stage C4): `docs/spikes/coding-c1b.md`, "Decided".
- Our own short list of extensions as the only marketplace (the rest of stage X1): it needs a session to show.
- Windows, Linux and Intel Macs (ADR-0102, decision 10).
- A stop that reaches a program which left both its group and its parent. Such a program stays inside the
  sandbox for as long as it lives.
