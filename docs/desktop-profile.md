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
| Products served | all registered | `PRODUCTS_ENABLED` (default: image, video, assistant, notebooks, voice) |
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
| `PRODUCTS_ENABLED` | comma-separated product ids; empty means all (desktop: image, video, assistant, notebooks and voice) |
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
| Side menu | `Sidebar.tsx`, `menu.ts` | the shared `SideMenu` of `packages/ui` (the web app uses the same one; the menu is defined once in `packages/ui/src/shell/menu.ts`, and `menu.ts` here says what each item opens in the window; an item missing there shows as "Soon"). New chat; groups **Notebook** (Create, View notebooks), **Images** (Create, Edit, and Transform, Inpaint, Extend, Upscale, Reference marked "Soon", Your images), **Video** (Create, Animate an image, Extend video, Your videos), **Voice** (Text to speech, Speech to text, Lip sync, Voices, Change a voice, Edit speech, Dub a recording and Audiobook), **Music** (Create, Your music, Lyrics and Split into parts); Library, Models, Train ("Soon"); Recents; You and settings. One group is open at a time and the one holding the current page stays open |
| Home | `pages/Home.tsx` | the shared `AssistantHome` of `packages/ui` (the web app's home is the same screen), with this window's "choose a chat model" notice |
| Create / Edit | `pages/Create.tsx` | wraps the shared `ImageWorkspace` with this window's model chip and setup notices |
| Notebooks | `pages/Notebooks.tsx`, `pages/Notebook.tsx`, `notebook-setup.ts` (the web app mounts the same `NotebookList` and `NotebookWorkspace`, with `NotebookPlaceProvider` saying where documents live) | View notebooks (cards, search by title and by what is inside, rename, delete, the setup card) and one notebook (the shared `NotebookWorkspace`) |
| Library | `pages/Library.tsx` | wraps the shared `ImageLibrary`; "Make it again" sends the recipe to Create (`Shell.tsx` holds it until the route changes) |
| Attach (chat box) | `packages/ui/src/chat/attachments/`, `services/api/.../attachments.py`, `products/wasifyai-assistant/wasifyai_assistant/attachments.py` | pictures (the model's projector, `--mmproj`, fetched from `projector-shelf.yaml` after a click: `desktop_vision.py`) and documents (read to text on the engine); see the CO2 section of `docs/spikes/composer-co0.md` |
| Models, Settings | `pages/Models.tsx`, `pages/Settings.tsx` | the model panel; the image engine card, updates, restart and repair; "Searching the web" (`SearchSettings` in `packages/ui`: service, permission, key; the engine side is `web_search.py`, keys encrypted with `secrets.key` in the data folder, ADR-0083) |

**The top bar (2026-10-21).** One row, 36 px high, across both panels (`TitleBar` in `packages/ui`, placed by `Shell.tsx`),
tinted like the side menu and so a little lighter than the page. On the left, level with the window's buttons: back, forward
and hide or show the side menu (`useHistoryButtons` in `router.ts` counts the screens visited, or uses the Navigation API when
the web view has it). On the right: the screen's title and tools. A screen puts its own header there with `PageHeader`
(`window-bar.tsx`: in the window it is portalled into the bar, on the web it stays a header of the page); a screen that gives
none gets the menu's name for it (tools marked `pageOnly`, the chat's rename and delete, are kept out of the bar for now: backlog D21) (`routeTitle` in `menu.ts`). The whole bar is a drag region, both panels, and its text lets
clicks through to it. On macOS the title bar is an overlay (`titleBarStyle: Overlay`); the traffic lights are placed at
`trafficLightPosition` 18,18 so their centres sit on the bar's middle line (the bar's height is `TITLE_BAR_PX`; change the two
together), and the left group starts 84 px in to clear them; elsewhere the native title bar stays. Dragging uses
`data-tauri-drag-region` with the `core:window:allow-start-dragging` capability. **Not seen in the real window**: only checked in
the browser pane, where the traffic lights do not exist. Items that are not built yet are shown disabled and labelled,
not hidden, so the menu keeps its final shape.

### The side menu's final shape (decided 2026-10-16; built in stage E3, with Video, Voice and Music shown as Soon)

Every product is one expandable group, the pattern *Images* already uses: clicking the group only opens or
closes it, and the items inside are the tools. Items whose product is not built on the desktop yet are shown
disabled with the **Soon** pill, so the menu keeps its final shape (as above).

