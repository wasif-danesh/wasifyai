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
| Writes | Everything | `<app data>/coding`, the workspaces of sessions that may write, the terminal folder. **Closed again:** `<workspace>/.git` of a workspace that has no git of its own when the engine starts (the Agent Server runs `git init` in a workspace by itself; a person's folder does not become a repository because it was opened) |
| Reads | `/Users`, `/Volumes`, the per-user temp folders, `/tmp`, the app's own data folder | The same three, and read-only: `engine/coding`, the Python it was made with, **the workspaces of sessions that only read**, and `<app data>/coding-fixed` |
| Network | Everything | This computer |
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

## The screens

| Where | What |
|---|---|
| `packages/ui/src/shell/menu.ts` | The group **Code** with Projects, Scheduled and Extensions. The window shows Projects only until the other two are built; the web hides all three (`apps/web/lib/parity.ts`: desktop only) |
| `packages/ui/src/code/Code.tsx` | The first screen (what the agent may and may not do, what leaves this computer, Choose a folder), the projects with their sessions ("Waiting for you" on one that waits), and the session view: the request, the agent's steps as quiet lines that open, its answer, what the turn changed with "Look at the changes" and "Undo this turn", an undone turn with "Bring it back", a plan with "Carry out this plan"; the box with the mode and Stop; the bar with the project, the model, the state and the cost |
| `packages/ui/src/code/Asking.tsx` | The approval card (three answers, and what was answered afterwards), the mode pill with its menu, and "What this project may do" |
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
project's files on disk after each change, undo, "bring it back", yes, no, allow and Stop.

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
| `services/api/tests/integration/test_coding_sandbox.py` | Hostile tests against the real server in its sandbox | `make test-coding`, opt-in |
| `apps/desktop/scripts/ui-audit.sh light coding-setup` (then `coding-repair`, `coding-remove`) | The part set up, repaired and removed from the real window's Settings, with the real downloads | By hand, on a throwaway `DESKTOP_DATA_DIR` |

## Not built

- The dot for files changed in a session, in the Files tab; the Terminal, Browser and Preview tabs; "Start in
  a new, empty folder"; the approval card on other screens while a session waits (the list of projects says
  "Waiting for you"); a project's "More" menu.
- Commands, the check and the implement, check, fix loop: stage C3. Until then a turn that changed files says
  "Not checked", and `loop.py` and `checks.py` are library code that nothing calls. The session's turn is still
  run by `runtime.py`; handing it to `Loop.run_turn` is the first step of C3.
- Dropping old checkpoints. The store under `<app data>/code/checkpoints` grows with the project.
- The scheduler: stage C6.
- A session going on after the app was closed and opened again: the session's token is gone, so its next
  message starts a new conversation with the agent, and the turn says so.
- The coding product's own connection to Wasify's tools (stage C4): `docs/spikes/coding-c1b.md`, "Decided".
- Our own short list of extensions as the only marketplace (the rest of stage X1): it needs a session to show.
- Windows, Linux and Intel Macs (ADR-0102, decision 10).
- A stop that reaches a program which left both its group and its parent. Such a program stays inside the
  sandbox for as long as it lives.
