# The desktop profile

Status: **Accepted** with ADR-0056 (the desktop app and the web product share one engine). Built in Phase 1:
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

## Optional components: the image engine

ComfyUI (ADR-0059) is not part of the first-run install. The window's "Set up image generation" action (the
Tauri command `component_install`, with `component_status` and the `component://status` event) installs it on
demand into `<app data>/engine/comfyui`: the pinned release source (`engine-manifest.json`, `comfyui`), its own
Python environment and the hashed lock the engine bundle carries for this platform
(`comfyui/requirements-<target>.lock`, made by `scripts/build-engine-bundle.sh`). Same steps, progress,
Repair and logs (`provision.log`) as the engine's installer. It is supported on Apple-silicon Macs only in this
version; elsewhere the window says so and the placeholder engine keeps working.

### Using it (stage A2)

`DESKTOP_IMAGE_ENGINE` chooses the runner: `stub` (placeholder pictures), `comfyui` (the real engine; a job fails
with "not set up yet" until the component is installed), `auto` (the real engine once installed, placeholders
until then; the shell's default), `external` (a ComfyUI someone else runs, at `COMFYUI_BASE_URL`; development).

The engine starts ComfyUI on the first real job (`ComfySidecar` in the media worker package): loopback only, a
random free port, its own working folder `<app data>/comfyui-data` (`models`, `input`, `output`, `temp`, `user`,
`custom_nodes`), model folders from a generated `extra_model_paths.yaml`, output in `logs/comfyui.log`. It
checks that the workflow's model files exist first and says so plainly if not. The model stays loaded
between jobs; the **slot manager** (`SlotManager`, SDK) unloads it through ComfyUI's `/free` after
`DESKTOP_IDLE_UNLOAD_S` seconds of no jobs (default 600) or when another owner needs the slot, and the process
exits with the engine.

| Variable | Meaning |
|---|---|
| `DESKTOP_MODELS_DIR` | where downloaded models go (default `<app data>/models`) |
| `DESKTOP_EXTRA_MODEL_DIRS` | read-only model roots with the usual folder layout (`diffusion_models/`, `text_encoders/`, `vae/`, ...), separated by `:` (`;` on Windows); the app never writes there |
| `DESKTOP_IDLE_UNLOAD_S` | idle time before the model is unloaded |
| `DESKTOP_COMFYUI_ARGS` | extra ComfyUI arguments, for tuning |

### Models (stage A3)

Each product lists the models it can use in `products/<id>/models.yaml` (id, licence, source, files with
folder, URL, size and SHA-256; URLs name a commit, not a branch). The engine reads them for the enabled products
(`wasifyai_api/desktop_models.py`) and serves, under `/desktop` (token-protected like every route):

| Route | What |
|---|---|
| `GET /desktop/models` | the catalogue with what is on this computer and where, the folders, memory, free disk, the current download |
| `POST /desktop/models/{id}/download` | start a download; the body must repeat the exact missing files and total size the window showed (`409` otherwise): **nothing downloads without that confirmation** |
| `GET /desktop/downloads/{id}`, `POST .../cancel` | progress; cancel (the partial file is kept) |
| `DELETE /desktop/models/{id}` | remove files from the app's own folder only |
| `PUT /desktop/models/folders` | the app's models folder and the read-only extra folders; remembered, and a running ComfyUI restarts on the next job |
| `GET /desktop/engine`, `POST /desktop/engine/unload` | image engine and model state; unload now |

Downloads: one at a time, resumable (`Range`), written as `<name>.part`, size and SHA-256 checked before the
rename, free disk checked first (needs the files plus 1 GB). Files in the extra folders count as present when
the size matches and are never written or deleted. The window's Models panel shows the list, a confirmation
with files, sizes, source, licence and free space before any download, progress and cancel, the loaded model
with Unload, and the folder settings. A memory warning is shown when the computer has less than the model's
`approx_ram_gb` (24 for klein 4B bf16).

## Updates of the app

The steps that remain before a public release (signing, notarisation, installers, offline install, the
updater's key and feed) are listed in ADR-0056, "Before the first public release".

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
| `packages/client` (`@wasifyai/client`) | `createRunClient(transport)`: start, watch and resume runs (SSE), upload a picture, enhance a prompt; `createImagesApi(transport)`: list, search, open, favourite, save a copy, delete; `HttpError`; the SSE parser; the image flow reducer | engine paths only (`/products/{id}/runs`, `/products/{id}/images`); no React, no browser globals |
| `packages/ui` (`@wasifyai/ui`) | `CreateImage`, `ImageForm`, **`ImageWorkspace`** (the two-panel Create/Edit screen), **`ImageLibrary`**, `useImageFlow`, `usePicture`, the primitives (button, notice, ...) and the design tokens (`tailwind.css`) | a `RunClient` and an `ImagesApi` passed in as props; no Next.js, no Tauri |

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

## The window: side menu and screens

`apps/desktop/src` owns the window's layout (the shared packages own the image form and flow).

| Piece | File | What |
|---|---|---|
| Router | `router.ts` | URL hash, six routes: `/`, `/images/create`, `/images/edit`, `/library`, `/models`, `/settings`. No library. |
| Shell | `Shell.tsx` | side menu + the screen; the menu collapses (remembered in `localStorage`) |
| Side menu | `Sidebar.tsx` | New chat (home), Models, Library, Images (expands: Create, Edit; Transform, Inpaint, Extend, Upscale, Reference marked "Soon"), Train ("Soon"), Projects, Recents, You + settings |
| Home | `pages/Home.tsx` | greeting and the "Ask anything" box (the assistant, ADR-0057, is not built: the box says so) |
| Create / Edit | `pages/Create.tsx` | wraps the shared `ImageWorkspace` with this window's model chip and setup notices |
| Library | `pages/Library.tsx` | wraps the shared `ImageLibrary`; "Make it again" sends the recipe to Create (`Shell.tsx` holds it until the route changes) |
| Models, Settings | `pages/Models.tsx`, `pages/Settings.tsx` | the model panel; the image engine card, updates, restart and repair |

On macOS the title bar is an overlay (`titleBarStyle: Overlay`, traffic lights at 18,22) and the menu leaves
room for them; elsewhere the native title bar stays. Dragging uses `data-tauri-drag-region` with the
`core:window:allow-start-dragging` capability. Items that are not built yet are shown disabled and labelled,
not hidden, so the menu keeps its final shape.

## Recipes, favourites and saving a copy (stage B)

Every image row keeps a **recipe** (`images.recipe`, versioned JSON: prompt, mode, size name, width, height,
seed) and a `favourite` flag. A run may carry a `seed` (0 to 2^31-1; anything else is refused before any work);
without one the graph draws it, so the recipe always holds the seed that made the picture.

| What | Where |
|---|---|
| `PATCH /products/wasifyai-image/images/{id}` `{favourite}`, `GET .../images?favourites=true` | `products/wasifyai-image/wasifyai_image/routes.py` |
| `POST .../images/{id}/export`: copies the file into `~/Downloads` (or `WASIFYAI_EXPORT_DIR`), never overwrites, answers `{name, path}`; 404 where no folder is set (web profile) | same; `app.state.export_dir` is set by the desktop profile in `main.py` |
| Postgres columns | migration `0017_image_recipes` |
| SQLite columns on an older file | `ensure_columns` (SDK), run by the image store |
| "Make it again" | text images with a recipe only: an edit's source picture is deleted once the image is saved |

The recipe does not name the model: the graph asks for a capability. The same seed gives the same picture on the
same installed model. `docs/phase2-stage-b-plan.md` has the decisions.

### Styles (LoRAs), Vary and Edit this result

A request may carry `loras: [{name, weight}]` (at most 3, weight 0.1 to 2.0, names relative to a `loras` folder).
The image graph validates them before any model is asked, the recipe keeps them, and a workflow whose map file has
no `lora_chain` refuses them. `GET /desktop/loras` answers `{ready, available}`: a LoRA in a ComfyUI-layout folder
(`<root>/loras/...`) is usable once its root is a read-only folder ("Use it"); the app's own `models/loras` folder
is scanned too. The loader is model-only (`LoraLoaderModelOnly`). A missing file stops the job with `lora_missing`.
Vary re-runs the recipe with a new seed; Edit this result makes the picture Edit's source. Evidence and numbers:
`docs/phase2-stage-c-plan.md`.

The window may `PATCH`: the desktop CORS list includes it (the self-test found it was missing).

## Finding models other tools left here (ADR-0063)

The engine looks, by itself shortly after it starts, in the known folders of Ollama, LM Studio, the Hugging Face
cache, ComfyUI (including Comfy Desktop's shared folder), Unsloth Studio, Pinokio, AnythingLLM, GPT4All and Jan.
The list is data (`services/api/src/wasifyai_api/discovery.yaml`); `OLLAMA_MODELS` and `HF_HUB_CACHE` move
their entries.

| Piece | Where |
|---|---|
| Header readers: GGUF (architecture, name, quantisation, licence; the tokenizer is never read), safetensors (tensor names classify language / image / video / LoRA / VAE / text encoder), diffusers and transformers repos by `model_index.json` and `config.json`; `.ckpt` is named, never opened | `desktop_discovery.py` |
| Bounded walk: depth 7, 60 000 files, 25 s; folder links are not followed; stubs under 1 MB and vocabulary-only GGUFs are dropped; shards count as one model | same |
| States: `ready` (already in a folder the app uses), `can_use` (a catalogue file in the right folder: one click adds that folder as a read-only models folder), `later` (recognised, a planned stage uses it), `unsupported` | `assess()` |
| Running servers (Ollama, LM Studio, ComfyUI) answered on loopback only; reported, never started or used yet | `probe_servers()` |
| Routes: `GET /desktop/discovery`, `POST .../scan`, `PUT .../settings` `{enabled, folders}`, `POST .../use` `{id}` | same |
| Window: "Found on this computer" under Models; "Finding models" in Settings (switch, more folders) | `FoundModels.tsx`, `pages/Settings.tsx` |

macOS asks before an app reads Documents, Desktop, Downloads or removable drives, so such known folders
(`needs_permission` in the data file) are offered with "Look in this folder" instead of being read. The result is
kept in the settings store (`desktop.discovery`) and lives on this computer only.

Measured on the owner's Mac (Ollama, the Hugging Face cache, Comfy Desktop's shared folder, Unsloth): 26 models
found in 0.1 s: 4 language, 6 image, 2 video, 3 embedding, 1 LoRA, 9 parts and files of image models; three
FLUX.2 klein files are `can_use`.

## The language engine (llama.cpp, stage D)

An optional component like the image engine, installed on demand from Settings ("Set up the language engine").
It is llama.cpp's prebuilt release for this platform (pinned in `engine-manifest.json`, checksum checked,
about 12 to 20 MB, no Python), unpacked under `<app data>/engine/llamacpp/<release>/` with a `state.json` the
engine reads. The engine (`llama_server.py`) runs one `llama-server` at a time on loopback for one model file and
stops it to free the memory. Only the Apple-silicon build uses a GPU; the other builds run on the processor.
`GET /desktop/language-engine` and `POST /desktop/language-engine/stop` are the routes; choosing a model and the
chat provider are D2 (`docs/phase2-stage-d-plan.md`).

## The assistant (ADR-0057, stage D3 and D4)

`wasifyai-assistant` is a product like the others, enabled on the desktop by default. A turn is a run of its
graph: `POST /products/wasifyai-assistant/runs` with `{"text": ..., "conversation_id"?: ...}` streams `token`,
`tool_call`, `tool_result` and `job_progress` events and ends with `done` (`conversation_id`, `title`, `reply`).
Conversations are listed, read, renamed and deleted under `/products/wasifyai-assistant/conversations`. It
answers with the model chosen in Models; with none chosen the run ends with an error that says to choose one.

Tools are an explicit list in `wasifyai_assistant/tools.py`. `generate_image` runs the image product as a child
run, so the picture is saved, indexed and has its recipe like any other; `search_creations` looks in the person's
own library. The model never sees a file or a link, only a sentence and ids.

### Evaluating a model for the assistant

`uv run python products/wasifyai-assistant/evals/run_tool_eval.py --gguf <file> --data-dir <app data>` runs the
tool-choice cases in `evals/cases.yaml` against a model with the assistant's own prompt and tools and prints
accuracy, answer time, speed and the server's memory. Add a case for every mistake a model makes in real use.
The recommended model on the hub shelf is the one that scores best here.

## The model hub (ADR-0064, stage D2b)

Models has two tabs. **On device** is the app's models, the chat model and what other tools left here.
**Discover** finds open models on Hugging Face and fetches one. The window never contacts the internet: the
engine does (`desktop_hub.py`, `/desktop/hub/...`), only after the person agrees (Settings has the switch), and a
download is only started from the exact files and size the person confirmed, re-checked against the repository at
its current commit and its published SHA-256. Pickle formats are never offered; a gated model is refused until
account sign-in exists. The recommended list (`hub-shelf.yaml`) works without the network.

## The chat model (stage D, D2)

The model that answers when the app needs words: improving a prompt now, the assistant next. It is chosen in
Models ("Chat model"): a found GGUF file run by the app's own `llama-server` (the language engine must be set
up), or a model of a running Ollama or LM Studio, used where it is.

