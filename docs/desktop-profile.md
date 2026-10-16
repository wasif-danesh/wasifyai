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
| Router | `router.ts` | URL hash, eight routes: `/`, `/images/create`, `/images/edit`, `/library`, `/models`, `/settings`, `/notebooks` and `/notebooks/<id>` (`new` is a draft). No library. `useRoute` answers an object; a chat or a draft notebook gets its address without a reload (`adopt`, `adoptNotebook`) |
| Shell | `Shell.tsx` | side menu + the screen; the menu collapses (remembered in `localStorage`) |
| Side menu | `Sidebar.tsx` | New chat; groups **Notebook** (Create, View Notebooks), **Images** (Create, Edit, and Transform, Inpaint, Extend, Upscale, Reference marked "Soon", Your images), **Video**, **Voice** (Text to speech and Speech to text work; Lip sync and Voices are "Soon"), **Music** (Create and Your music work; Lyrics is "Soon"); Library, Models, Train ("Soon"); Recents; You and settings. One group is open at a time and the one holding the current page stays open |
| Home | `pages/Home.tsx` | greeting and the "Ask anything" box (the assistant, ADR-0057, is not built: the box says so) |
| Create / Edit | `pages/Create.tsx` | wraps the shared `ImageWorkspace` with this window's model chip and setup notices |
| Notebooks | `pages/Notebooks.tsx`, `pages/Notebook.tsx`, `notebook-setup.ts` | View Notebooks (cards, search by title and by what is inside, rename, delete, the setup card) and one notebook (the shared `NotebookWorkspace`) |
| Library | `pages/Library.tsx` | wraps the shared `ImageLibrary`; "Make it again" sends the recipe to Create (`Shell.tsx` holds it until the route changes) |
| Models, Settings | `pages/Models.tsx`, `pages/Settings.tsx` | the model panel; the image engine card, updates, restart and repair |

On macOS the title bar is an overlay (`titleBarStyle: Overlay`, traffic lights at 18,22) and the menu leaves
room for them; elsewhere the native title bar stays. Dragging uses `data-tauri-drag-region` with the
`core:window:allow-start-dragging` capability. Items that are not built yet are shown disabled and labelled,
not hidden, so the menu keeps its final shape.

### The side menu's final shape (decided 2026-10-16; built in stage E3, with Video, Voice and Music shown as Soon)

Every product is one expandable group, the pattern *Images* already uses: clicking the group only opens or
closes it, and the items inside are the tools. Items whose product is not built on the desktop yet are shown
disabled with the **Soon** pill, so the menu keeps its final shape (as above).

| Group | Items | Engine today (ADR-0062) | Built on the desktop |
|---|---|---|---|
| *New chat* | (single item) | assistant (ADR-0057) | yes |
| **Notebook** | Create, View Notebooks | `wasifyai-notebooks` (ADR-0065) | stage E |
| **Images** | Create, Edit, Transform, Inpaint, Extend, Upscale, Reference, Your images | ComfyUI | Create, Edit |
| **Video** | Create, Animate an image, Extend video, Your videos | `wasifyai-video` on ComfyUI (`video.generate`, `video.animate`) | Soon |
| **Voice** | Text to speech, Speech to text, Lip sync, Voices | `wasifyai-voice` on audio.cpp (ADR-0066); lip sync MuseTalk later | Speak and Transcribe built (V1); the rest Soon |
| **Music** | Create, Your music, Lyrics | `wasifyai-voice` on audio.cpp (ADR-0066, V3); the ComfyUI ACE-Step workflow and `text.lyrics` later | Create and Your music built; Lyrics Soon |
| *Library* | (single item) all creations, searchable (ADR-0041) | | yes |
| *Models*, *Train* (Soon) | single items | | Models yes |

Rules:
- **"Your ..." items open the Library filtered to that kind** (the per-kind filter ADR-0041 already requires), not
  a second store. *Library* stays the place for everything.
- **One group open at a time** (an accordion): opening one closes the others; the group holding the current
  page stays open. Eight groups would not fit otherwise.
