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

## The areas, one page each

The rest of what is built on the desktop is one page per area under `docs/desktop/`:

- [Provisioning and components](desktop/provisioning.md)
- [The image screens](desktop/images.md)
- [Models, the language engine and the hub](desktop/models.md)
- [The assistant](desktop/assistant.md)
- [Notebooks](desktop/notebooks.md)
- [Speech, music, lip sync, dubbing and audiobooks](desktop/voice.md)
- [Video and Video Builder](desktop/video.md)
- [3D models](desktop/model3d.md)
- [Other apps: the MCP server and the launcher](desktop/connections.md)

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
| Models, Settings | `pages/Models.tsx`, `pages/Settings.tsx` | the model panel; the image engine card, updates, restart and repair; "Searching the web" (`SearchSettings` in `packages/ui`: service, permission, key; the engine side is `web_search.py`, keys in the secret store, ADR-0083 and ADR-0092); "Hugging Face token" (`HubToken`: typed once, kept in the keychain, never shown again; `PUT`/`DELETE /desktop/hub/token`) |

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

> Since stage U2 of the UI plan (2026-10-27, ADR-0093) the menu shows eleven entries with no groups to open; a product's
> modes are tabs in the top bar. The groups below are still the list of item ids (`MENU_GROUPS`); what the menu shows is
> `MENU_ENTRIES` in `packages/ui/src/shell/menu.ts`.

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
