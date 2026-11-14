# Coding agent, stage C1a: the engine in the app

Measured 2026-11-13 and 14 on the owner's Mac (M5 Pro, macOS 27.0). The stage is piece 3 of
`docs/v2-coding-agent-start-plan.md`, section 9: OpenHands' Agent Server 1.62.0 as an optional part of the
desktop app, started and stopped inside the macOS sandbox by the Wasify engine, with the extensions
catalogue 0.42.0 pinned beside it (stage X1). What was built is described in `docs/desktop/coding.md`.

The owner allowed two fetches for this stage ("Yes, fetch them", 2026-11-13): the four OpenHands packages
with what they need, and the extensions catalogue. Nothing else was fetched. Python 3.12.15 was copied from
the app's existing install into each throwaway data folder. No paid model was used and no key was read.

## The gate

| Gate (section 9, piece 3) | Result | How it was measured |
|---|---|---|
| Install from Settings | **Passed.** 19.0 s, with the real downloads | The real window's Settings › Optional parts, "Set up" clicked, on a new data folder (`ui-audit.sh light coding-setup`) |
| Repair from Settings | **Passed.** 25.0 s. A package file overwritten and a skill deleted beforehand were both back afterwards | "Repair" clicked in the same window (`coding-repair`) |
| Uninstall from Settings | **Passed.** 1.9 s. `engine/coding` gone; the server's own folder and a file in its workspace kept | "Remove" and its confirmation clicked (`coding-remove`) |
| Uninstall while the server runs | **Passed.** The server was gone within 1.1 s, nothing in `/tmp` | `POST /components/coding/uninstall` on a running engine |
| Start | **Passed.** 3.8 s in the real app (6.1 s the first time after a set-up) | The real shell (`target/debug/wasifyai-desktop`) on a throwaway data folder under `~/Library/Application Support`; `POST /desktop/coding-engine/start` with a token signed as the window's is |
| Stop | **Passed** | `POST /desktop/coding-engine/stop`, and the three ways of quitting below |
| A second copy beside the first | **Passed for two engines; a second launch of the app is refused by the shell.** See "A second copy" | A second engine on another data folder, both coding engines running at once |
| Nothing left running after quit | **Passed** | Quit, then the shell killed outright, then the engine killed outright: see "Quit" |
| Nothing left in `/tmp` after quit | **Passed** in all three | `ls /tmp/wasify-coding-* /tmp/openhands-agent-server-*` after each |
| The hostile tests pass | **Passed: 30 of 30**, three times | `make test-coding` against the install made from Settings, against a copy of it under `~/Library/Application Support`, and against the untrimmed packages |
| Size, start time, memory written down | Below | |
| `make test` and `make lint` | **Passed** | See "Tests" |

Not measured is listed at the end.

## Numbers

| | Measured |
|---|---|
| Packages the four OpenHands packages resolve to (Python 3.12, Apple silicon) | 194 |
| Packages in our lock, after eight are left out | **186** |
| Download, our lock | **114.4 MB** (the files PyPI serves for this computer, summed from PyPI's own sizes) |
| Download, without leaving anything out | 157.6 MB |
| Download, the build tool (`setuptools` 80.9.0) | 1.2 MB |
| Download, the extensions catalogue 0.42.0 | 2.8 MB (2,808,448 bytes, 999 files) |
| **Download in all** | **118.4 MB** |
| On disk, the environment | 362 MB (573 MB without leaving anything out) |
| On disk, the catalogue unpacked | 11 MB |
| **On disk in all** (`engine/coding`) | **373 MB** as the disk counts it; the files themselves add up to 325 MB |
| Shown to the person before set-up | "about 375 MB" |
| Set-up from Settings | 19.0 s |
| Start, until the server says it is ready | 3.8 s, three times in the real app; 6.1 s for the first start of a new install |
| Memory after start, the server and everything under it | 372 MB and 374 MB |
| Memory, highest during a real session on the local model | 429 MB |
| Stop, when asked | Under 1 s |

The download size was not counted on the wire. It is the sum of the sizes PyPI and npm publish for the exact
files the lock allows on this computer.

Sizes here are in MB of 1,000,000 bytes. The C0 spikes gave 573 MB and 385 MB for an environment that also
held the automation server, which is no longer part of the plan (ADR-0105), and they were read from `du -h`,
which counts in larger units. For the four packages alone, leaving the eight out takes 573 MB down to 362 MB.

## What is left out of the lock

`services/coding-engine/leave-out.txt` names eight packages. Five are the spike's (`google-api-python-client`,
`grpcio`, `cython`, `reportlab`, `posthog`). Three more go with them: `screeninfo`, `pyobjc-core` (which holds
`PyObjCTest`, 16 MB of its own tests) and `pyobjc-framework-cocoa`. All but `grpcio` are wanted only by
`browser-use`, the agent's own browser tool, which is switched off.

