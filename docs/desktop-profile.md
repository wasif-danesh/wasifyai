# The desktop profile

Status: **Proposed**, with ADR-0056 (the desktop app and the web product share one engine). Built in Phase 1:
the engine runs in a desktop profile, a Tauri shell starts it, and one window shows its state. Commands and
numbers below were run on a MacBook Pro M5 Pro (macOS). Windows and Linux are exercised by CI
(`.github/workflows/desktop.yml`): the shell builds, the engine tests pass, and a clean install followed by the
window's self-test passes on both; nobody has run them by hand, and no numbers were taken there.

## What a profile is

The same engine (`services/api`, the SDK, the products) runs under a **deployment profile**, chosen by
`DEPLOYMENT_PROFILE`. Product code never asks which one it runs in: the profile is the set of adapters behind
interfaces that already existed.

| Interface | `web` profile | `desktop` profile |
|---|---|---|
| Records (users, uploads, images, usage, settings) | Postgres | SQLite file `wasifyai.db` |
| Run event log (`seq`, `Last-Event-ID`) | Redis Streams | `SqliteEventLog` (same semantics, 7 days kept) |
| Run store | Redis hashes | `SqliteRunStore` |
| Job queue and results | Redis streams + a separate media worker | `SqliteJobQueue` + a worker in the engine's process |
| Graph checkpoints | LangGraph Postgres saver | LangGraph SQLite saver (`checkpoints.db`) |
| Files | S3 API, presigned URLs | a folder, links signed by the engine (`/files/...`) |
| Search index (ADR-0041) | pgvector | rows with JSON vectors, compared in Python |
| Embedder when there is no gateway | LiteLLM `creation-embedder` | `local-hash/v1`, a word-hash embedder, replaced when a gateway exists |
| Sign-in | the web app's BFF token (`google:`, `github:`, ...) | the shell's token, provider `desktop` |
| Products served | all registered | `PRODUCTS_ENABLED` (default `wasifyai-image`) |
| Metrics port | 9464 | none |

Store adapters that depend on the database are chosen by the **engine's dialect**, not by the profile name:
`image_store(engine)`, `upload_store(engine)`, `image_index_source(engine)`. The Postgres classes are unchanged.

## Where the code is

| Path | What |
|---|---|
| `packages/platform-sdk/src/wasifyai_platform_sdk/sqlite/` | engine factory, event log, run store, job queue, uploads, usage |
| `packages/platform-sdk/.../storage.py` (`LocalFileStorage`) | folder storage and signed links |
| `services/api/src/wasifyai_api/sqlite_stores.py` | users, safeguards setting, search index |
| `services/api/src/wasifyai_api/desktop.py` | the backends, `/files`, and the entry point `python -m wasifyai_api.desktop` |
| `services/api/src/wasifyai_api/local_embedder.py` | the model-free embedder |
| `services/media-worker/src/wasifyai_media_worker/local.py` | the worker loop over the SQLite queue |
| `apps/desktop/` | the Tauri 2 shell and the window (see its README) |

## How the shell and the engine meet

1. The shell makes a random secret for this launch and starts
   `python -m wasifyai_api.desktop` with `DEPLOYMENT_PROFILE=desktop`, `DESKTOP_DATA_DIR`, `API_AUTH_SECRET`
   (the secret), `AUTH_MODE=jwt`, `PRODUCTS_DIR`, `WASIFYAI_PORT=0` and `WASIFYAI_EXIT_ON_STDIN_EOF=1`.
2. The engine binds `127.0.0.1` on a free port and prints one JSON line:
   `{"event": "wasifyai.engine.ready", "port": N, "pid": P}`.
3. The shell calls `/health`, then `/me` with a token it signed itself (HS256, issuer `wasifyai-web`, audience
   `wasifyai-api`, subject `desktop:local`, 15 minutes). A 200 means both sides agree on the secret.
4. The window asks the shell (`engine_session`) for `{base_url, token, expires_at}` and calls the engine with it.
   The engine allows the window's origins by CORS (`DESKTOP_ALLOWED_ORIGINS`).
5. The shell keeps the engine's stdin open. If the shell dies, however it dies, the engine sees EOF and exits.
   On a normal quit (and on SIGTERM or Ctrl+C) the shell closes stdin, waits 8 seconds, then ends the process
   group (Windows: `taskkill /T /F`).

Nothing listens on the network: the engine's socket is bound to loopback and every route except `/health` and
the signed `/files` links needs the token.

## Files

`LocalFileStorage.url()` returns `{DESKTOP_PUBLIC_URL}/files/{key}?e={expiry}&s={hmac}`. The signature covers
the key and the expiry and is made with the launch secret, so a link opens one file for one hour, only against
this launch of the engine. An `<img>` can use it without a header.