| What | Where |
|---|---|
| The choice and the session that makes it ready (holds the `chat` slot for a file) | `desktop_language.py` `LanguageService` |
| The text provider every product's text capabilities use on the desktop | `LocalTextProvider`, supplied as `ProviderDeps.text_provider` in `main.py` |
| `GET /desktop/language`, `PUT /desktop/language` `{item_id, context}` or `{server}` or `{clear}`, `POST /desktop/language/try` | `desktop_llm.py` |
| Fit at the chosen context, with the engine's own backend | `language_machine()` and `desktop_fit.need_of_language(chosen=...)` |
| Window | `ChatModel.tsx`, `language.ts` |

A file is refused when the engine cannot read it (`unsupported`) or the computer cannot hold it (`too_big`); a
server is only one the engine found itself on `127.0.0.1`. Choosing never starts anything: the first request
does, so a person who only browses Models costs no memory.

## Will it fit? (ADR-0063)

`desktop_fit.py` answers `fits`, `tight` or `too_big` for a model, with a reason in plain words, from what the
computer has now.

| Device | Capacity (more cannot work) | Budget (free to use now) |
|---|---|---|
| Apple silicon (unified memory) | 90% of the memory | 75% of it, or what is available if less |
| NVIDIA card | the card's memory; a language model may spill into 50% of the RAM | the card's free memory (the same spill rule) |
| Processor only | 85% of the memory | what is available |