- The owner approved the whole list, including *Your images*, *Voices* and *Lyrics* (2026-10-16).
- *Create* in **Notebook** opens a draft stored after the first source (plan, open question 2).
- The *Recents* list stays at the foot and scrolls.
- The same group and item definitions feed the web product's side panel later (`lib/products.ts`, ADR-0046).

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
own library and names what it finds (notebooks by title) but does not read inside documents.
`search_notebooks` (stage E6) looks inside the person's notebooks: the engine embeds the question once, runs the
notebooks' hybrid retrieval over up to 40 notebooks that have a ready source (the most recently used), keeps 3
passages per notebook, merges by score, and returns the best 5 with at most 2 per source. The model gets each
passage (up to 700 characters) with its notebook and source, told that it is quoted material and not
instructions; the window shows the source, the notebook and a snippet, with "Open notebook". If the search model
is not installed or notebooks are not part of the build the tool answers that in words. The model never sees a
file or a link, only a sentence, passages and ids.

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

## Notebooks (ADR-0065, stage E1: the engine)

`products/wasifyai-notebooks` is a library of sources per notebook: read, cut into passages, indexed on this
computer, and searched. The window and the grounded chat arrive in E3 and E2; this is the engine.

| Piece | File | What |
|---|---|---|
| Store | `wasifyai_notebooks/store.py` | `<data>/notebooks/notebooks.db`: notebooks, folders (8 deep), documents, passages; FTS5 by trigger, vectors in sqlite-vec; dedup by SHA-256 per folder; every read scoped by tenant and user |
| Hardening | `hardening.py` | extension list, bytes must match the extension, OOXML entry and unpacked-size limits, 100 MB, one safe path part for the stored name |
| Reading | `reading.py`, `docling_worker.py` | text, Markdown, CSV and HTML are read in the engine; the rest by Docling in its own process (`--serve`: one process per batch, gone after 60 s idle), 15 minutes per file at most |
| Cutting | `chunking.py` | SurfSense's recursive rules at 480 tokens of the search model's tokenizer; every passage keeps its Markdown line span |
| Search model | `embedding.py`, `models.yaml` | bge-small-en-v1.5 (quantised ONNX, 67 MB) through the Models panel like any model; the index records it and refuses another |
| Retrieval | `retrieval.py` | SurfSense's blend of BM25 and cosine (0.65), per notebook or per ticked sources; `mode` dense, lexical, hybrid for evaluation |
| Ingest | `ingest.py` | one source at a time, highest priority first; cancel checked between steps; nothing is read until the search model is present (sources wait, they do not fail); a file with almost no text fails in words (`No text could be read...`); work in progress at quit is failed at start with Retry |
| Reader setup | `reader_install.py`, `reader/` | `POST /setup/reader` with the size shown: environment from the engine's own Python, hashed lock per platform, nine weight files by SHA-256, a check that reads a test picture. Lock compiled by `scripts/build-engine-bundle.sh` |
| Search index | `index.py` | notebooks are a creation kind (`notebook`) in My creations search (ADR-0041) |

Routes, under `/products/wasifyai-notebooks` (loopback token; another person's notebook is a 404):

| Route | Does |
|---|---|
| `GET /status` | what is set up: search model, reader (with setup progress), passage count |
| `POST /setup/reader` | start the reader setup; `{confirm_bytes}` must equal the size offered |
| `GET/POST /notebooks`, `GET/PATCH/DELETE /notebooks/{id}` | list (newest opened first), create, read (marks it opened), rename, delete |
| `GET/POST /notebooks/{id}/folders`, `PATCH/DELETE .../folders/{fid}` | folders; deleting one removes its sources |
| `GET /notebooks/{id}/documents` | sources, with `status` and `folder_id` filters; polled while any is reading |
| `POST .../documents` | a note |
| `POST .../documents/upload` | multipart `files`, optional `folder_id`; answers `created`, `duplicates`, `rejected` (each with its reason) |
| `GET/PATCH/DELETE .../documents/{did}` | read with its Markdown, rename or edit a note, delete (409 while being read) |
| `POST .../documents/{did}/retry`, `.../cancel`, `.../documents/move` | requeue, stop, file into a folder |
| `GET .../documents/{did}/original` | the stored file, always as an attachment |
| `GET .../passages/{chunk_id}` | a passage and its neighbours, for opening a citation |
| `POST .../search` | `{query, top_k, document_ids?, mode?}`: passages with scores and line spans; 409 `embedder_missing` |

Measured on the owner's Mac (14 files, 66 pages, 7 real PDFs and 7 generated files; details in
`docs/phase2-stage-e-plan.md`): 30 s from upload to all searchable with the reader running as one process
(72 s when each file started its own), 69 passages, retrieval 22 of 24 answerable questions at rank 1 and 24 of 24
in the top 3, 10 ms per question over HTTP; a clean setup of the reader 70 s (packages from the cache,
weights downloaded).