## Environment (desktop)

| Variable | Meaning |
|---|---|
| `DEPLOYMENT_PROFILE` | `web` (default) or `desktop` |
| `DESKTOP_DATA_DIR` | database, checkpoints and files live here |
| `DESKTOP_PUBLIC_URL` | the engine's own URL, for signed links (the launcher sets it from the bound port) |
| `DESKTOP_ALLOWED_ORIGINS` | window origins allowed by CORS |
| `DESKTOP_IMAGE_ENGINE` | `stub` (placeholder files, no GPU) or `comfyui` (uses `COMFYUI_BASE_URL`) |
| `PRODUCTS_ENABLED` | comma-separated product ids; empty means all (desktop: `wasifyai-image`) |
| `WASIFYAI_PORT` | `0` (default): pick a free port |
| `WASIFYAI_EXIT_ON_STDIN_EOF` | `1`: exit when the shell goes away |

On the desktop profile `LITELLM_BASE_URL` defaults to empty and `METRICS_PORT` to 0 unless set.

## Developing

```
make setup                          # the Python environment (.venv)
pnpm --filter @wasifyai/desktop build   # the window's files (apps/desktop/dist)
cd apps/desktop/src-tauri && cargo run   # starts the shell, which starts the engine from .venv
```

`WASIFYAI_ENGINE_PYTHON` points the shell at another Python; `WASIFYAI_REPO` at another checkout. The engine's
output goes to `<app data>/logs/engine.log`. Tests: `uv run pytest services/api/tests/test_desktop_profile.py
packages/platform-sdk/tests/test_sqlite_adapters.py services/api/tests/test_sqlite_stores.py` and
`cargo test` in `apps/desktop/src-tauri`.

## Provisioning: how the engine gets onto a computer

An installed app carries no Python. On first run (and on "Repair") the shell builds the engine's environment
under `<app data>/engine` from two things: the **component manifest** compiled into the shell
(`apps/desktop/src-tauri/engine-manifest.json`: exact uv and Python versions, a SHA-256 and size for the uv
download of each platform, the free space needed) and the **engine bundle** shipped inside the app
(`scripts/build-engine-bundle.sh`, or `make engine-bundle`: our wheels, `requirements.lock` with a hash for
every third-party package, product config, and `bundle.json` with a SHA-256 for every file).

| Step | What happens | Shown in the window as |
|---|---|---|
| 1 check | every bundle file is checked against `bundle.json`; free disk space against the manifest (1 GiB) | "Checking this computer" |
| 2 uv | uv is downloaded from its pinned release, its SHA-256 is checked, it is unpacked; a later run checks the unpacked binary against the checksum recorded then | "Getting the installer", with bytes |
| 3 python | `uv python install 3.12.15` into `engine/python` (uv checks the Python build it downloads) | "Installing Python" |
| 4 environment | `uv venv` into `engine/venv` | "Creating the engine's environment" |
| 5 packages | `uv pip install --require-hashes --no-deps -r requirements.lock`, then our wheels | "Installing the engine" |
| 6 verify | imports the engine in the new environment, writes `engine/state.json` (uv, Python, bundle checksum), removes uv's download cache | "Checking the engine" |

The window shows `Step n of 6`, a bar, and the installer's latest output line. Output goes to
`<app data>/logs/provision.log`. A step that fails says which and why, and the window offers **Try again** and
**Repair the installation**. Repair removes the environment, checks uv again, installs everything, and if the
new environment still does not work throws Python and uv's cache away and does it once more. A damaged bundle or
too little disk space stops at step 1 and is not retried.

Which engine the shell uses, in order: `WASIFYAI_ENGINE_PYTHON` (a path); with `WASIFYAI_PROVISION=1` the managed
environment; a development checkout's `.venv`; the managed environment, installed from the bundle when missing
or out of date (what an installed app does).

Measured on this Mac (M5 Pro, macOS, from nothing, over the network): **25 s** for the whole install, **3.4 s**
launch when it is already installed, **18 s** for a repair of a damaged environment. On disk afterwards:
venv 195 MB, Python 66 MB, uv 34 MB (**294 MB**); the peak during install is about 520 MB because uv's
download cache holds a second copy of the packages until step 6 removes it.

| Variable | Meaning |
|---|---|
| `WASIFYAI_ENGINE_BUNDLE` | the engine bundle to install from (default: the app's resources, then the checkout's `apps/desktop/engine-bundle`) |
| `WASIFYAI_PROVISION` | `1`: use the managed environment even in a checkout that has a `.venv` |
| `WASIFYAI_REPAIR` | `1`: rebuild the environment at start |
| `WASIFYAI_DATA_DIR` | another app data folder (tests, trying the installer) |
| `WASIFYAI_ENGINE_PYTHON` | an explicit Python for the engine |