Shown to work without them, inside the sandbox:

- The server starts and says 1.62.0.
- All 30 hostile tests pass.
- **A real session** on the local Qwen 27B through Ollama: asked for a small module with five unit tests, it
  wrote both files and ran the tests, was told to copy a file to the Desktop and was refused by the
  sandbox. Finished in 46 s, five tool steps. The five tests pass when run again by hand, and nothing
  appeared on the Desktop.

`browser-use` itself is still installed (3 MB). Whether the browser tool is wanted is decided with the
Browser tab (C4), as ADR-0102 says.

## The sandbox profile

The profile is `services/coding-engine/engine.sb.template`. It is stricter than the spikes' profile in two ways.

**1. Reading (ADR-0102, decision 3).** The spikes closed five folders. This profile closes `/Users`,
`/Volumes`, the per-user temp folders (`/private/var/folders`), `/tmp` and the app's own data folder, and
opens again only the engine's packages, the Python they were installed with, the server's own state and the
workspaces. Measured with the data folder where the real app keeps it
(`~/Library/Application Support/...`, a path with a space in it): the server starts, a real session runs,
git commits, Python makes temp files in its own state, and this computer's own address is reachable.

Three things had to be done for it to work:

| Found | Done |
|---|---|
| A program cannot reach an opened folder when the folders above it are closed | The profile also allows the names (not the contents) of every folder on the way to an opened one |
| A link inside a closed folder cannot be followed. The server did not start from a data folder reached through a link | The supervisor starts the server by its real path and gives it real paths only |
| `git` in `/usr/bin` is a stand-in that looks the real program up through a cache in the per-user temp folder. Closed, every `git` call took 0.5 s and printed four errors | Apple's developer tools folder is put on the server's `PATH`: under 0.1 s for several calls, no errors. Opening the cache for writing was rejected: a command could then point the person's own `git` at another program |

**2. Other programs. The spikes' profile had a hole.** With only the three rules of the spikes (writes,
reads, network), a command inside the sandbox could:

- run `open -a Calculator`, and the app started. `open` hands the work to a system service outside the
  sandbox, so `open some.command` would run a script with the person's full rights;
- send a signal to any process of the person. A test process outside the sandbox was ended that way.

The profile now refuses a signal to a process outside the sandbox, opening an app or a file, a message to
another app, and handing a job to the system. All four are in the hostile tests. Signals between the
server and the programs it starts still work.

## The hostile tests

`services/api/tests/integration/test_coding_sandbox.py`, run with `make test-coding`. Every command goes
through the server's own command endpoint, which is how the agent's commands run. No model is used.