| Group | Items | Engine today (ADR-0062) | Built on the desktop |
|---|---|---|---|
| *New chat* | (single item) | assistant (ADR-0057) | yes |
| **Notebook** | Create, View notebooks | `wasifyai-notebooks` (ADR-0065) | stage E |
| **Images** | Create, Edit, Inpaint, Reference, 3D model, Your images (Transform, Extend and Upscale were taken out of the menu 2026-10-21; `docs/spikes/unsloth-image-workflows.md`) | ComfyUI | Create, Edit, Inpaint, Reference (2026-10-21) |
| **Video** | Create, Animate an image, Extend video, Your videos | `wasifyai-video` on ComfyUI (`video.generate`, `video.animate`, `video.extend`); LTX-Video 2B (V8) | Create, Animate an image, Extend video (2026-10-21), Your videos |
| **Voice** | Text to speech, Speech to text, Lip sync, Voices | `wasifyai-voice` on audio.cpp (ADR-0066); lip sync is MuseTalk, an optional sidecar | all built (V1 to V5) |
| **Music** | Create, Your music, Lyrics | `wasifyai-voice` on audio.cpp (ADR-0066, V3); the ComfyUI ACE-Step workflow and `text.lyrics` later | Create and Your music built; Lyrics Soon |
| *Library* | (single item) all creations, searchable (ADR-0041) | | yes |
| *Train models*, *Model hub* | single items, in this order; the hub is last (owner, 2026-10-25: *Models* was renamed *Model hub*, the page where models are got and managed) | | both built |

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
| `POST .../images/{id}/export`: body `{path}` writes the file at the path the person chose in the system's Save As box (the window opens it with Tauri's dialog plugin and cannot write a file itself; the engine refuses a folder, a missing folder and anything inside its own data folder); without a `path` it copies into the export folder (`WASIFYAI_EXPORT_DIR`, which the shell sets to the operating system's own Downloads folder, for the assistant's export action) and never overwrites. The video, 3D and notebook-output export routes take the same `{path}`; screens that hold the bytes themselves (speech, music, transcripts, lip sync, a source's original) send them to `POST /desktop/save` with the path. Answers `{name, path}`; 404 where no folder is set (web profile) | same; `app.state.export_dir` is set by the desktop profile in `main.py` |
| Postgres columns | migration `0017_image_recipes` |
| SQLite columns on an older file | `ensure_columns` (SDK), run by the image store |
| "Make it again" | text images with a recipe only: an edit's source picture is deleted once the image is saved |

The recipe does not name the model: the graph asks for a capability. The same seed gives the same picture on the
same installed model. `docs/phase2-stage-b-plan.md` has the decisions.

### Reference and Inpaint (built 2026-10-21; `docs/image-inpaint-reference-plan.md`, `docs/spikes/image-ir0.md`)

Both run on FLUX.2 klein 4B through ComfyUI; no new model.

- **Reference** (*Images › Reference*, action `image.reference`): two pictures and a prompt make a new picture at a size the person
  chooses. Workflow `flux2-klein-4b-reference`: the Edit mechanism with a second reference, each picture scaled to half a megapixel
  (about 70 s instead of 100 to 120 s at a full megapixel, with both subjects still recognisable). Exactly two pictures.
- **Inpaint** (*Images › Inpaint*, action `image.inpaint`): the person paints the area (brush, eraser, rectangle, or a rectangle by
  numbers for the keyboard) and says what to put there. Workflow `flux2-klein-4b-inpaint`: klein has no inpainting model, so the
  Edit workflow runs on a copy of the picture with the area filled white ("fill the white area with ..."), and the result is pasted back
  through the mask: **outside the mask the picture is identical to the last pixel** (tested: two runs with different prompts and seeds
  agree on all 916,567 pixels outside the grown mask). The picture is worked on at about one megapixel. The model sometimes ignores a
  small area. The agent's `image.inpaint` takes a rectangle (shares of the picture) because an agent cannot paint.
- Each takes up to three uploads per run (`image`, `image2`, `mask`; `PICTURE_SLOTS` in the SDK); the graph deletes all of them on every
  way out. The mask is uploaded when the person presses Generate and is checked (not empty, not nearly all of the picture, the
  picture's shape) before any GPU work.

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

### The tools are catalogue actions (ADR-0068, stage A1)

The four tools run through the action executor (`wasifyai_platform_sdk.actions`, `docs/actions.md`): `generate_image`
is `image.generate`, `make_music` is `music.generate`, `search_creations` is `library.search`, `search_notebooks`
is `notebook.search`, all with the origin `assistant`. What the model is shown (names, descriptions, the system
prompt) and what the person sees did not change, so the tool-choice evaluation below measures the same thing. The
assistant's setting is "make things at once" (`ApprovalPolicy(make="auto")`); deleting and anything that needs a
person's word always ask, from any origin, and are not offered to the model. The engine builds the catalogue
for the products it serves (`app.state.actions`, `wasifyai_api.actions_engine`), with the audit log and the
pending approvals in the same SQLite file (`action_audit`, `action_approvals`, created on first use, additive
only). Every call writes one audit entry (no content) and one `action.run` usage event. `docs/contracts/actions.json`
is the catalogue as a file; `docs/help/` holds the help for every action.

### Evaluating a model for the assistant

`uv run python products/wasifyai-assistant/evals/run_tool_eval.py --gguf <file> --data-dir <app data>` runs the
tool-choice cases in `evals/cases.yaml` against a model with the assistant's own prompt and tools and prints
accuracy, answer time, speed and the server's memory. Add a case for every mistake a model makes in real use.
The recommended model on the hub shelf is the one that scores best here.

## The model hub (ADR-0064, stage D2b)

Models is a page of nine cards (Chat, Images, Video, Voice, Listening, Music, Faces, Documents, 3D), each with the model in
use, the one picker every screen has ("Select image model", ...) and Remove (ADR-0086). Choosing a model that is on the
computer uses it; choosing one that is not opens a dialog with the engine and the files, the total, the time, the licence and
where they come from, and "Download and use" does the lot. The window composes this from the routes below
(`apps/desktop/src/choices/`); the picker itself (`packages/ui/src/models/`) knows no engine. **Advanced** keeps the model folders,
the files other tools left here and Discover. The first time, the chat card offers the model that suits the computer's memory.
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
| Reader setup | `reader_install.py`, `reader/` | `POST /setup/reader` with the size shown: environment from the engine's own Python, hashed lock per platform, nine weight files by SHA-256, a check that reads a test picture. The locks are **committed** in `products/wasifyai-notebooks/reader/requirements-<target>.lock` (`make reader-locks` writes them; the bundle script copies them), so a development checkout (`pnpm tauri dev`) can set the reader up too: before 2026-10-19 only the bundle had them and a checkout said "The reader is not part of this build" |
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
| `StudioPane`, `OutputViewers` | the eleven formats as tiles, a brief, the outputs list, and viewers: Markdown, flashcards that turn over, a quiz that scores, a mind map as a tree, slides, a table, the audio script, an infographic with its exact facts; save the file; the Studio can be dragged wider or narrower by its left edge (arrow keys, double-click, or the expand button; the width is kept in this browser); rename and delete ask in a box of the page, and Save a copy writes into the Downloads folder through `POST /notebooks/{id}/artifacts/{id}/export` (the app window cannot download a file or show `window.confirm`/`window.prompt`, see backlog D18) |

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
| Window | Voice menu: Text to speech, Speech to text | model button ("Select ... model") with its dialog; voice list; options made from the descriptor; setup card for the runtime; a made-before list; a transcript with times and Save as text or subtitles |

Rules in the code: a request is checked against the descriptor before it is sent (an unknown option or voice is
refused in words, because the runtime answers a mistake with HTTP 500 and may ignore an option silently); the
runtime's own messages are not shown; a cancelled request restarts the runtime; no model is chosen for the person
silently (the recommended one is only the starting choice).

Recordings: the runtime reads WAV only. Other formats are converted with ffmpeg when it is on the computer, else with
macOS's `afconvert`; with neither the person is told to install ffmpeg or save a WAV. Bundling ffmpeg is an open
question for the owner (licence and size).

### Dictation: the Mic in the chat box (ADR-0083, stage CO4)

The chat box writes down what the person says. The window records the microphone (`getUserMedia` and an `AudioWorklet` loaded from `/recorder-worklet.js`, a file of the app itself because the window's content policy
refuses a blob) and averages it to a 16 kHz mono 16-bit WAV in the page; `POST /products/wasifyai-voice/dictation` returns the text and keeps nothing (WAV only, 10 MB and 5 minutes at most, a silent clip refused;
`wasifyai_voice/dictation.py`). The model slot has a **light-owner rule**: the speech model stays in memory beside the chat model when `ModelsService.fits_beside` says the two fit (the chat server's memory plus the
speech model's catalogue figure, against the fit check's budget), and dictation does not wait for a chat answer that is being written; when they do not fit, dictation unloads the chat model and the window says so.
The shell has `src-tauri/Info.plist` (`NSMicrophoneUsageDescription`) and `Entitlements.plist` (`com.apple.security.device.audio-input`, used when the app is signed); Cargo does not watch `Info.plist`, so after
editing it run `touch build.rs`. With no speech model the first press shows a setup card (name, licence, source, size, one download). Details and what was not verified: `docs/spikes/composer-co0.md`, "What CO4 built".

### Read aloud: the speaker under a reply (ADR-0083, stage CU3)

A button under each assistant reply speaks it with the local speech model (Kokoro 82M, Apache-2.0, 190 MB on disk, English only). It is opt-in (only a press starts it), local and keeps nothing: `POST /products/wasifyai-voice/read-aloud`
(`wasifyai_voice/read_aloud.py`) turns the reply into plain words, cuts it into passages and speaks the one asked for, and the window asks for the next while the first plays. The model slot treats it as dictation's twin: the same
`audio` owner with `beside_bytes` = 1 GB, so the voice stays beside the chat model when `fits_beside` says the two fit. With no voice the first press shows a setup card (name, licence, source, languages, size, one download). Details and what was not verified:
`docs/spikes/composer-co0.md`, "What CU3 read-aloud built".

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
| Product | the Speak graph with `task: "music"`, `music_edit` and `lyrics`; `/tracks` (list with `?favourites=`, get, download as WAV, MP3 or M4A, rename, favourite, delete), `/formats`; `voice.db` table `tracks` (schema 4: favourite, parent track, edit recipe); My creations search (kind `track`) |
| Window | Music > Create (model list, Music or Sound effect when the model has both, description, lyrics only if it sings, "No singing" only if it can, length, seed, the model's own options such as BPM and key, 1 to 4 takes, an estimate from the measured speed, elapsed time while it works, Cancel), Your music (play, search, Favourites only, save as WAV / MP3 / M4A, rename, favourite, delete, "Make it again", "Another take", "Change it") and Lyrics (describe a song, get words written by the chat model, send them to Create) |
| Edits | `music` descriptors list an `edit` block per model. ACE-Step: **repaint** a time range, **extend** past the end, **cover** in another style. Stable Audio: **inpaint** a masked range, **restyle**. `check_music_edit` refuses a part an action does not use; ranges are clamped and merged; the result is a new track that points at its parent, never an overwrite |
| Assistant | the `make_music` tool (child run of the music product); the chat shows a player and opens the track in Your music |
| Options | `bpm` and `keyscale` change ACE-Step's output and are sent; the runtime silently ignores anything it does not know (`language`, invented names), so every option is checked against the descriptor first |

Not built: the ComfyUI ACE-Step workflow as a second engine for the same list, models beyond these (HeartMuLa and
others), a watermark decision for generated audio, a song longer than 4 minutes, and a listening check of the
quality (sung lyrics in order cannot be tested by machine).

### Audio tools (stage V4)

Three tools work on a recording the person already has: a track, a speech, or a file added with **Add a recording**
(Your music keeps it as a track of kind "added from a file"). Each is a model chosen from a list, and each result is a
**track** in Your music with `parent_id` (what it came from) and an `edit` record, so search, favourites, rename and
saving as WAV, MP3 or M4A already work on it.

| Tool | Models (all `commercial_use: yes` unless marked) | What it needs |
|---|---|---|
| Split into parts (`separate`) | HTDemucs 4 stems (recommended), HTDemucs 6 stems (adds guitar and piano), Mel-Band RoFormer (vocals and instrumental): MIT | a recording up to 10 minutes; it is converted to 44.1 kHz stereo first; choose which parts to keep |
| Change a voice (`convert`) | Tone Color VC (OpenVoice v2, MIT, recommended), MeanVC2 (Apache-2.0) | a **saved cloned voice** to sound like (its consent record is copied into the result); both recordings are converted to the rate the model reads |
| Edit speech (`edit`) | dots.tts Edit (Apache-2.0 project, weights card says "other": `conditional`, never chosen for the person) | what the recording says now, written down by the speech-to-text model on request, and what it should say: the difference becomes `<sub targ="new">old</sub>`, `<del>`, `<ins>` tags (up to 5 separate changes) |

Routes: `POST /tracks/import` (multipart), `POST /words` (write down what a library recording says; nothing is
saved), and graph tasks `separate`, `convert`, `speech_edit` on `/runs` (source: `source_track` or `source_speech`).
The window: Music > Split into parts, Voice > Change a voice and Edit speech, and the same three as buttons on every
track in Your music. Not built: voice conversion with built-in voices (RVC), singing conversion (Seed-VC is GPL-3.0),
Vevo2 (CC-BY-NC-ND), enhancement and restoration models, and diarisation.

### Music on the image engine (stage V3b)

A music model can be run by the image engine's ComfyUI instead of audio.cpp (`engine: comfyui` in its descriptor).
The first is **ACE-Step 1.5 Turbo (image engine)**: the same song model, with the language of the lyrics and the time
signature as options (the audio.cpp build ignores a language). It needs the image engine set up and a 10 GB
checkpoint, and it holds the image slot while it works. The workflow is `products/wasifyai-voice/workflows/`, a copy
of the web product's with its last node changed to `PreviewAudio` so nothing is left in ComfyUI's output folder; its
map file names the inputs, so the code has no node ids. The model list shows "Needs the image engine" for it when
that is missing. It is not recommended: on a Mac, audio.cpp on Metal is about twice as fast. The reason for it is
Windows and Linux with a graphics card, where the pinned audio.cpp build runs on the CPU.

### Lip sync (stage V5)

A picture and a voice make a video of the face saying it. The model is chosen from the list like every other
(MuseTalk 1.5, MIT, the only one so far); the engine is an **optional component**, not part of the app.

| Piece | What it does |
|---|---|
| The engine | MuseTalk's code at an exact commit and a hashed package lock (`musetalk_pins.json`, `lipsync_server/musetalk.lock.txt`), set up on a click after the size (about 2.1 GB on disk) is shown, with the app's own `uv`, into `<app data>/engine/musetalk` (its own environment: torch must not touch the engine's). Apple-silicon Macs only for now (the one measured). The engine does this itself, like the speech runtime, not the shell like the image engine. A copy set up by hand is used as it is when `WASIFYAI_MUSETALK_HOME` names it (development) |
| The weights | the catalogue entry `musetalk-v15` (11 files, 4.2 GB: MuseTalk 1.5, the VAE, whisper-tiny, the face parser, ResNet18, and the face detector and landmark model) fetched in Models after the person sees their size; when the server starts they are linked to where MuseTalk reads them |
| The process | one `uvicorn` server on loopback (`lipsync_server/`), started on demand, stopped when something else takes the memory (it is its own owner of the one slot, about 12 GB) and when a run is cancelled |
| The picture | added with `POST /pictures`: checked, flattened to a clean PNG (no location or camera data), at most 1024 pixels; kept until a clip uses it, or for a day |
| The voice | words (made into speech here with the default model, and kept as a speech), or a recording from the library; at most 5 minutes |
| The clip | `clips` in `voice.db` (schema 5): the video, the picture (its poster), what the voice came from, the person's answers, the time taken; `GET/PATCH/DELETE /clips`, `/clips/{id}/download`; My creations search finds it by title and words (kind `lipsync`) |

**Consent and the mark (ADR-0044, ADR-0066 decision 8).** Before anything is made the person says **what the picture
is** (a drawing, a picture of themselves, a picture of someone who agreed) and **whose voice it is** (made here from
words, their own, one they have permission to use). Without both answers the run is refused before any work is done;
"made here from words" is only accepted for words, or a speech made here, never for a recording of the library.
The answers and their wording are kept with the clip. Every video carries a visible **"AI-generated"** label on a
dark plate in the bottom-left corner of every frame, drawn by the server, and a metadata comment; the descriptor
must say `mark: required` or it does not load, and there is no switch. The system safeguards of ADR-0047 (classifier,
moderation, daily limit) are not part of the desktop; consent and the mark are.

Not built: other lip sync models (InfiniteTalk, LivePortrait, the CUDA `liveavatar`), video as the input, moving
the head (MuseTalk redraws the mouth and keeps the head still), several faces, a CUDA lock for Windows and Linux, and
languages: nothing was tested beyond English.

### Dubbing (stage V6)

A recording said again in another language. It uses what is already there (no new model): the separator, the speech
to text model, the chat model, a speaking or copying model, and ffmpeg. Two steps, so the translation can be read and
changed before anything is spoken.

| Step | What happens |
|---|---|
| The script (`dub_script`) | the voice is separated from the background (Mel-Band RoFormer by default; both parts are kept in Your music), what is said is written down with times (Parakeet), and each line is translated by the chat model, in batches of 40 with a length hint per line, a line at a time where a batch does not come back as the right number of lines. The result is a list of lines: start, end, what was said, what it becomes |
| The dub (`dub`) | each line (as the person left it) is spoken, fitted to its time (played up to 1.3 times faster if it runs over; the largest overrun is reported), and mixed with ffmpeg over the background at its time into a 44.1 kHz stereo track |
| The voice | the **original speaker's**, copied from the longest stretch of the separated voice that the model takes (needs the person's word that it is theirs or that they have permission; kept with the track), a **saved** voice (a cloned one, or a designed one), or a **built-in** voice (only for a language the model has voices in) |
| The languages | the ones a speaking or copying model on this computer knows, from the descriptors; today English (Kokoro, built-in voices), and English, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Spanish and Italian (Qwen3-TTS, copying a voice). Writing down the original needs the speech to text model's languages (25 European ones) |
| The track | `mode: dubbed`, `parent_id`, the script, the language, the fit and the consent in its `edit` record; its translated words are searchable |

Needs ffmpeg on the computer (the dub says so in words when it is missing). One speaker only: the lines of two
voices would be spoken in one. Not built: telling speakers apart, lip sync of the dubbed voice (use Lip sync on the
result), sound effects kept separate from music, and a video as the source (a recording's audio only).

### Audiobook (stage V7)

A long text read aloud, chapter by chapter. No new model: any speaking model, with a built-in voice, a designed voice
or a cloned one.

| Step | What happens |
|---|---|
| The chapters | `POST /audiobook/plan` finds them at headings (`Chapter 3`, `CHAPTER ONE: ...`, `# Title`, `Part II`, `Prologue`, `1. Title`), else cuts the text between paragraphs into parts of about 6 000 characters; nothing is made or kept. The person reads them, renames, edits the words, joins a chapter with the next or removes one. A text is at most 400 000 characters, a chapter 60 000, a book 200 chapters |
| Speaking | each chapter is cut into pieces of at most 700 characters at sentence ends (Chinese and Japanese stops too), spoken one at a time and joined with 0.25 s between pieces and 0.7 s after a paragraph; the title is spoken first (it can be left out) |
| Keeping | **each chapter is a track the moment it is done** (`mode: chapter`, the words in `lyrics`, so a book is found by what it says); a failure or a cancel leaves the earlier chapters and the message says which; optionally one track of the whole book (`mode: audiobook`) for books up to about 100 000 characters, which is about two hours, because it is joined in memory |
| The window | Voice > Audiobook: the title, the text (pasted or a `.txt` or `.md` file), the chapters, the voice (a built-in one with the model's own options such as speed, or a saved one), the progress by chapter and part, Cancel |

Not built: chapter markers inside the whole-book file, MP3 or M4A in one go (save each track in Your music), reading
from the notebooks' sources, several voices in one book, and pronunciation notes.

## Video (stage V8)

A short clip from words, or from a picture and what should move. The product already existed for the web
(`products/wasifyai-video`, ADR-0037); the desktop serves it with a small, quick model, on the image engine's
ComfyUI, with no new service.

| Piece | What |
|---|---|
| The model | **LTX-Video 2B 0.9.5** (OpenRAIL-M; later LTX weights need a paid licence above USD 10M revenue, so this one stays pinned). Two files, 16.1 GB: the checkpoint (6.3 GB) and the T5-XXL text encoder (9.8 GB), listed in `products/wasifyai-video/models.yaml` with sizes and SHA-256 like every model, fetched from Models after the person has seen them |
| Speed, measured on a 64 GB Apple-silicon Mac (ComfyUI 0.40, half precision) | 2 s clip (49 frames, 768x512, 30 steps) **72 s**; 5 s clip (121 frames) **252 s**; 25 frames at 512x320 and 15 steps 13 s. Through the app's engine, a 2 s clip from text took 86 s including loading the model and a 2 s clip from a picture 58 s. Peak memory about 13 GB (`approx_ram_gb: 14`), which is what the "will it fit" check uses (a video job is judged by the video models, an image job by the image models) |
| Precision | half precision on the Mac's GPU now gives the same picture as the fp32 setting ADR-0037 needed (34 s against 13 s at the small size), so the engine starts ComfyUI with no extra arguments; the `scripts/comfyui-video.sh` second server is for the web only |
| The engine | the product runs as on the web: the graph checks the request, starts a `video.generate` or `video.animate` job, the same in-process worker and ComfyUI sidecar as images run it, a still from the first frame is made with ffmpeg (`imageio-ffmpeg`), the clip is saved, indexed and counted. Clips live in the `videos` table of `wasifyai.db` (`SqliteVideoStore`, created on first use; a clip that stays "working" for 90 minutes is marked failed), and `video_index_source` serves My creations search. One clip at a time per person |
| Routes | `/products/wasifyai-video/runs`, `GET /videos` (`status`, `ids`), `GET/DELETE /videos/{id}`, `/videos/{id}/download`, and `POST /videos/{id}/export` (copies the MP4 to `~/Downloads` or `WASIFYAI_EXPORT_DIR`, never overwrites, as for images) |
| The window | Video > Create (`#/video/create`), Animate an image (`#/video/animate`), Extend video (`#/video/extend`), Your videos (`#/video/library`): `VideoWorkspace`, `ExtendForm` and `VideoLibrary` in `packages/ui`, `createVideosApi` and `videoFlowReducer` in `packages/client`. The page shows the model and whether it is on the computer, the fit, and the same notices as Create (placeholder clips until the image engine is set up, the model missing, tight memory). The result is a player with Save a copy; a clip being made carries on if the person leaves the screen and shows as "Being made" in Your videos |

Found while building this: My creations search failed (an error response) for any hit that was a music track or a
saved voice, because the voice product indexes those two kinds and the search vocabulary did not list them. They are
listed now (`track`, `voice`), and `/creations/search` is tested with each.

**Extend video (2026-10-21, `docs/spikes/video-extend-vx0.md`).** The last 9 frames of one of the person's clips start a new 49 frame clip (`ltx-video-2b-extend`: `LoadVideo`, `GetVideoComponents`, `ImageFromBatch`, `LTXVImgToVideo` with the 9 frames as its image batch), and the graph joins the old clip up to those frames with the whole new one using ffmpeg (`join_clips`, frame exact), so each round adds 40 frames (1.7 s). The result is a new clip (`mode` `extend`) beside the original. The worker reads a job's inputs only from the person's uploads, so the graph puts a temporary copy of the source at `uploads/extend-<id>.mp4` (a new `video` input slot, `PICTURE_SLOTS`) and deletes it on every exit. There is no limit on the length of the clip (owner, 2026-10-21): the part that is added is 5 or 8 seconds (121 or 193 frames, nine of them repeated), and clips are 5 or 8 seconds (ADR-0037, amendment). Action `video.extend` (`video_id`, `prompt`), screen `#/video/extend` (`ExtendForm`: choose a finished clip, the words fill in from its own). The words steer only weakly: the movement of the last second carries on, and the picture softens each round. **Adding a video (2026-10-21):** the screen also takes a video file from the person's computer (`POST /products/wasifyai-video/videos/import`, a multipart file of at most 200 MB): ffmpeg decodes it and makes it H.264 at 24 frames a second, a multiple of 32 on each side with the longer side at most 768, no sound, no tags, at most 30 seconds, then it is a clip of the library with `mode` `import` (searchable, shown as "Added from your computer"). Its last frame is checked like an uploaded picture (ADR-0047), and only its last second goes to the engine (the engine holds every frame it is given in memory). Not built: Extend from a card in Your videos, dropping a file on the screen, the web version of the screen, a longer or shorter extension, audio.

Not built: other video models (LTX's distilled 2B, Wan, CogVideoX:
each needs its licence and a measurement first), a smaller text encoder (the 8-bit T5-XXL is about 5 GB and would cut the
download by a third; its effect on the picture is not measured), sound for clips, clips longer than 5 seconds, and checking the
finished clip (the known gap of images too).

## Video Builder (ADR-0077, stages V1a to V1c and MG1; experimental)

Videos written as an HTML page and drawn frame by frame on this computer, in a locked box. It is always in the
menu, as **Video › Video Builder**; the screen says it is experimental. Details and measurements: `docs/spikes/video-builder-v1.md`.

| Piece | What |
|---|---|
| The component | `<app data>/components/video-builder/`: a pinned Node.js 22.23.1, the pinned Chrome headless shell 152.0.7977.30 and the 130 npm packages of a lock (`hyperframes` 0.8.171, `gsap` 3.15.0, the two font packages, and FFmpeg 4.4 with ffprobe 4.4.1 from `@ffmpeg-installer` and `@ffprobe-installer`). **318 MB** (288 MB before the fonts and FFmpeg) is shown before the click, about 580 MB on disk, 25 s to set up here. `GET /desktop/video-builder`, `POST /install` (the size shown must be sent back), `POST /uninstall`. Apple-silicon Macs only: elsewhere the screen says so |
| The sandbox | `video_builder_sandbox.py`: a launcher the render starts instead of the browser (drops `--no-sandbox` and popups allowed, refuses to start without the filter), a loopback proxy that forwards to the render's own file server only, a guard (wall, stall, memory limits, process-tree kill), a lint before the compiler |
| The product | inside the video product (`wasifyai_video/builder/`): templates, `builder.db` (compositions and render rows) in `<app data>/video-builder/`, project folders, the render manager (one at a time, a fit check first), routes under `/products/wasifyai-video/builder/` |
| What it makes | a **clip of Your videos** (a `videos` row with `mode = "composition"`, the same storage layout), so the library, export, search and delete already work. A project (a composition) is its own kind in the library and in search |
| The templates | **Animated title, quote, bar chart (from CSV lines), lower third, captions**: typed fields, a shape, a length, four preset looks, Inter or Source Serif 4 (shipped, OFL). The words are escaped text in the page, never markup. A lower third and captions are transparent (WebM alpha, ProRes 4444 MOV, or MP4) |
| The prompt box | the screen opens on "What should we make?": a description (and perhaps a CSV file and a shape) is read by the chosen chat model into a template and its fields, with `POST /builder/draft`; nothing is saved, the form opens filled in and is checked by the person. Two small questions to the model (which template, then its fields); words in quotes must come back exactly; CSV rows never pass through the model |
| The exact-text check | before anything is drawn the page is opened in the sandboxed browser and each word on the screen is compared with what was typed (text, visible, drawn, not cut off, inside the safe margin); a failure is said in words and nothing is made. `POST /builder/projects/{id}/check` runs it alone |
| Actions | `motion.make` (write, check and make in one step), `motion.revise`, `video_builder.create`, `video_builder.lint`, `video_builder.render` (help files in `docs/help/`); `library.*` reaches the `composition` kind. Every change keeps a version; Undo brings the last back (20 kept) |
| Measured here (M5 Pro, 64 GB) | a 5 s 720p title: preview 4.3 s, video 7 to 9 s; 12 s at 1080x1080: 8 s; the render holds about 2.3 GB (`ps` of its process tree); cancel stops it in 1.3 s with nothing left running |

Measured with MG1: each template 7 to 10 s at 720p, tree peak 2.2 to 2.3 GB. Lengths are 3 to 90 seconds (30 by default): a 90 second video draws in 14 to 33 s with the same 2.0 to 2.3 GB.

Not built: the moderation of the words when safeguards are on (ADR-0079 decision 9), a card for projects in a web `/creations` page
(the feature is desktop only), the quarantine check inside the packaged app, the chat path (needs A2), a looping preview clip.

## 3D models (ADR-0080, stages TD1 and TD2; experimental)

A 3D model made from a picture, or from words through a picture, on this computer. It is always in the
menu, as **3D model** (its own item after Motion graphics since 2026-10-24); the screen says it is experimental. Details and measurements: `docs/spikes/pixal3d-td1.md`.

| Piece | What |
|---|---|
| The component | `<app data>/components/model3d/`: the pinned `pixal3d.cpp` Metal build (`trellis-cli`), the Pixal3D single-view Q8_0 weights with the DINOv3 encoder and the BiRefNet cut-out model, **8.98 GB** shown before the click, resumable and hash-checked. `GET /desktop/model3d`, `POST /install` (the size shown must be sent back), `/install/cancel`, `/uninstall`. Apple-silicon Macs only |
| The engine | `desktop_model3d.py`: one process of `trellis-cli` per run (the cut-out, then the 3D run); progress from its output, cancel by killing the process group, the one big-model slot held while it works; about 19 GB of memory, 5 to 25 minutes |
| The product | `products/wasifyai-model3d`: pictures and models in `<app data>/model3d/model3d.db` and files beside it, one job at a time, routes under `/products/wasifyai-model3d/m3d`; a model is the creation kind `model3d` (search, library, rename, save a copy) |
| The screen | start from a picture or from words (four candidates from the image engine), the picture checks in words and the cut-out, Light / Standard / Detailed, progress with stages, a viewer (`<model-viewer>`), Save a copy (GLB), Make it again |
| Licence | "Built with DINOv3" on the setup card, the screen and each model; Meta's agreement and pixal3d.cpp's licence and notice travel with the files |

Not built: four photos around an object, a turntable video, 50k and 200k face targets, our own CI build of the binary, the web version.

## The self-test

`WASIFYAI_SMOKE=1 cargo run` (in `apps/desktop/src-tauri`) starts the shell as usual; once the engine is ready
the window opens the Create screen (`#/images/create`), types a prompt, presses Generate, favourites the result, reads its seed, presses "Make it again" and expects the same seed and size, waits for the picture to load from the
engine's signed link, and the shell prints `SMOKE PASS ...` and exits 0 (`SMOKE FAIL ...` and 1 otherwise).
It drives the real DOM in the real webview, so CORS, the content security policy and the file link are all
exercised. It needs the engine environment (`.venv`).

## What is not done

- **Gallery extras.** Collections, tags and bulk actions are not built; the model id is not in the recipe yet.
- **Menu entries marked "Soon"**: Train; Projects and
  Recents (they need the assistant and projects, ADR-0057). The home "Ask anything" box does not answer.
- **Other screens** (music, speech, ...) still live in `apps/web`; the image and video screens are shared (`packages/ui`).
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
