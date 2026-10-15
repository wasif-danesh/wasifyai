# Desktop Phase 1: evidence (engine profile and shell)

Date: 2026-10-15. Machine: MacBook Pro M5 Pro, 64 GB, macOS. Scope done: ADR-0056 steps 1 to 5
(engine desktop profile, Tauri shell with installer and updater skeleton, shared image screen in `packages/ui` +
`packages/client`, end to end on the Mac). The CI run (step 6) has not happened; see "Not verified" below. Everything is a **debug build against the repository's `.venv`**, not a
packaged app.

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

- **Windows and Linux.** Nothing was run. `windows_job.rs` is Windows-only code that was never compiled here.
  `.github/workflows/desktop.yml` builds and tests on all three and has not run.
- **Redis contract tests** (event log and run store) skip locally; the existing `ci.yml` has a Redis service and
  will run them. If they fail there, the SQLite adapters are the reference only by test, not by proof.
- **What the window looks like.** The self-test drives and checks the DOM, not pixels; no screenshot was
  taken, and the web app's own pages were not compared before and after the move (the built CSS does contain
  the shared package's classes, and the web test suite and `next build` pass).
- **A packaged app** (`.app`, `.dmg`, signing): not built. The engine bundle is found next to the checkout, not
  inside an app's resources, and `cargo tauri build` was not run.
- **The installer on Windows and Linux**, and the Intel Mac build of uv: the manifest has the checksums, nothing
  was run. The Unix-only installer tests do not run on Windows.
- **The updater** against a real feed and a signed archive.
- **Offline install.** Step 2 and step 5 need the network.
- **Image generation on a real engine.** The stub image engine makes placeholder files.
