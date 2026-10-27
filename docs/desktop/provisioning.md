# Provisioning and components on the desktop

Part of [the desktop profile](../desktop-profile.md): what is built, how it is wired, what is not done.

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
| `DESKTOP_SECRET_STORE` | `keychain` (the shell sets it: keys and tokens go to the macOS keychain, the Windows Credential Manager or the Linux Secret Service under "Wasify AI", with the encrypted file where none is reachable) or `file` (the default when the engine is started by hand: `secrets.json`, Fernet under `secrets.key`); ADR-0092 |

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