Packaging: `make engine-bundle`, then in `apps/desktop`
`pnpm exec tauri build --config src-tauri/tauri.bundle.conf.json --bundles app` (macOS; `deb` on Linux,
`nsis` on Windows). The extra config puts `engine-bundle/` in the app's resources; the plain build leaves it
out so a checkout without a bundle still builds. The result is unsigned. Measured numbers for the packaged app
are in `docs/spikes/desktop-phase1.md`.

Not done here: ComfyUI and the models are Phase 2 (ADR-0059). The window needs an internet connection for
steps 2 and 5; an offline install would need a wheelhouse in the bundle.

## Updates of the app

`updater.rs` is a skeleton that is off until a build has a signing key and a feed: compile with
`WASIFYAI_UPDATER_PUBKEY` and `WASIFYAI_UPDATER_ENDPOINT` set and pass `--config` with a filled-in
`tauri.updater.conf.example.json` (the plugin will not start without a key in the configuration, so it is not
registered otherwise). The window checks once when the engine is ready and shows "Install and restart" if
an update is waiting. Without those values the commands answer `not_configured` and nothing is contacted.
Not verified against a real feed or a signed archive.

## Shared screens (packages/ui and packages/client)

The image create screen is one piece of code that the web app and the desktop window both mount.

| Package | What | Knows about |
|---|---|---|
| `packages/client` (`@wasifyai/client`) | `createRunClient(transport)`: start, watch and resume runs (SSE), upload a picture, enhance a prompt; `HttpError`; the SSE parser; the image flow reducer | engine paths only (`/products/{id}/runs`); no React, no browser globals |
| `packages/ui` (`@wasifyai/ui`) | `CreateImage`, `ImageForm`, `useImageFlow`, `usePicture`, the primitives (button, notice, ...) and the design tokens (`tailwind.css`) | a `RunClient` passed in as a prop; no Next.js, no Tauri |

A **transport** is `fetch(path, init)` plus `onUnauthorized`. The web app's sends `/api` + path to its BFF with the
session cookie (`apps/web/lib/run-client.ts`). The window's (`apps/desktop/src/transport.ts`) sends path to
the loopback engine with the shell's token, keeps the token until a minute before it expires, and asks the
shell once more after a 401.

Both packages are TypeScript source with no build step: Next.js lists them in `transpilePackages`, Vite reads
them directly, and each app's Tailwind stylesheet imports `packages/ui/src/tailwind.css` and adds
`@source` for the package. A screen takes its client as a prop and keeps it the same object between renders.

Files that moved out of `apps/web` left a one-line re-export at the old path (`components/ui/button.tsx`,
`lib/styles.ts`, `components/Notice.tsx`, ...), so the other screens did not change. Switch a screen's imports
to `@wasifyai/ui` when it is migrated; delete the shim when nothing uses it.

## The self-test

`WASIFYAI_SMOKE=1 cargo run` (in `apps/desktop/src-tauri`) starts the shell as usual; once the engine is ready
the window types a prompt into the create form, presses the button, waits for the picture to load from the
engine's signed link, and the shell prints `SMOKE PASS ...` and exits 0 (`SMOKE FAIL ...` and 1 otherwise).
It drives the real DOM in the real webview, so CORS, the content security policy and the file link are all
exercised. It needs the engine environment (`.venv`).

## What is not done

- **Result actions on desktop.** The window shows the picture and "Make another"; download and a library
  screen come with the gallery (Phase 2). There is no router yet.
- **Other screens** (music, video, speech, ...) still live in `apps/web`; only the image screen is shared.
- **Schema changes.** Each adapter creates its tables on first use (`CREATE TABLE IF NOT EXISTS`). There is no
  migration runner, so changes must be additive until one is written.
- **Admin routes** are mounted but the admin store is Postgres-only; on desktop they answer 403 (the desktop
  user is not an admin).
- **Text capabilities** (enhance, moderation) need a gateway; with none configured they fail with a typed error.
  Safeguards are off by default, so image creation does not call them.
- **Redis contract tests** (`test_sqlite_adapters.py`) skip without a reachable Redis; CI has one. The Redis job
  queue is not behind the same interface as the SQLite one, so the queue contract runs on SQLite only.
- **Search** compares vectors in Python: fine for thousands of creations, not for a corpus. `sqlite-vec` is the
  next step if it is measured to be needed (ADR-0060).
