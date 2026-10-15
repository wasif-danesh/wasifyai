# Desktop Phase 1: evidence (engine profile and shell)

Date: 2026-10-15. Machine: MacBook Pro M5 Pro, 64 GB, macOS. Scope done: ADR-0056 steps 1 to 5
(engine desktop profile, Tauri shell with installer and updater skeleton, shared image screen in `packages/ui` +
`packages/client`, end to end on the Mac). Step 6 (three-OS CI) is done: the `desktop` workflow is green on all
three systems (12 jobs, commit dcd3b29; see "CI on three systems"). The measured numbers
below are from the Mac and are a **debug build against the repository's `.venv`**, not a packaged app.

## Measured

| Measure | Result | How |
|---|---|---|
| Engine process, idle, resident memory | **170 to 171 MB** (3 runs) | `ps -o rss` at ready and 5 s later; all registered products imported |
| Engine start to the ready line | **1.7 to 1.8 s** (3 runs) | launcher started with a fresh data folder, warm bytecode cache |
| Shell launch to engine ready (`/health` and `/me` answered) | **2.1 to 2.4 s** (3 runs) | polled the engine log; debug shell |
| Shell process resident memory | **115 MB** | debug build with the WKWebView window open; the WebKit helper processes are not attributed |
| Budget (ADR-0056 suggestion) | engine under 300 MB: met with room | |
| Single instance | a second launch exits within 4 s and leaves one engine | run by hand |
| Crash cleanup | `kill -9` of the shell: the engine is gone within 4 s (stdin EOF) | run by hand |
| Orderly quit | SIGTERM: engine log shows "Application shutdown complete" and "engine stopped"; all processes gone in 1 s | run by hand |
| Token handoff | the shell's HS256 token (Rust) is accepted by the engine (`/me` 200) at every launch | the shell checks it before it reports ready |

The 170 MB includes importing every registered product (music, video, speech, ...), asyncpg and redis; the
desktop profile serves only `wasifyai-image`, so loading only that product's package is the first lever if the
number needs to come down.

## End to end (step 5)

`WASIFYAI_SMOKE=1 ./target/debug/wasifyai-desktop`, run on the Mac:

| Step | Result |
|---|---|
| Launch, engine start, window up | engine ready line, `/health` and `/me` answered |
| Create form typed into and submitted in the real webview | `POST /products/wasifyai-image/runs` 200 |
| Job events over SSE (check, queued, running, completed, done) | picture reached the screen |
| Picture loaded from the engine's signed link under the window's CSP | 256x256 placeholder from `http://127.0.0.1:<port>/files/...` |
| Whole run, launch to exit | **4.3 s**, exit code 0 |
| Processes left after exit | none (engine stopped, "engine stopped" in the log) |
| Second launch while the first runs | exits within 4 s, one shell and one engine remain |
| SIGTERM while running | engine and shell gone within 1 s |

## Provisioning (step 3), run for real

`WASIFYAI_PROVISION=1 WASIFYAI_DATA_DIR=<empty folder> WASIFYAI_SMOKE=1 ./target/debug/wasifyai-desktop`, on the
Mac, over the network (uv 17 MB from GitHub; Python and 77 packages through uv):

| Run | Time | Result |
|---|---|---|
| From nothing: download uv, install Python 3.12.15, venv, packages, verify, then the whole self-test | **25.6 s** | exit 0, image made in the window |
| Second launch, already installed | **3.4 s** | exit 0, nothing downloaded |
| Repair after deleting a file from the engine package (`WASIFYAI_REPAIR=1`) | **17.9 s** | exit 0; the file is back |

Disk afterwards: venv 195 MB, Python 66 MB, uv 34 MB: **294 MB**. Before the cache is removed at the end of
install the folder held 218 MB more, so the free-space requirement is set at 1 GiB.

## First CI run (step 6), 2026-10-15

The first push of the desktop work ran `ci` and `desktop` on GitHub's hosted runners. Facts from those runs,
and what each one led to:

| Job | Result | Finding |
|---|---|---|
| `ci` / python (Ubuntu, with Postgres and Redis) | pass | The **Redis contract tests passed** (`test_event_log_redis`, `test_run_store_redis`): the SQLite adapters and the Redis ones follow the same rules. All desktop-profile tests passed here too. |
| `desktop` / shell (macOS, Windows, Linux) | **pass on all three** | `cargo test` and `cargo build --release --locked` pass, so `windows_job.rs` compiles on Windows and the shell builds with the webview libraries on Linux. |
| `desktop` / engine (Ubuntu) | pass on the first push; **hung on the second** | A shutdown race (below). |
| `desktop` / engine (Windows) | **fail** | `import resource`: the SDK imported a Unix-only module at load, so the engine could not even be imported on Windows. Fixed: imported inside the Linux-only child setup. |
| `desktop` / engine (macOS) | **fail, both pushes** | `uv sync` chose Python 3.15 on the runner, and `ormsgpack` has no wheel for it and does not build. Fixed: `.python-version` is `3.12` (the containers and the installer's pin), and the desktop workflow sets `UV_PYTHON`. |
| `ci` / setup (macOS) | failed on the first push with the same error, **passed on the second** | The same cause; which interpreter `uv` picks depends on the runner image, so it is not deterministic. `.python-version` makes it so. |
| `desktop` / smoke, install | skipped | They were chained behind the engine job. Now independent, so one failure does not hide the rest. |

**The hang** was a bug in the engine's shutdown, found by repeating the test locally (1 hang in 10 runs, then
a thread dump): the lifespan cancelled its background tasks (index reconciler, upload sweeper) without
waiting for them and then closed the database. A task cancelled in the middle of a query rolls back through
its connection; the connection was already closed and never answered, so the task, and the event loop's own
shutdown, waited forever. The lifespan now waits for the cancelled tasks before it closes anything: 40
consecutive clean runs afterwards. This affects the web profile's shutdown in the same way.

## The packaged app (step 7), measured on the Mac

`tauri build --config src-tauri/tauri.bundle.conf.json --bundles app` produced `wasifyai.app` (16.5 MiB; the
engine bundle is in its Resources, 680 KB). It was run from `Contents/MacOS` with a fresh app data folder,
`WASIFYAI_REPO` pointing nowhere (so it finds no checkout, no `.venv`) and the self-test on. MacBook Pro M5 Pro,
64 GB, macOS, release build, network on, unsigned. Times are the shell's own clock from its start.

| Measure | Result |
|---|---|
| **First launch** (installs uv, Python 3.12.15 and 77 packages, then starts the engine) | engine answering after **24.8 s**; app start to picture shown and quit **26.4 s** |
| **Relaunch** (already installed), two runs | engine answering after **2.1 s**; start to picture shown and quit **3.3 s** |
| **Engine process, idle** (resident memory, 10 s after launch, nothing asked) | **171 MB**; 178 to 179 MB at the instant it answers; 182 MB after one image |
| **Shell process** | **111 to 121 MB** |
| **WebKit helper processes** (WebContent 52, GPU 32, Networking 12 MB) | **96 MB** |
| **Whole app idle** (engine + shell + WebKit helpers) | **about 380 MB** |
| **On disk** | app 16.5 MiB + engine folder **294 MB** (venv 195, Python 66, uv 34) |
| Quit | engine process gone, none left |
| ADR-0056 budget (engine idle under 300 MB) | **met** (171 MB) |

Method: no measuring tool was added to the repository; the numbers come from the shell itself
(`SMOKE_METRICS`: `ready_ms`, resident memory of the engine at ready and after the run, of the shell) and `ps`
for the WebKit helpers, which are other processes the shell does not own (those were the new
`com.apple.WebKit.*` processes that appeared while the app ran). "Cold" means the first launch after the app
was built and the folder created; the machine was not rebooted, so the engine's Python files and Python itself
were not cold in the operating system's file cache on the relaunches.

### The same packaged app on the three CI systems

The `package` job builds the app for each system, then runs the packaged result on a machine with no
checkout: macOS runs `wasifyai.app`; Linux unpacks the `.deb` and runs `usr/bin/wasifyai-desktop` under xvfb;
Windows installs the NSIS setup silently and runs the installed `wasifyai-desktop.exe`. Each runs twice: the
first launch installs the engine, the second finds it installed. Two CI runs; every one of the twelve
launches **passed** the self-test (a picture was made in the window). Numbers below are from run 38705240476
(commit 2d3fba7), which has the corrected measurement; the earlier run 38703782545 is quoted where it differs.

"Shell" is the time from the shell's start to its setup hook (the window is being created); "engine" is from
the hook to the engine answering `/health` and `/me`; their sum is the time to ready.

| | macOS (hosted, arm64) | Ubuntu (hosted, x64) | Windows (hosted, x64) |
|---|---|---|---|
| Packaged size | `.app` 18.1 MiB | `.deb` 7.8 MiB | NSIS setup 4.3 MiB |
| **First launch**, to ready (the engine installs) | 15.6 s = 1.7 shell + 13.9 engine (29.7 s in the earlier run) | 48.3 s = **35.0 shell** + 13.3 engine | 20.7 s = 2.9 shell + 17.8 engine |
| **Relaunch**, to ready | **1.9 s** = 0.6 + 1.3 | 31.6 s = **30.1 shell** + **1.5 engine** | **2.9 s** = 0.5 + 2.4 |
| **Engine memory** at ready, first and second launch | 167, 155 MB | 168, 160 MB | 155, 149 MB |
| Engine memory after one image | 171, 161 MB | 176, 168 MB | 160, 154 MB |
| Shell process memory | 98 to 100 MB | 187 to 200 MB | 33 to 42 MB |