**Asking a notebook (stage E2).** A question is a run of the product's graph, not a new route:
`POST /products/wasifyai-notebooks/runs` with `{text, notebook_id, conversation_id?, document_ids?}`.
The graph (`graph.py`) searches the ticked sources (a `search_sources` step), puts the best five passages in the
user message with the question (`grounding.py`, SurfSense's prompts), streams the answer, then checks the
labels (`[n]`): numbers that are not passages go, a sentence that says the sources do not hold the answer
carries none, and a label must share a word with its passage. The answer, its cited passages (text as it
was) and the conversation are saved in `notebooks.db`. The prompt is the shorter `compact` one for a chosen
model file under 1.5 GB and `capable` otherwise; the history is trimmed to the model's window
(`context - 1024 answer - 450 system - 2400 passages - question`). Routes added:
`GET/GET/PATCH/DELETE /notebooks/{id}/conversations[/{cid}]`. Measured with Qwen3 4B: 24 of 24 answers right,
refusals said in words, no labels on them, a median of 4 s (`docs/phase2-stage-e-plan.md`, "E2 evidence").

**Studio (stage E4).** `studio/` makes a notebook's outputs. Formats: `report`, `study_guide`, `flashcards`,
`quiz`, `mindmap`, `word`, `pdf`. A run of the notebooks graph with `studio: {format, prompt}` and the ticked
`document_ids` (formats: also `slides`, `datatable`, `audio`, `infographic`; `guide` is saved with the notebook, not as an output) saves an `artifacts` row (status `processing`), reads the sources cut to the model's window
(`studio/context.py`: whole, an even share each, or the best passages), asks the model for Markdown or JSON under
the prompt for its tier (`studio/prompts/`, SurfSense's), builds and checks it (`studio/formats.py`; one second
try with the reason), renders Word and PDF with `studio/word.py` and `studio/pdf.py`, and saves the body, the
data and the file under `<data>/notebooks/artifacts/<notebook>/<id>/`. Routes: `GET .../artifacts`,
`GET/PATCH/DELETE .../artifacts/{id}`, `POST .../artifacts/{id}/cancel`, `GET .../artifacts/{id}/file` (always an
attachment). `GET /notebooks/{id}/guide` answers the source guide (`guide`, `stale`, `ready`). An infographic's picture is made by a child run of the image product (the assistant's tool host), so it needs image generation set up; a deck is `.pptx` (python-pptx), a table `.xlsx` (openpyxl, values only), an audio overview a script, spoken on request (see "Speech" below). The window's Studio pane has a tile per format, a short brief (a focus and "made from 12 sources"),
the list of outputs (polled while one is being made), and viewers for each format.

The notebooks are served on the desktop profile only (the routes answer 503 without an app data folder); the
web profile needs a Postgres and pgvector adapter of the store (not built).

## Notebooks in the window (stage E3)

The shared screens are in `packages/ui/src/notebook/`, the client and the reducer of a question in
`packages/client/src/notebooks.ts`; the app only supplies the clients, the setup logic and the menu.

