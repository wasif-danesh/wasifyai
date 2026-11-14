# The coding engine on the desktop

Part of [the desktop profile](../desktop-profile.md). ADR-0101 to ADR-0105; the order of the work is in
`docs/v2-coding-agent-start-plan.md`. **Built so far: stage C1a**, the engine in the app. There is no coding
screen and no coding session yet: the product `wasifyai-code` comes with stage C1b. Measurements of this stage
are in `docs/spikes/coding-c1a.md`.

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
| `services/api/src/wasifyai_api/desktop_coding.py` | `GET /desktop/coding-engine`, `POST /desktop/coding-engine/start` and `/stop` |
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

`CodingServer.ensure_running()` starts one server per app. Nothing starts it yet except the route below and
the last step of the setup; from C1b the coding product starts it when a session needs it.

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
| Writes | Everything | `<app data>/coding`, the workspaces a session was given, the terminal folder |
| Reads | `/Users`, `/Volumes`, the per-user temp folders, `/tmp`, the app's own data folder | The same three, and read-only: `engine/coding` and the Python it was made with |
| Network | Everything | This computer |
| Other programs | A signal to a process outside the sandbox, opening an app or a file with `open`, a message to another app, a job handed to the system | Signals inside the sandbox |

The system and the tools stay readable: `/usr`, `/bin`, `/System`, `/Library`, `/opt/homebrew`, `/Applications`.
The rule on other programs is new in this stage: the profile of the C0 spikes let a command open any app, and
so run a file outside the sandbox (`docs/spikes/coding-c1a.md`).

The profile is not edited by hand at run time and never widened by a request. A workspace is a folder the
person chose; `ensure_running(workspaces)` restarts the server when the list changes, because a profile cannot
change while its process runs.

## Routes

All three are under `/desktop`, need a signed-in person like every route, and never give out the session key.

| Route | What |
|---|---|
| `GET /desktop/coding-engine` | `supported`, `installed`, `version`, `extensions`, `running`, `pid`, `port`, `workspaces`, `start_seconds`, `memory_bytes` |
| `POST /desktop/coding-engine/start` | Start it (409 with a sentence when it is not set up or did not start) |
| `POST /desktop/coding-engine/stop` | Stop it and everything it started |

These are for this stage's checks and for diagnostics. A coding session never goes through them: the window
calls the coding product's actions, and the product calls the engine (ADR-0101, decision 4).

## Tests

| Test | What | Runs |
|---|---|---|
| `services/api/tests/test_coding_server.py` | The supervisor against the fake server: the profile, the start, the key, the clean environment, the stop, the guard, the routes. One test runs the real `sandbox-exec` with a real start's profile and a shell | `make test` |
| `services/api/tests/test_components_coding.py` | The part against the fake: seven steps, refusals, repair, remove, the platforms where it is not offered, and that the pin, the manifests and the lock agree | `make test` |
| `services/api/tests/fake_agent_server.py` | The fake Agent Server: the endpoints the supervisor uses, started the way the real one is | - |
| `services/api/tests/integration/test_coding_sandbox.py` | Hostile tests against the real server in its sandbox | `make test-coding`, opt-in |
| `apps/desktop/scripts/ui-audit.sh light coding-setup` (then `coding-repair`, `coding-remove`) | The part set up, repaired and removed from the real window's Settings, with the real downloads | By hand, on a throwaway `DESKTOP_DATA_DIR` |

## Not built

- The product, its screens, the model gateway, the check loop, the scheduler: stages C1b onwards.
- Our own short list of extensions as the only marketplace (the rest of stage X1): it needs a session to show.
- Windows, Linux and Intel Macs (ADR-0102, decision 10).
- A stop that reaches a program which left both its group and its parent. Such a program stays inside the
  sandbox for as long as it lives.