What this says:

- **Engine memory is 149 to 168 MB at ready on all three systems** (resident set; Windows: working set), under
  the 300 MB budget, and within 20 MB of the M5 Pro's 171 MB. Windows is valid now: the first CI run had measured
  Windows' venv launcher (4 MB) instead of the interpreter.
- **The engine starts in 1.3 to 2.4 s when installed, on every system, including Linux.** First-launch times
  vary with the network (macOS 15.6 s in one run, 29.7 s in the other).
- **Linux's slow relaunch is not the engine.** 30 to 35 s pass before the shell's own setup hook runs, i.e. in
  the shell's startup and window creation on that runner. `NO_AT_BRIDGE=1` (a hypothesis about a missing
  accessibility bus) did **not** remove it. A likelier cause is the single-instance plugin waiting for a D-Bus
  session bus that a bare runner does not have; this is a guess, not a finding. An experiment (the same run
  under `dbus-run-session`, which cannot fail the job) is in the workflow; until it has run, the cause is
  open, and nobody has timed the app on a real Linux desktop.
- Shell memory excludes the web view's own processes on every system (the Mac's 96 MB of WebKit helpers were
  counted separately above; WebKitGTK and WebView2 were not measured). Linux's shell is larger because GTK and
  WebKitGTK load into it.

Hosted runners are shared virtual machines: use them to compare systems with the Mac numbers above, not as a
promise to users.

## CI on three systems (step 6): the second run, commit 2db73f6

Every job of the `desktop` workflow on GitHub's hosted runners (macOS arm64, Windows x64, Ubuntu x64):

| Job | macOS | Windows | Linux |
|---|---|---|---|
| shell: `cargo test --locked` and `cargo build --release --locked` (webview libraries on Linux) | pass | pass | pass |
| engine: desktop-profile tests (SQLite adapters, local files, stores, the real launcher) | pass | **35 of 36** on this commit: the launcher test compared the engine's pid with the pid of the process the test started, which a venv's `python.exe` launcher on Windows makes different (a test assumption; **fixed in dcd3b29, all pass**) | pass |
| smoke: the window, driven like a person, against the checkout's `.venv` | **PASS** | **PASS** | **PASS** (xvfb, software rendering) |
| install: build the engine bundle, install uv, Python and the 77 packages into an empty folder, then the same self-test | **PASS** (159 s for the step, which also compiles the shell) | **PASS** (240 s) | **PASS** (176 s) |

Also green in the same run: `ci` / python (760 tests with real Postgres and Redis, including the Redis contract
tests), web, setup, helm-kind. The step times above include compiling the shell, so they are not install times;
the installer's own log is the "Installer log" step of each `install` job.

What CI did **not** tell us: memory and cold start on Windows and Linux (not measured), what the window looks
like (the self-test checks the DOM), and anything about a packaged, signed app.

## Tests that exist now

| Where | What | Result here |
|---|---|---|
| `packages/platform-sdk/tests/test_sqlite_adapters.py` | event log and run store contracts on memory, SQLite and Redis; queue contract on SQLite | memory and SQLite pass; Redis skipped (no Redis on this Mac) |
| `services/api/tests/test_sqlite_stores.py` | user store, settings, index store contracts | pass |
| `products/wasifyai-image/tests/test_image_sqlite.py` | image records, index source | pass |
| `packages/platform-sdk/tests/test_storage.py` | local files and signed links | pass |
| `services/api/tests/test_desktop_profile.py` | an image made end to end through the queue and worker, file links, search, replay, restart, a real launcher subprocess | pass |
| `apps/desktop/src-tauri` `cargo test` | ready line, token claims, loopback client; manifest pins; download and checksum (loopback server); archive extraction; free space; the installer's steps, repair, disk and bundle checks against a fake uv; updater status | 31 pass (Windows-only job tests did not run; the fake-uv tests are Unix-only) |
| `packages/client` | transport and run client, SSE parser, image flow reducer | 16 pass |
| `packages/ui` | image form, flow hook, create screen with the app's own actions, picture helpers | 15 pass |
| `apps/web` | the whole suite, with the image screen now mounted from `packages/ui`; `next build` | 279 + 1 pass; build passes |
| `apps/desktop` | the engine transport, the install progress fraction | 9 pass |
| whole Python suite | | 760 passed, 38 skipped (integration tests that need Postgres, Redis or models) |

## Not verified

