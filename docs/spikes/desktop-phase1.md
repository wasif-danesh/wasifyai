# Desktop Phase 1: evidence (engine profile and shell)

Date: 2026-10-15. Machine: MacBook Pro M5 Pro, 64 GB, macOS. Scope done: ADR-0056 steps 1, 2, 4 and 5
(engine desktop profile, Tauri shell, shared image screen in `packages/ui` + `packages/client`, end to end on the
Mac). Provisioning and the CI run are not done; see "Not verified" below. Everything is a **debug build against the repository's `.venv`**, not a
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

## Tests that exist now

| Where | What | Result here |
|---|---|---|
| `packages/platform-sdk/tests/test_sqlite_adapters.py` | event log and run store contracts on memory, SQLite and Redis; queue contract on SQLite | memory and SQLite pass; Redis skipped (no Redis on this Mac) |
| `services/api/tests/test_sqlite_stores.py` | user store, settings, index store contracts | pass |
| `products/wasifyai-image/tests/test_image_sqlite.py` | image records, index source | pass |
| `packages/platform-sdk/tests/test_storage.py` | local files and signed links | pass |
| `services/api/tests/test_desktop_profile.py` | an image made end to end through the queue and worker, file links, search, replay, restart, a real launcher subprocess | pass |
| `apps/desktop/src-tauri` `cargo test` | ready-line parsing, token claims, loopback client | 8 pass (Windows-only job tests did not run) |
| `packages/client` | transport and run client, SSE parser, image flow reducer | 16 pass |
| `packages/ui` | image form, flow hook, create screen with the app's own actions, picture helpers | 15 pass |
| `apps/web` | the whole suite, with the image screen now mounted from `packages/ui`; `next build` | 279 + 1 pass; build passes |
| `apps/desktop` | the engine transport | 6 pass |
| whole Python suite | | 760 passed, 38 skipped (integration tests that need Postgres, Redis or models) |

## Not verified

- **Windows and Linux.** Nothing was run. `windows_job.rs` is Windows-only code that was never compiled here.
  `.github/workflows/desktop.yml` builds and tests on all three and has not run.
- **Redis contract tests** (event log and run store) skip locally; the existing `ci.yml` has a Redis service and
  will run them. If they fail there, the SQLite adapters are the reference only by test, not by proof.
- **What the window looks like.** The self-test drives and checks the DOM, not pixels; no screenshot was
  taken, and the web app's own pages were not compared before and after the move (the built CSS does contain
  the shared package's classes, and the web test suite and `next build` pass).
- **A packaged app** (`.app`, `.dmg`, signing): not built.
- **Image generation on a real engine.** The stub image engine makes placeholder files.