| Piece | What |
|---|---|
| `NotebookList` | cards with the counts (sources, being read, could not be read) and when it was opened; search by title and, through My creations search (`kind=notebook`), by the names of the sources |
| `SetupCard` | "Set up reading documents": the search model (through the Models panel's download) and the document reader (`POST /setup/reader`); each says its size and goes ahead only on a click; progress and a failure's sentence are shown |
| `NotebookWorkspace` | header (name, "12 of 14 sources, 2 being read"), three panes, tabs under 1,024 px; a new notebook opens on the add-sources screen and is saved when its first source is added or its name is set |
| `AddSources` | upload (picker or drop), copied text, Websites shown as Soon; files the engine will not take are named before sending |
| `SourcesPane` | tree with tri-state ticks (everything is ticked until something is unticked, so a source added later counts), folders, status per source with Retry and Stop, rename, move, remove |
| `SourceViewer` | the source's text as the notebook reads it, the cited passage marked; a removed source still shows the passage an answer used; a note can be edited; the original can be saved |
| `NotebookChat` | the thread, the search shown as one line, answers with `[n]` pills that open the passage, Copy, the scope and model chips, "Add a source first" and the other reasons the box is blocked |
| `StudioPane`, `OutputViewers` | the eleven formats as tiles, a brief, the outputs list, and viewers: Markdown, flashcards that turn over, a quiz that scores, a mind map as a tree, slides, a table, the audio script, an infographic with its exact facts; save the file |

The scope sent with a question is `document_ids` of the ticked, ready sources, or nothing when nothing is
unticked. The menu steps aside on a window narrower than 1,280 px while a notebook is open and comes back when
the person leaves it (a menu the person closed stays closed). The self-test creates a draft notebook, adds a file
through the real file input, sees it listed, and finds the notebook's card.

## Speech: speak and transcribe (ADR-0066, stage V1)

One native program, audio.cpp (Apache-2.0), serves every speech model on this computer, and the person picks the
model from a list. Evidence: `docs/spikes/voice-v0.md`, `docs/phase2-voice-plan.md`.

| Piece | Where | What it does |
|---|---|---|
| Model descriptors | `products/wasifyai-voice/models.yaml` (`voice:` block of an entry) | tasks, languages, voices, options, sample rate, measured speed and memory, and the weights' licence with `commercial_use` (yes, conditional, no, unreviewed) and its evidence. Only `yes` can be recommended. Types and request checks: `platform-sdk/voice_models.py` |
| Spec data | `products/wasifyai-voice/specs/` | audio.cpp `v0.9.0` spec files; a test checks that voices, options and the package file agree |
| Runtime | `wasifyai_api/audio_runtime.py`, pins in `audio_pins.json` | installer (size and SHA-256 shown first, confirm to download, unpacked safely, checked by running `--version`), or "use the copy already on this computer" (same tag, same hash); one `audiocpp_server` with every model that is present, lazy loading, one model in memory, loopback; the `audio` owner of the one slot (starting it stops a resident chat model, and the reverse) |
| Routes | `GET /desktop/audio`, `GET /desktop/audio/models?task=`, `POST /desktop/audio/install` (`confirm_bytes`), `/use-found`, `/stop`; `GET /desktop/models?task=` filters the catalogue | model states: ready, needs the runtime, not on this computer, not available |
| Product | `wasifyai-voice`: graph `speak` (a run), `/speeches`, `/transcripts` (upload, list, get, rename, delete, export txt, srt, vtt) | `voice.db` and files in the app's storage; speeches and transcripts are in My creations search (kinds `speech`, `transcript`) |
| Window | Voice menu: Text to speech, Speech to text | model list with licence badge, cost line, state and "Get it in Models"; voice list; options made from the descriptor; setup card for the runtime; a made-before list; a transcript with times and Save as text or subtitles |

Rules in the code: a request is checked against the descriptor before it is sent (an unknown option or voice is
refused in words, because the runtime answers a mistake with HTTP 500 and may ignore an option silently); the
runtime's own messages are not shown; a cancelled request restarts the runtime; no model is chosen for the person
silently (the recommended one is only the starting choice).

Recordings: the runtime reads WAV only. Other formats are converted with ffmpeg when it is on the computer, else with
macOS's `afconvert`; with neither the person is told to install ffmpeg or save a WAV. Bundling ffmpeg is an open
question for the owner (licence and size).

### Your voices and the audio overview (stage V2)

| Piece | What it does |
|---|---|
| Descriptors | `design` and `clone` rules in `models.yaml` say how a model takes a description (`instruct_option` for Qwen3-TTS, `text_prefix` for VoxCPM2, which ignores the option) and a recording (reference words required or optional, 2 to 30 seconds). Checks: `check_design`, `check_clone` in the SDK |
| Saved voices | `/products/wasifyai-voice/voices`: `POST /voices/design` (name, description), `POST /voices/clone` (recording, name, **consent** `own` or `permission`, optional words), `PATCH` (name, description, the words), `DELETE`, `GET /voices?kind=`. A voice is not tied to a model: any ready model that can design or clone speaks it. A clone without a consent answer is refused (422 `consent_required`); the answer, its sentence and the time are kept with the voice |
| Recording | converted if needed, kept as WAV of at most 30 seconds (cut at the start), refused under 2 seconds; stored for playback and as a file under `<data>/voice/voices/` that the runtime reads |
| Speaking | a run of the Speak graph with `saved_voice` (and optionally `model`); the engine picks the recommended design or clone model otherwise; refused in words before loading when the voice cannot be used with the model (words missing, recording length) |
| Window | Voice > Voices: describe or clone, hear a sample, change the words, delete, "Use in Text to speech"; Text to speech lists "Your voices" and then offers the models that can do what that voice is |
| Audio overview | `POST /notebooks/{id}/artifacts/{aid}/voices`: the script's turns are spoken one by one by a speech model with built-in voices (Kokoro: a woman and a man by default, or `voices: {"1": id, "2": id}`), joined with pauses, kept as `overview.wav`, and the output's data gains `audio: true`; `GET .../voices` says how far it has got, `GET .../audio` is the sound. In the Studio viewer: "Speak it", progress, a player |

Saved voices and recordings are in My creations search (kind `voice`). Voices stay on this computer.

### Music (stage V3)

Music is another task of the same product and the same runtime, picked from the same kind of list.

| Piece | What it does |
|---|---|
| Descriptors | a `music` block: the modes a model makes (`song`, `sfx`), per mode whether it takes lyrics (`optional`, `required`, `unused`), whether it can leave the singing out (`toggle`, `always`, `never`) and its lengths as [shortest, usual, longest] seconds; and `request`, how the runtime takes the parts: the duration as a field of the request (`top`) or an option (`option:<name>`), the option that carries lyrics, what an instrumental is called (`[Instrumental]`). Catalogue: ACE-Step 1.5 Turbo (MIT, recommended), Stable Audio 3 Small music and sound effects (Stability Community Licence: **conditional**, never recommended) |
| Checks | `check_music`: a description of 3 or more characters; lyrics for a model that does not sing, or with "no singing", or singing that is required but missing, are refused in words (never dropped); a length outside the model's range is brought into it |
| Engine | `AudioEngine.music`: builds the request from the descriptor, chooses a random seed when none is given (the runtime's default is fixed, so every run would repeat), waits up to 40 s per second of music (at most two hours), reads the answer as raw audio or as JSON with base64 audio |
| Product | the Speak graph with `task: "music"`; `/tracks` (list, get, download, rename, delete); `voice.db` table `tracks`; My creations search (kind `track`) |
| Window | Music > Create (model list, Music or Sound effect when the model has both, description, lyrics only if it sings, "No singing" only if it can, length, seed, an estimate from the measured speed, elapsed time while it works, Cancel) and Your music (play, save as WAV, rename, delete) |

Not in V3: editing a clip (repaint, extend, cover, inpaint: the runtime has them for ACE-Step and Stable Audio), the
ComfyUI ACE-Step workflow as a second engine for the same list, lyrics writing (`text.lyrics`), and a listening
check of the quality.

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