| Must be refused | Result |
|---|---|
| A write to the home folder, the Desktop, `/tmp`, this repository | Refused, "Operation not permitted" |
| A change to, and a delete of, a file of this repository | Refused; the file unchanged |
| A write through Python | Refused, `PermissionError` |
| A write through a child of a child, and through a child that left its parent's group and session | Refused |
| Copying out with `cp`, `tee`, `mv` and a link | Refused |
| A write into the engine's own packages and its own install record | Refused |
| A listing of `~/.ssh`, `~/Library/Application Support`, the home folder, the Desktop, the keychains, `/tmp`, other disks | Refused |
| Reading an ordinary file elsewhere in the home folder (the spikes' profile allowed this) | Refused |
| Reading the app's own data folder, a keys file in it, the launcher's runtime file | Refused |
| The internet: by name, by number, with curl and with Python | Refused |
| A signal to a process outside | Refused; the process lived |
| Opening an app, opening a script, a message to Finder | Refused |
| `ps`, `sudo` | Do not start (a rule of macOS for any sandbox, not ours); `pgrep` works |

| Must work | Result |
|---|---|
| The pinned version answers inside the sandbox, with its home and temp folder under its own state | Works |
| A write inside the workspace | Works |
| A folder the person chose as a workspace, read and written | Works |
| `git init`, `add`, `commit` in the workspace, with no complaint | Works |
| Python, with its temp files in the server's own state | Works |
| An address on this computer (the model gateway will be one) | Works |
| The pinned catalogue is what the server offers, and nothing was copied into its home | Works: 73 skills |

One more test of the profile runs in `make test` with no server at all: the real `sandbox-exec`, the profile
written by a real start, and a shell.

## Quit

Each case began with the coding engine running in the real app.

| How the app ended | The server | `/tmp` |
|---|---|---|
| Quit (a termination request to the shell, the same path as the menu's Quit) | Gone; the shell, the engine and the server all ended within 4 s | Empty |
| The shell killed outright (`kill -9`) | Gone within about 1 s | Empty |
| The engine killed outright (`kill -9`), so nothing called stop | Gone within about 1 s, by the guard | Empty |

**Why a guard.** The server runs in a process group of its own (ADR-0102, decision 2), so a signal to the
engine's group does not reach it. If the engine dies without stopping it, it would live on with 370 MB. The
server therefore holds one end of a pipe from the engine. When the pipe closes it removes its terminal
folder, asks its own group to stop, and ends it 5 s later.

**Stopping the group is not enough.** The Agent Server starts every command in a session of its own. A stop
that signals only the server's group leaves a running command behind. Stop therefore lists every process
under the server first and ends those too.

## A second copy

The shell uses a single-instance rule that was there before this stage: a second launch of Wasify AI brings
the first window forward and starts no engine. Tried here: the second copy, on its own data folder, exited
within seconds and started nothing.

What the plan's rule is about (the test app's fixed ports, where a second copy could not start) was
measured with two engines: the real app's, and a second engine on another data folder started the way the
shell starts one. Both coding engines ran at once, on ports 59926 and 60118, each with its own key and its
own terminal folder. Stopping one left the other answering. Nothing in this stage uses a fixed port.

## What was found on the way

1. **One folder must be in `/tmp` while the server runs.** The server keeps its terminal's sockets in
   `$TMUX_TMPDIR`, and a socket's path must fit in 104 bytes on macOS. That leaves about 51 bytes for the
   folder. `~/Library/Application Support/ai.wasifyai.desktop` is 67 already, and the per-user temp folder is
   too long as well. Left alone, the server makes `/tmp/openhands-agent-server-<pid>` itself and leaves it
   behind when it is killed (the spikes found two). The supervisor makes `/tmp/wasify-coding-<8 letters>`
   instead, readable by the person only, names it in the profile, and removes it at stop, at a forced
   quit, and at the next start if a run was cut off. Its temp folder proper (`TMPDIR`) is inside its state.
2. **`EXTENSIONS_PATH` does not stop every fetch.** With it set, the 73 skills come from the pinned copy. But
   `GET /api/skills/marketplace` still tries `git clone https://github.com/OpenHands/extensions`
   (`skills_service.py`, `_fetch_catalog_entries`). Inside the sandbox it fails and the list comes back
   empty. Our Extensions module must not use that endpoint, and the sandbox is what holds the rule
   "nothing is fetched at run time".
3. **One package has no prebuilt file.** `func-timeout`, which `openhands-tools` imports, is published as
   source only. uv builds it while installing and fetches `setuptools` for that: the newest one, with no
   hash, even under `--require-hashes`. `services/coding-engine/build-constraints.txt` pins `setuptools`
   with its hash, and a wrong hash was shown to stop the install.
4. **The server gives its session key to the commands it runs** (`export_session_api_key`). A command can
   therefore call the server's own API. It is all inside the sandbox, and the key opens nothing of Wasify's.
   From C1b on, nothing that matters may be decided by the Agent Server alone, which ADR-0101 already says.
5. **The server's own state folder is not on its import path.** It is started with Python's isolated mode,
   so a file an agent writes into the server's working folder is not imported at the next start.
6. **`uv python install` also tries to put `python3.12` into `~/.local/bin`.** It did not replace the file
   that is there. This is how every optional part with its own Python is installed today, not something
   new; it is noted because it writes outside the app's data folder.
7. **A stop does not reach a program that left both its group and its parent.** Such a program stays
   inside the sandbox for as long as it lives. No test here makes one. The hostile tests of C3, when
   commands arrive for real, should.

## Tests

| | Result |
|---|---|
| `services/api/tests/test_coding_server.py` (the supervisor on the fake server) | 21 passed |
| `services/api/tests/test_components_coding.py` (the part on the fake server) | 15 passed |
| `make test-coding` (the real server in its sandbox) | 30 passed |
| `cargo test provision` (the shell checks the coding engine's files in the bundle) | 10 passed |
| `make test` | Passed: see the last lines of this section |
| `make lint` | Passed |

The fake Agent Server (`services/api/tests/fake_agent_server.py`) answers `/alive`, `/health`, `/ready` and
`/server_info`. It is started with the same arguments as the real one and runs the supervisor's guard as
it is, so the forced-quit test in `make test` is a real one. It replays no recorded event streams yet:
nothing reads events before C1b.

`make test`: 3357 Python tests passed and 451 skipped (the skipped ones need services or are opt-in, the 30 hostile tests among them), 220 web tests and 744 screen tests passed. `make lint`: ruff, the format check, pyright (0 errors), Biome and the TypeScript check all passed. After the runs nothing was left in `/tmp`.

## Not measured

- **A clean macOS account.** Every run was on the owner's account. The data folders were new, but uv, Apple's
  developer tools and Homebrew were already on the computer. On a Mac without the developer tools, `git` is
  not there at all; what the app says then is not built.
- **The packaged app.** The runs used the development build of the shell with the checkout's engine. The
  engine bundle carries the coding engine's files and the shell checks them (a test shows it), but
  `scripts/build-engine-bundle.sh` was not run: it fetches other things the owner was not asked about.
- **Python from the internet.** Python 3.12.15 was copied from the app's own install, so the set-up's
  "Installing Python" step found it and fetched nothing. On a computer where the app has run, it is there.
- **The download on the wire.** See "Numbers".
- **The rest of stage X1:** our own short list as the only marketplace loaded, and the gate "a session starts
  and only the short list's skills are offered". There is no session and no short list yet (the owner's open
  question 3 in the plan).
- **The window of the real shell.** Set up, Repair and Remove were clicked in the real window's code running
  in a browser against a real engine, as `ui-audit.sh` does for every screen. In the Tauri window itself the
  same list was not clicked; start, stop and quit were measured with the real shell.
- **Windows, Linux, Intel Macs:** the part says it is not available yet. That sentence is tested; nothing else.
- **A long-running server.** Memory was read after start and during one 46 s session, not over hours.
- **A session on Claude Sonnet 5.5.** No paid run was allowed. The one real session was on the local model.

## For the next stages

- **C1b:** the product starts the server with `ensure_running(workspaces)`. A change of workspaces restarts
  the server, because a profile cannot change while its process runs. One server for several sessions with
  different workspaces therefore means a restart, or one profile that names all of them: to be decided there.
- **C1b:** the routes `/desktop/coding-engine/start` and `/stop` were added so this gate could be measured.
  Once the product starts the server, the owner may want them removed.
- **C1b:** the launcher's runtime file (`engine.json`) is closed to the sandbox now. Spike 6 read it from
  inside. The coding product's own connection must be given to the server another way.
- **C3:** the terminal tool uses tmux when it is installed (it is not on this Mac). Its server leaves the
  process group, so stop will have to end it through its socket in the terminal folder.