- **Why Linux takes 30 s before the shell's setup hook on a bare runner** (the engine is fast there), and how
  long a real Linux desktop takes; **WebKitGTK and WebView2 helper-process memory**.
- **What the window looks like.** The self-test drives and checks the DOM, not pixels; no screenshot was
  taken, and the web app's own pages were not compared before and after the move (the built CSS does contain
  the shared package's classes, and the web test suite and `next build` pass).
- **A signed, notarised app**, a `.dmg`, an AppImage: not built. The `.app` above is unsigned (Gatekeeper will
  ask on another Mac); the engine bundle is inside it.
- **The Intel Mac build of uv and the Linux arm64 build**: the manifest has their checksums; no runner of
  those kinds was used. The Unix-only installer tests (fake uv) do not run on Windows; the real install does
  (the `install` job).
- **The updater** against a real feed and a signed archive.
- **Offline install.** Step 2 and step 5 need the network.
- **Image generation on a real engine.** The stub image engine makes placeholder files.

## Phase 2, stage A1: the image engine component (2026-10-15)

`docs/phase2-stage-a-plan.md`, step A1, run for real on the M5 Pro (macOS, network on) through the window's
self-test (`WASIFYAI_SMOKE=1 WASIFYAI_SMOKE_COMPONENT=comfyui`: the window presses "Set up image generation" and
waits until it says it is installed). No model was downloaded.

| Measure | Result |
|---|---|
| Install from nothing (uv, Python, ComfyUI 0.40.0 source, 84 hashed packages including torch 2.11.0) | **311 s** |
| On disk afterwards | **1.4 GB** (ComfyUI's environment about 1.35 GB, source 49 MB) plus the engine's 102 MB of uv and Python |
| Accelerator torch found | `mps` (the Apple GPU) |
| ComfyUI server started by hand from the installed environment | up after **6.8 s**; reports ComfyUI 0.40.0, torch 2.11.0, device `mps` |
| ComfyUI server idle, no model loaded | **558 MB** resident |
| Requirement for the free-disk check | 4 GiB (peak is the environment plus uv's download cache, which is removed at the end) |

Found on the way (for A2): ComfyUI refuses to start if its base directory has no `custom_nodes` folder, so the
engine must create `models`, `input`, `output`, `temp`, `user` and `custom_nodes` before it starts the process
(the container recipe does the same with `mkdir -p`).

The GitHub archive of the tag was downloaded twice and had the same SHA-256 both times, which the pin relies on;
GitHub does not promise archives are byte-stable for ever, so a changed archive fails the install with a
checksum message and the pin has to be refreshed.

## Phase 2, stage A2: real images through the engine (2026-10-15)

ComfyUI started and supervised by the engine, the model kept loaded between jobs, a slot manager unloading it
when idle. Mac M5 Pro, 64 GB, ComfyUI 0.40.0 and torch 2.11.0 from the A1 install, FLUX.2 klein 4B bf16 read
read-only from `~/ComfyUI-Shared/models` (no model was copied or downloaded), 1024x1024, 4 steps.

| Measure | Result |
|---|---|
| Real image made by the window's self-test (`WASIFYAI_SMOKE=1 WASIFYAI_IMAGE_ENGINE=comfyui`) | **passed**, 1024x1024, a recognisable red teapot on a wooden table; app start to quit 38.8 s including starting ComfyUI and loading the model |
| First job in an engine (starts ComfyUI, loads the models) | **29.8 s** |
| Next jobs, a new prompt each time (model kept loaded) | **13.3 to 13.6 s** end to end; ComfyUI itself reports 13.0 to 13.1 s, so the app's own cost is about 0.3 s |
| Same prompt, new seed | 9.3 to 10.2 s |
| ComfyUI resident memory, model loaded | about **7.9 to 9.2 GB** by `ps` (the process peak seen in Phase 0 was 17.6 GB) |
| After the idle unload (25 s in this test, 10 min by default) | **764 MB**: the slot manager released the models; the process stays |
| First job after an idle unload | 17.7 s (models read back from disk) |
| ComfyUI process after the engine exits | none left |

Correction to Phase 0: its **9 s warm** figure was a run with the same prompt and a new seed, where ComfyUI
reuses the text encoding. With a **new prompt every time, warm is about 13 s**: the Qwen text encoder runs on the
**CPU** (ComfyUI's log: "CLIP/text encoder model load device: cpu") and takes about 4 s. `--gpu-only` and
`--highvram` do not change that and the time is the same on torch 2.9.1. Moving the encoder to the GPU, or using
the 3.85 GB fp4 encoder, is the obvious next speed-up and is not done.

Findings: ComfyUI stops at start-up if its base directory has no `custom_nodes` folder (the sidecar creates the
folders); an identical graph is answered from ComfyUI's cache in 0 s, which a benchmark has to avoid.