- **Free memory** is read from `vm_stat` (macOS), `/proc/meminfo` (Linux) or `GlobalMemoryStatusEx` (Windows);
  the card from `nvidia-smi`. Memory held by the app's own resident model counts as free, because the next model
  is loaded into it.
- **What a model asks for:** the catalogue's declared (measured) figure where it has one, otherwise an estimate:
  language models are weights plus the KV cache for 8192 tokens (from the GGUF header) plus 0.6 GB; image and
  video files are weights x 1.15 plus 3 GB (6 GB for video). Estimates are labelled "about".
- **Where it is used:** the Models list and found models (a badge and the reason); the download confirmation
  (`too_big` needs "get the files anyway", the engine refuses a request without `accept_memory`); the Create
  screen (a notice for `tight`, Generate off for `too_big` with the reason); and the engine itself, which
  refuses a real image job that cannot fit before anything is loaded (`FitGuardRunner`, error `model_too_big`).
  A found model that cannot fit is never offered with "Use it".
- **Tune with measurements.** The 0.9 / 0.75 / 0.85 limits and the +3 GB working memory are starting values;
  record real peaks per model family and adjust.

## The self-test

`WASIFYAI_SMOKE=1 cargo run` (in `apps/desktop/src-tauri`) starts the shell as usual; once the engine is ready
the window opens the Create screen (`#/images/create`), types a prompt, presses Generate, favourites the result, reads its seed, presses "Make it again" and expects the same seed and size, waits for the picture to load from the
engine's signed link, and the shell prints `SMOKE PASS ...` and exits 0 (`SMOKE FAIL ...` and 1 otherwise).
It drives the real DOM in the real webview, so CORS, the content security policy and the file link are all
exercised. It needs the engine environment (`.venv`).

## What is not done

- **Gallery extras.** Collections, tags and bulk actions are not built; the model id is not in the recipe yet.
- **Menu entries marked "Soon"**: Transform, Inpaint, Extend, Upscale, Reference, Train; Projects and
  Recents (they need the assistant and projects, ADR-0057). The home "Ask anything" box does not answer.
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
