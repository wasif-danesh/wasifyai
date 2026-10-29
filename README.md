# Wasify AI

Wasify AI is an AI app you run on your own computer, and a web twin of it. A **chat assistant** is the home
screen; beside it are **images**, **video**, **voice** (text to speech, speech to text, music, dubbing,
audiobooks, lip sync) and **notebooks** (chat with your own documents). Everything you make lands in one
library, **My creations**, searchable by meaning in any language.

Under it is a reusable **platform core** (the repository is called `wasifyai`): an API with streaming, a
stateful agent runtime, a model gateway, media workers, storage, auth and monitoring. Each **product** is a
thin layer on top: a few LangGraph graphs, a config file and a screen.

> **Status (2026-10-20): v1 in progress, desktop first.** The desktop app (a Tauri window that starts the engine on
> your computer) is the main target: Mac first, image first, English first. The same screens run as a web app
> against the same engine in containers. This week the chat gained **edit and versions of a message**,
> **cards that ask before the assistant makes something**, **file attachments** (pictures and documents), **web
> search**, **Thinking**, **Mic dictation** and **read aloud**, and the **notebook chat** moved onto the same
> chat engine. These are being tested by hand in the real window before anything new starts; next after that is
> a simpler way to choose models. See the [roadmap](docs/roadmap.md).

## Contents

- [What it looks like](#what-it-looks-like)
- [What the chat can do](#what-the-chat-can-do)
- [How it works](#how-it-works)
- [Products](#products)
- [Run the desktop app](#run-the-desktop-app)
- [Run the web app](#run-the-web-app) (including [what to install first](#before-you-start-manual-prerequisites))
- [Monitoring](#monitoring)
- [Using the API](#using-the-api)
- [Project layout](#project-layout)
- [Configuration](#configuration)
- [Development](#development)
- [Environments](#environments)
- [Documentation](#documentation)
- [Principles](#principles)
- [Roadmap](#roadmap)

## What it looks like

The pictures below are the shared screens (the desktop window and the web app draw the same ones), taken from the
web app against its test engine, so they show sample data. `README_SHOTS=1 pnpm --filter web exec playwright test
e2e/readme-screens.spec.ts --project=desktop-light` makes them again.

![Home: the assistant, with the options under the box: Attach, Thinking, Search and Mic](docs/images/screens/home.png)

| A chat: a picture and a file attached, sources from the web, two versions of an answer | The assistant asks before it makes something |
|---|---|
| ![A chat with attachments, web sources and a version picker](docs/images/screens/chat.png) | ![A card that asks before making a picture](docs/images/screens/card.png) |

| Files waiting in the box | On a phone |
|---|---|
| ![A picture and a PDF waiting to be sent](docs/images/screens/attach.png) | ![A chat on a phone, dark theme](docs/images/screens/phone.png) |

| Notebooks: chat with your sources, citations, a Studio of outputs | Images |
|---|---|
| ![A notebook with its chat, citation pills and the Studio](docs/images/screens/notebook-chat.png) | ![Create images](docs/images/screens/images.png) |

| Video | Voice (text to speech) |
|---|---|
| ![Make a video](docs/images/screens/video.png) | ![Text to speech](docs/images/screens/voice.png) |

| Music | Notebooks |
|---|---|
| ![Create music](docs/images/screens/music.png) | ![Your notebooks](docs/images/screens/notebooks.png) |

## What the chat can do

| | |
|---|---|
| **Ask anything** | Answers stream in, with code, maths and diagrams; Stop and Try again; a conversation is kept and found again from Recents and from search. |
| **Make things** | "Draw a red teapot" or "make a song" runs the image or music product and shows the result in the chat. |
| **Edit and versions** | Edit a message of yours or press Answer again: the old version stays, and "2 / 3" arrows move between versions. The version you leave on screen is the one you come back to. |
| **Cards that ask first** | After the assistant has read the web or a file you attached, anything it wants to make or change waits for your Go ahead; it cannot be talked into it by text it read. |
| **Attach** | Pictures (the model needs its picture reader; the app offers it, with the size, and downloads only after you click) and documents (text, Markdown, CSV, HTML; PDF and Office with the document reader). Drag, paste or pick. |
| **Search** | Off until you allow it. DuckDuckGo needs no account; Ollama, Tavily, Exa or Brave Search work with your own key. Sources are shown and open in your browser. |
| **Thinking** | For models that can think: it shows its thinking, collapsed, and says it takes longer. Off by default. |
| **Mic** | Press, speak, press again: your words land in the box. A speech model runs on your computer; audio is not kept. |
| **Read aloud** | A button on each reply speaks it with a voice that runs on your computer. Nothing is saved. |
| **Notebooks** | Chat with your own documents: citations you can open, a Studio for reports, study guides, decks and more. |

The chat is built on assistant-ui (edit, versions, code, maths and diagrams in answers, approval cards).
Design: [ADR-0082](docs/decisions/0082-chat-ui-on-assistant-ui.md) (the chat) and
[ADR-0083](docs/decisions/0083-composer-options-attach-search-thinking-mic.md) (the options under the box).

## How it works

```
Browser ─► Next.js (UI + BFF) ─► FastAPI + LangGraph ─► LiteLLM ─► Ollama / vLLM
                                        │
                                        ├─► Postgres (pgvector, checkpoints, jobs)
                                        ├─► Redis (job queue, pub/sub) ─► Media worker ───► ComfyUI (images, video)
                                        └─► Object storage (SeaweedFS / S3 / GCS / Azure Blob)

Prometheus, Alertmanager, Grafana and Loki watch all of it and alert to Telegram.
```

That is the **web profile**. The **desktop profile** runs the same engine with the same products and screens, with
the web's services replaced by local ones behind the same interfaces:

```
Tauri window (packages/ui) ─► engine on 127.0.0.1 (FastAPI + LangGraph, a token per launch)
                                   ├─► SQLite (records, checkpoints, run events, job queue)
                                   ├─► a folder of files (links signed per launch)
                                   ├─► llama-server (the chat model, `--mmproj` for pictures) or Ollama / LM Studio
                                   ├─► audio.cpp (speech, music, dubbing) and ComfyUI / the image engine, on demand
                                   └─► the notebooks' document reader (a separate process), on demand
```

Product code never asks which profile it runs in ([desktop profile](docs/desktop-profile.md)). The chat screens live
in `packages/ui` and talk to the engine through `packages/client`, so the web app and the window share them.

1. The browser talks only to the **Next.js** app, which handles sign-in (Auth.js). Its route
   handlers (the BFF) check the session, attach a short-lived signed token, proxy to the API and
   pass the event stream through unchanged.
2. **FastAPI** runs the product's **LangGraph** graph and streams progress to the browser as
   Server-Sent Events: node status, tokens, interrupts, job progress, and a final result.
3. Graphs ask for **capabilities** (`text.chat`, `image.generate`, `video.generate`), never for specific models. Config binds each capability to a provider.
4. Text goes through **LiteLLM**, an OpenAI-compatible gateway that maps aliases to Ollama
   (dev, staging) or vLLM / hosted APIs (prod).
5. Slow work (images, video) is never awaited inline. The graph enqueues a job in
   **Redis**, a **media worker** drives ComfyUI, and the graph resumes when the
   job finishes.
6. Graph state is checkpointed in **Postgres**, so a run can pause for user input and resume.
7. Nothing a person makes is moderated, marked or limited per day
   ([ADR-0094](docs/decisions/0094-no-safeguards-marks-or-licence-data-in-v1.md)).

## Products

| Product | What it does |
|---|---|
| [`wasifyai-assistant`](products/wasifyai-assistant/) | The chat: conversations with a tree of message versions, tools that make things, cards that ask first, attachments, web search, Thinking |
| [`wasifyai-image`](products/wasifyai-image/README.md) | Text to image and image to image (FLUX.2 klein 4B on the web; the desktop image engine) |
| [`wasifyai-video`](products/wasifyai-video/README.md) | Text to video and image to video, 2 or 5 seconds (LTX-Video 2B), made in the background |
| [`wasifyai-voice`](products/wasifyai-voice/README.md) | Text to speech, speech to text (and Mic dictation), music, audio tools, dubbing, audiobooks, lip sync, read aloud |
| [`wasifyai-notebooks`](products/wasifyai-notebooks/) | Chat with your own documents: sources, citations, a Studio of outputs |

A product is a folder under `products/` with its `product.yaml`, graphs, prompts and ComfyUI
workflows. Adding a product adds no API endpoints: the graph registry exposes registered
graphs through the same generic routes.

## Run the desktop app

The desktop app is a small Rust shell ([Tauri 2](https://tauri.app)) that starts the engine (`services/api` in its
desktop profile: SQLite, local files, a worker in the same process) and shows the window. Nothing listens on the
network: the engine binds `127.0.0.1` and every call carries a token the shell made for that launch.

**You need** (macOS is the tested platform): Homebrew, Apple's command line tools (`xcode-select --install`), and
the Rust toolchain 1.89 or newer ([rustup](https://rustup.rs)). `make setup` installs the rest (`uv`, Node 22,
`pnpm`) and the Python environment; it does not install Rust. About 15 GB of free disk and 16 GB of memory are
comfortable for the default chat model (Qwen3.5 9B: about 5.7 GB to get, about 7 GB in memory). Windows and Linux
are built and tested by CI but have not been used by hand.

```bash
git clone https://github.com/wasif-danesh/wasifyai.git && cd wasifyai
make setup                                  # tools and the Python environment (.venv)
pnpm --filter @wasifyai/desktop build       # the window's files (apps/desktop/dist)
cd apps/desktop/src-tauri && cargo run      # the shell; it starts the engine from .venv
```

(After the first build, `touch build.rs` before `cargo run` if you change `Info.plist`: macOS reads the microphone
text from it.) The window can also run on its own against a running engine: `pnpm --filter @wasifyai/desktop dev`
(http://localhost:1420). A packaged, unsigned app with the engine bundle inside:
`make engine-bundle && pnpm exec tauri build --config src-tauri/tauri.bundle.conf.json --bundles app`
(run in `apps/desktop`).

**The first time**

1. The window opens on the assistant. In **Settings**, set up the **language engine** (it installs the model
   runner, with the size shown) or, if you use Ollama or LM Studio, pick one of their models.
2. In **Models**, under *Found on this computer* or *Discover*, choose a chat model. Qwen3.5 9B is the one the
   assistant is tuned for and the one with a picture reader.
3. Ask something. Optional extras, each with its size shown and downloaded only when you click: the image engine
   (Settings), a speech model for Mic and Read aloud, the picture reader (the first time you attach a picture), the
   document reader for PDF and Office files (the first time you add one to a notebook).

Your data (database, files, models you fetched, logs) lives in the app data folder: on macOS
`~/Library/Application Support/ai.wasifyai.desktop` (`logs/engine.log` is the first place to look when something
fails). More: [desktop profile](docs/desktop-profile.md), [apps/desktop](apps/desktop/README.md). **Testing it by
hand:** [desktop window checklist](docs/testing/desktop-window-checklist.md).

## Run the web app

The same screens as a web app, with the engine in containers (Postgres, Redis, object storage, the model gateway,
a media worker):

Do the [one-time prerequisites](#before-you-start-manual-prerequisites) for your platform, then
two commands do everything else:

```bash
git clone https://github.com/wasif-danesh/wasifyai.git && cd wasifyai
make setup      # installs missing tools, starts Podman + Ollama, pulls the model, creates .env
make dev        # starts the stack, waits for Postgres, runs migrations, follows logs
```

Then open http://localhost:3000, choose a product and make something. GPU media (images, video) are
placeholders by default; set `COMFYUI_MODE=real` in `.env` and run ComfyUI with the models for real ones (see
[Hardware notes](#hardware-notes)). Music, speech and lip sync are the voice product: hosted models through the
gateway, or the models on this machine (`scripts/web-local.sh`, [runbook](docs/runbooks/web-notebooks-voice.md)).

Sign-in is off by default (`AUTH_MODE=stub` in `.env.example`: everyone is the dev user). To turn it on,
set `AUTH_MODE=jwt`, the two secrets and a provider's client id and secret: see
[Sign-in in apps/web](apps/web/README.md#sign-in).

If `make` is not installed yet (common on a fresh Linux box), run the script directly. It
installs `make` for you: `./scripts/setup.sh`, then `make dev`.

### Before you start (manual prerequisites)

`make setup` installs almost everything, but a few things must exist first because they need
administrator rights, a reboot, or are needed to run the setup at all. Do these once.

**Every platform**

- An internet connection, and about 15 GB of free disk (the default model is about 10 GB).
- 8 GB of RAM or more for the default `gemma4:e4b` model (16 GB is more comfortable). With less, switch to a smaller model
  (see [Hardware notes](#hardware-notes)).
- A GPU is optional. Apple Silicon (Metal) and NVIDIA GPUs speed up replies; CPU-only works but
  is slow.

**macOS**

1. Install [Homebrew](https://brew.sh).
2. Install Apple's command line tools (they provide `git` and `make`): `xcode-select --install`.

**Linux** (Debian, Ubuntu, Kali, Fedora, Arch and derivatives)

1. Use a distro with `apt`, `dnf` or `pacman`, and an account with `sudo`.
2. Install `git` (for example `sudo apt install git`). `make`, `curl` and `openssl` are installed
   by setup if missing.
3. For the local Kubernetes cluster only (`make kind-up`) with rootless Podman, enable cgroup
   delegation once: [runbooks/linux-kind.md](docs/runbooks/linux-kind.md).

**Windows 10 (22H2) or 11**: use WSL2 with Ubuntu. Native PowerShell and cmd are not supported.

1. Turn on hardware virtualisation in the BIOS/UEFI, and use an administrator account.
2. From an elevated PowerShell, run `wsl --install -d Ubuntu-24.04`, reboot if asked, and finish
   the Ubuntu first-run user setup.
3. Optional but recommended: enable systemd in Ubuntu (`printf '[boot]\nsystemd=true\n' | sudo tee /etc/wsl.conf`),
   then run `wsl --shutdown` from PowerShell and reopen Ubuntu.
4. For GPU acceleration, install a current NVIDIA driver on **Windows**, not inside Linux.
5. Clone the repo inside Ubuntu's own filesystem (`~`), not under `/mnt/c`, then follow the Linux
   steps above.

Details and tips: [docs/windows.md](docs/windows.md).

### Supported platforms

| Platform | Status |
|---|---|
| macOS (Apple Silicon and Intel) | Supported; Homebrew and Xcode command line tools required first |
| Linux: Debian, Ubuntu, Kali (apt), Fedora (dnf), Arch (pacman) | Supported; the tool installation is tested in Ubuntu and Fedora containers and in CI. Engine, Ollama and model steps are tested on macOS only |
| Windows 10/11 | Supported **through WSL2** (Ubuntu); see [docs/windows.md](docs/windows.md). Not yet tested on a real Windows machine |

### What `make setup` does

It is idempotent (safe to re-run) and asks before every install or large download. Add `-y`
(`./scripts/setup.sh -y`) to accept everything without prompts. `make setup-k8s` does the same
and also installs `kind`, `helm` and `kubectl`.

1. Checks for `podman`, `uv`, `pnpm`, Node 22+, `ollama`, `curl`, `git`, `make`, `openssl` and a
   Compose provider, and installs what is missing:
   - **macOS:** Homebrew.
   - **Linux and WSL:** the distro package manager for system tools (`podman`, `git`, ...), plus
     official installers for the rest: `uv` and Ollama use their vendors' install scripts, and
     Node 22, `kind`, `helm` and `kubectl` are downloaded as binaries and **checksum-verified**
     into `~/.local/bin`. pnpm comes from Corepack. No Homebrew or sudo is needed for those.
2. Creates and starts the Podman VM on macOS, and checks it has enough memory (offers to resize).
3. Starts Ollama and pulls every model named in `services/api/src/wasifyai_api/model_defaults.yaml`
   (`gemma4:e4b`, about 10 GB, plus `nomic-embed-text` and the multilingual `bge-m3`, about 1.5 GB together). On Linux it also checks that containers can reach Ollama and
   offers a fix if not.
4. Creates `.env` from `.env.example` and generates random secrets. Nothing is printed.
5. Runs `uv sync --all-packages` and `pnpm install`.

Anything it cannot do for you is listed under
[Before you start](#before-you-start-manual-prerequisites); the script stops with a message if
something is missing.

`make dev` runs `make preflight` first: a fast, read-only check that lists exactly what is
missing and points back to `make setup`.

### Hardware notes

- `gemma4:e4b` needs about 8 GB of RAM and 15 GB of free disk. Setup warns when a machine is
  short. To use a smaller or faster model, change the `ollama_chat/...` entries in
  `services/api/src/wasifyai_api/model_defaults.yaml` (or switch a model at run time in `/admin/models`); setup and
  preflight read the model names from that file.
- Text to speech runs on the CPU in containers. English, Spanish, French, Hindi, Italian and Portuguese use
  Kokoro (small). **Bengali** uses Indic Parler-TTS, which needs about 4.5 GB of memory on its own and runs
  about five times slower than real time on a CPU, so give the Podman VM about **12 GB** (`podman machine set
  --memory 12288`). Its model is gated: accept the terms on its Hugging Face page and put a read token in
  `.env` as `HF_TOKEN`.
- The lip sync server (MuseTalk) runs natively on the Mac so it can use the Apple GPU: about 12 GB of memory
  and 5 seconds of compute per second of video. `make dev` starts and `make down` stops it.
- Ollama runs natively on the host so it can use the GPU. On Apple Silicon it uses Metal. On
  Intel Macs and machines without a supported GPU it runs on CPU, so replies are slow.
- Linux and WSL: Ollama listens on `127.0.0.1` by default, which containers may not reach.
  `make setup` tests this and, with your consent, makes Ollama listen on `0.0.0.0`. Ollama has no
  authentication, so restrict port 11434 with a host firewall.

### Services

| Service | URL |
|---|---|
| Web (Next.js) | http://localhost:3000 |
| API (FastAPI) | http://localhost:8000 (`/health`, `/docs`) |
| LiteLLM | http://localhost:4000 |
| Object storage (S3 API) | http://localhost:8333 |
| Postgres / Redis | `localhost:5432` / `localhost:6379` |

`make logs` follows container logs, and `make down` stops everything.

### Run on Kubernetes (kind)

Runs the same Helm chart used for staging, on a local cluster. `make setup-k8s` installs `kind`, `helm` and
`kubectl`. On Linux with rootless Podman see [runbooks/linux-kind.md](docs/runbooks/linux-kind.md).

```bash
make down         # the Compose stack and kind both use localhost:3000
make kind-up      # builds images, creates the cluster, installs the chart and the monitoring stack
make kind-test    # smoke test: migrations, every product's pages and APIs, the pods that replace native services
make kind-e2e     # makes something with each of the six products
make kind-down    # delete the cluster
```

The default `KIND_MODE=full` runs **every service as a pod, nothing native**: Ollama with its models and ComfyUI, plus Prometheus, Alertmanager, Grafana and Loki. It needs a
Podman VM of about 24 GB of memory and 100 GB of disk (`podman machine set --memory 32768 --disk-size 160`) and
downloads about 20 GB of models on the first start. There is no GPU in the cluster, so GPU media (images,
video) are placeholders, apart from one model-free ComfyUI graph the smoke test runs for real. `KIND_MODE=light`
is what CI runs: no models. Home lab setup with k3s and
Argo CD: [runbook](docs/runbooks/homelab-k3s.md).

### Where everything is

`make urls` prints this for the mode that is running and says what answers right now.

<!-- urls:start -->
| Service | What it is | Compose (`make dev`) | kind (`make kind-up`) |
|---|---|---|---|
| Web app | the six products, My creations, admin | `http://localhost:3000` | `http://localhost:3000` |
| Admin area | users, models, media backends, audit | `http://localhost:3000/admin` | `http://localhost:3000/admin` |
| API docs | Swagger UI for the API | `http://localhost:8000/docs` | `kubectl -n wasifyai port-forward svc/wasifyai-api 8000:8000`, then `http://localhost:8000/docs` |
| LiteLLM | the model gateway | `http://localhost:4000` | `kubectl -n wasifyai port-forward svc/wasifyai-litellm 4000:4000`, then `http://localhost:4000` |
| Object storage | S3 API (SeaweedFS) | `http://localhost:8333` | `kubectl -n wasifyai port-forward svc/wasifyai-storage 8333:8333`, then `http://localhost:8333` |
| ComfyUI | images (and video on :8189) | `http://localhost:8188` | `kubectl -n wasifyai port-forward svc/wasifyai-comfyui 8188:8188`, then `http://localhost:8188` |
| Ollama | the language models | `http://localhost:11434` | `kubectl -n wasifyai port-forward svc/wasifyai-ollama 11434:11434`, then `http://localhost:11434` |
| Postgres | database, checkpoints, usage events | `localhost:5432` | `kubectl -n wasifyai port-forward svc/wasifyai-postgres 5432:5432`, then `localhost:5432` |
| Redis | job queue and run events | `localhost:6379` | `kubectl -n wasifyai port-forward svc/wasifyai-redis 6379:6379`, then `localhost:6379` |
| Grafana | dashboards and logs | not installed | `kubectl -n monitoring port-forward svc/monitoring-grafana 3001:80`, then `http://localhost:3001` |
| Prometheus | metrics and alert rules | not installed | `kubectl -n monitoring port-forward svc/monitoring-prometheus 9090:9090`, then `http://localhost:9090` |
| Alertmanager | what is firing, where it goes | not installed | `kubectl -n monitoring port-forward svc/monitoring-alertmanager 9093:9093`, then `http://localhost:9093` |
| Healthchecks.io | the outside heartbeat | not installed | `https://healthchecks.io` |
<!-- urls:end -->

LangGraph has no interface of its own: it runs inside the API. Run state is in Postgres (the checkpoint tables),
the job queue is Redis Streams (`wasifyai:jobs`, `wasifyai:done`), and logs and metrics are in Grafana.

### Monitoring

```bash
make monitoring-up      # Prometheus, Alertmanager, Grafana, Loki; part of make kind-up
make monitoring-drill   # stop the worker and expect an alert on Telegram, then a resolve
make monitoring-drill-meta   # stop Prometheus and expect Healthchecks.io to message you
```

Only production sends: with `ALERT_NOTIFICATIONS=on` alerts go to Telegram (`TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID` in `.env`) and a heartbeat to Healthchecks.io (`HEALTHCHECKS_PING_URL`) tells you when the whole
cluster is down. Everywhere else alerts still show in Alertmanager and Grafana but nothing is sent. Dashboards, alert list and fire drills:
[runbook](docs/runbooks/monitoring.md), [ADR-0048](docs/decisions/0048-monitoring-and-alerting.md).

### Develop with live reload

Start only the backing services, then run the API and web app natively:

```bash
podman compose up -d postgres redis litellm
DATABASE_URL=postgresql+asyncpg://wasifyai:wasifyai@localhost:5432/wasifyai \
  LITELLM_BASE_URL=http://localhost:4000 \
  uv run uvicorn wasifyai_api.main:app --reload --port 8000
API_BASE_URL=http://localhost:8000 pnpm --filter web dev      # in another terminal
```

## Using the API

All routes resolve an identity on every request: a signed token from the web app (`AUTH_MODE=jwt`,
the default) or the dev user (`AUTH_MODE=stub`, set in `.env.example` for local work).
Without a valid token every route except `/health` answers `401`. Responses for runs are `text/event-stream`.

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness check (no identity needed) |
| `POST /products/{product_id}/runs` | Start a run; streams events. Body: `{"input": {...}, "thread_id"?: uuid}` |
| `GET /runs/{run_id}/events` | Reconnect to a run; honours `Last-Event-ID` |
| `POST /runs/{run_id}/resume` | Answer an `interrupt` (approve, edit); continues the stream. Body: `{"value": ...}` |
| `POST /runs/{run_id}/cancel` | Stop a run (the Stop button) |
| `GET /me` | The caller's user id, tenant and role |
| `GET/PATCH/DELETE /products/wasifyai-assistant/conversations[/{id}]` | The assistant's conversations. `GET ...?tree=1` returns every version of every message; `PATCH {head_id}` says which version is on screen. Runs take `parent_message_id`, `regenerate`, `attachments`, `search`, `thinking` and `approvals` ([SSE contract](docs/contracts/sse-events.md)) |
| `GET /products/wasifyai-assistant/options` | What the chat box can offer with the model in use: Thinking, Search, Attach (and the picture reader the app can fetch) |
| `GET/PUT /products/wasifyai-assistant/search` | Web search settings: service, permission, keys (written, never read back) |
| `POST /products/wasifyai-assistant/attachments` | A document for a chat message, read to text on the engine (pictures use the ordinary upload route) |
| `POST /products/wasifyai-voice/dictation` | Mic: a 16 kHz mono WAV in, words out, nothing kept |
| `GET /desktop/vision`, `POST /desktop/vision/download` | Desktop: the chosen model's picture reader, and fetching it after you agreed to the size |
| `GET /admin/media`, `PUT /admin/media/{product}/{capability}`, `POST .../test`, `.../reset` | Admin only: choose which backend runs a product's media capability; keys are write-only |
| `GET /admin/models`, `PUT /admin/models/{alias}`, `POST /admin/models/{alias}/test`, `/reset` | Admin only: see and change which provider and model serve each LiteLLM alias; keys are write-only |
| `GET /admin/users`, `/admin/songs`, `/admin/usage?days=`, `/admin/audit` | Admin only (`403` for others): users, songs from all users, usage totals, the audit log. Listing users is itself audited |
| `POST /products/{id}/uploads/images` (raw image body) | Store the user's picture (re-encoded, metadata-free) and return its key ([ADR-0035](docs/decisions/0035-image-uploads.md)) |
| `GET /creations/search?q=&kind=&limit=` | Search the signed-in user's own creations by meaning and exact words, in any language ([ADR-0041](docs/decisions/0041-semantic-search.md)); every list route also takes `ids=` |
| `POST /products/{id}/prompt/enhance` | Rewrite the user's prompt for the product's model ([ADR-0038](docs/decisions/0038-prompt-enhancement.md)) |
| `DELETE /products/{id}/uploads/images/{upload_id}` | Take back an uploaded picture ([ADR-0039](docs/decisions/0039-picture-input.md)) |
| `GET /products/wasifyai-video/videos`, `GET/DELETE /products/wasifyai-video/videos/{id}`, `.../download` | The signed-in user's clips, including ones still being made ([ADR-0037](docs/decisions/0037-video-product.md)) |
| `GET /products/wasifyai-image/images`, `GET/DELETE /products/wasifyai-image/images/{id}`, `.../download` | The signed-in user's images ([ADR-0036](docs/decisions/0036-image-product.md)) |

Try it without the browser, through the Next.js BFF:

```bash
curl -N -X POST localhost:3000/api/products/hello/runs \
  -H 'content-type: application/json' -d '{"input":{"message":"Say hi"}}'
```

You should see `node`, `token` ... and `done` events. Each message looks like:

```
id: 2
event: token
data: {"run_id":"…","thread_id":"…","seq":2,"ts":"…","node":"hello","text":"Hello"}
```

Event types are `node`, `token`, `interrupt`, `job_progress`, `error` and `done`. Full protocol:
[SSE event contract](docs/contracts/sse-events.md). Interactive docs are at
http://localhost:8000/docs.

## Project layout

```
wasifyai/
├─ apps/web/                 # Next.js app (shadcn/ui, Tailwind, TanStack Table): product UIs, side panel, admin, BFF; Playwright specs in e2e/
├─ apps/desktop/             # the desktop app: Tauri 2 shell (Rust) and the window (Vite + React); AGPL-3.0, see its README
├─ services/
│  ├─ api/                   # FastAPI + LangGraph runtime (graphs, runs, identity, migrations, metrics)
│  ├─ media-worker/          # Redis consumer that drives ComfyUI
│  └─ comfyui/               # ComfyUI container image (CPU by default, CUDA by build argument)
├─ packages/
│  ├─ ui/                    # the screens the web app and the window share (chat on assistant-ui, notebooks, create screens), tokens only
│  ├─ client/                # the typed engine client and the chat state (message tree, run follower)
│  ├─ contracts/             # Pydantic models: SSE events and request bodies (source of truth)
│  ├─ contracts-ts/          # TypeScript types generated from the OpenAPI schema
│  └─ platform-sdk/          # Capabilities, providers, product config, storage, usage, actions, web access, graph registry
├─ products/
│  ├─ hello/, media-demo/    # sample products: config only (used by the smoke tests)
│  ├─ wasifyai-image/           # text to image and image to image
│  ├─ wasifyai-video/           # text to video and image to video
│  ├─ wasifyai-voice/           # speech, music, audio tools, dubbing, audiobook, lip sync (one graph, one store)
│  ├─ wasifyai-notebooks/       # source-grounded notebooks
│  └─ wasifyai-assistant/       # the chat
├─ deploy/
│  ├─ compose/               # LiteLLM config for the local stack
│  ├─ helm/wasifyai/            # Helm chart + values overlays (local, staging, prod, cloud/*)
│  ├─ monitoring/            # values for the monitoring stack and the Alertmanager template
│  ├─ kind/                  # local cluster config
│  └─ argocd/                # Argo CD Application for staging
├─ design/                   # DESIGN.md: the single source of the look (colours, type, spacing), and its themes
├─ scripts/                  # setup, preflight, dev, kind, monitoring, design and chat-bundle helpers
├─ docs/                     # architecture, ADRs, contracts, runbooks, roadmap, spikes, the test checklist
├─ compose.yaml              # local dev stack
└─ Makefile                  # setup, dev, test, lint, contracts, migrate, kind-*, monitoring-*
```

Python packages are snake_case (`wasifyai_api`); folders and URLs are kebab-case.

## Configuration

There are three kinds of configuration, each with one home:

| Kind | Examples | Where |
|---|---|---|
| Secrets | API keys, DB passwords, `AUTH_SECRET`, `API_AUTH_SECRET`, OAuth client secrets | `.env` (gitignored); keys are listed in `.env.example` |
| Environment wiring | `DATABASE_URL`, `LITELLM_BASE_URL`, `OLLAMA_BASE_URL`, `COMFYUI_BASE_URL` | `.env` locally, Helm values on Kubernetes |
| Product config | Model bindings, workflows, quotas | `products/<id>/product.yaml` |

Containers reach Ollama and ComfyUI on the host through `host.containers.internal`, because
containers on macOS cannot use the Metal GPU. Never commit `.env`; the repo and container
builds ignore it. More detail: [Configuration](docs/configuration.md).

## Development

```bash
make test        # Python (no GPU or network needed) + TypeScript tests
make test-integration   # real Postgres/pgvector, Redis pipeline, SeaweedFS, LiteLLM + Ollama (needs make dev)
make test-comfyui       # opt-in: a real image, song and cover on your local ComfyUI (slow first time)
make lint        # ruff, pyright, Biome, tsc
make format      # ruff format + autofix
make contracts   # regenerate TS types from the API's OpenAPI schema
make setup       # one-time machine setup (see Run the desktop app and Run the web app); setup-k8s adds kind/helm/kubectl
make preflight   # read-only readiness check
make dev / down  # start (with migrations) / stop the container stack
make migrate     # alembic upgrade head only (Postgres on localhost)
make helm-lint   # lint and render the chart with every overlay
make kind-up / kind-test / kind-e2e / kind-down   # local Kubernetes (see above)
make monitoring-up / monitoring-drill             # monitoring stack and fire drill
make engine-bundle                                # the files the desktop app installs its engine from
```

The screens and the desktop app:

```bash
pnpm -r typecheck                                  # every TypeScript package
pnpm --filter @wasifyai/ui exec vitest run         # the shared screens (jsdom); also client, web and desktop
pnpm --filter web test:e2e:layout                  # the layout cases in Chromium against the test engine (CI runs these)
pnpm --filter web test:e2e                         # also the screenshot cases (kept per operating system)
pnpm design:check                                  # no hard-coded colours, sizes or radii; contrast of every token pair
pnpm chat:bundle-check                             # the new chat's first screen stays within its size budget
cd apps/desktop/src-tauri && cargo test            # the shell
WASIFYAI_SMOKE=1 cargo run                         # the self-test: make an image in the real window, exit 0 or 1
```

- **Tooling:** Python 3.12 with `uv`, `ruff`, `pyright`, `pytest`, Alembic. TypeScript with
  `pnpm`, Turborepo, Biome, Vitest, Next.js App Router in strict mode. UI: shadcn/ui (Radix) with Tailwind CSS, react-hook-form and Zod for forms, TanStack Table for data grids ([ADR-0045](docs/decisions/0045-ui-components.md)); `apps/web/app/tailwind.css` is the only stylesheet.
- **Contracts:** Pydantic models are the source of truth. Never hand-edit
  `packages/contracts-ts/src/schema.gen.ts`; run `make contracts` (it also writes `docs/contracts/actions.json`, the
  catalogue of everything the app can do).
- **The look:** `design/DESIGN.md` is the only source of colours, type and spacing; screens use tokens, and the lint
  fails on anything hard-coded ([ADR-0081](docs/decisions/0081-design-system-from-design-md.md)).
- **Features are actions:** anything a person or an agent can ask the app to do has an action, a help file and a
  place in the menu ([how to add one](docs/actions.md)).
- **Tests:** graph tests use a fake capability provider, so they need no GPU or network.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org), scoped by area,
  e.g. `feat(api): ...`.
- **Containers:** use `${CONTAINER_ENGINE:-podman}` in scripts, never hard-code an engine.
  Images build for `linux/arm64` and `linux/amd64`.
- **CI:** GitHub Actions runs lint, typecheck and tests, a `setup` job on Ubuntu and macOS, a
  Helm lint and `kind` smoke test, and on `main` builds and pushes multi-arch images.

### Troubleshooting

| Symptom | Fix |
|---|---|
| No reply, or an error on the page | Check Ollama is up and lists the model: `curl localhost:11434/api/tags` |
| LiteLLM exits at start | `podman logs wasifyai-litellm-1`. It needs `LITELLM_API_KEY` set in `.env` |
| Port already in use | `make down`, then try again |
| Slow first reply | The model loads into memory on first use. CPU-only machines are slower; try `gemma4:e2b` |
| Empty reply with a small `max_tokens` | Gemma 4 "thinking" uses the token budget. It is off for the chat and lyrics aliases; keep budgets generous for the `moderator` ([ADR-0018](docs/decisions/0018-default-text-model-gemma4-e4b.md)) |
| Every model call fails with "model not found" right after start | The API seeds the model aliases into LiteLLM when it starts; give it a minute and check `podman logs wasifyai-api-1`. `LITELLM_API_KEY` must match between the API and LiteLLM |
| "API keys can't be saved yet" in `/admin/media` | `MEDIA_SECRETS_KEY` is missing: run `make setup`, then restart the API and the worker |
| `make dev` fails with "LITELLM_SALT_KEY" | Run `make setup`; it generates the key. Never change it afterwards: saved provider keys are encrypted with it |
| `podman compose` cannot connect | Run `podman machine start` |
| `make dev` says "Not ready" | Run `make setup`; it fixes every item the preflight lists |
| Sign-in page says "No sign-in provider is set up" | Set a provider's `AUTH_<PROVIDER>_ID` and `_SECRET` in `.env`, or `AUTH_MODE=stub` for local work |
| Sign-in fails with `redirect_uri_mismatch` or "Server error: problem with the server configuration" | Set `AUTH_URL=http://localhost:3000` and register `http://localhost:3000/api/auth/callback/<provider>` with the provider. In a container the server otherwise reports `0.0.0.0` |
| API refuses to start: "AUTH_MODE=jwt needs API_AUTH_SECRET" | Put the same 32+ byte `API_AUTH_SECRET` (`openssl rand -hex 32`) in the API and web environment, or set `AUTH_MODE=stub` |
| Desktop: `cargo run` says the Rust version is too old | Update the toolchain: `rustup update` (the shell needs 1.89 or newer) |
| Desktop: the window opens but says the engine did not start | Open `~/Library/Application Support/ai.wasifyai.desktop/logs/engine.log`; "Repair the installation" in Settings rebuilds the engine's environment |
| Desktop: Mic is silent or macOS never asked for the microphone | Run `touch apps/desktop/src-tauri/build.rs` and `cargo run` again (the permission text is read at build time); check System Settings, Privacy, Microphone |
| Desktop: a picture is refused ("cannot look at pictures") | The chat model needs its picture reader. Attach the picture again and press Download in the card, or put the model's `mmproj` file next to it |
| Desktop: web search says DuckDuckGo is busy or has not answered | DuckDuckGo limits automated searches. Wait a little, or add a key for Tavily, Exa, Brave or Ollama in Settings, Searching the web |
| Playwright cases fail only when two runs overlap | They share `apps/web/e2e/results` and `.next`: run one at a time, or give each run its own `--output` |
| `command not found` right after setup (Linux, WSL) | Tools are installed in `~/.local/bin`. Add it to your PATH (`export PATH="$HOME/.local/bin:$PATH"` in `~/.profile`) and reopen the shell |
| `make kind-up` fails on Linux with rootless Podman | Enable cgroup delegation: [runbooks/linux-kind.md](docs/runbooks/linux-kind.md) |
| WSL is slow or runs out of memory | Keep the repo under `~`, not `/mnt/c`, and raise the limit in `.wslconfig` ([docs/windows.md](docs/windows.md)) |

## Environments

| Environment | Where | Purpose |
|---|---|---|
| Dev | macOS, Linux or Windows (WSL2), Podman | Day-to-day development |
| Staging | Home lab k3s, 24 GB NVIDIA GPU | Integration and test runs |
| GCP test | Managed Kubernetes on GCP, built with OpenTofu, shut down after the test | Prove the deployment; not a launch |
| Prod | Managed Kubernetes, GCP first (AWS and Azure kept deployable) | Production, later |

The same container images run everywhere. Only infrastructure and configuration differ.

## Documentation

| Doc | What it covers |
|---|---|
| [Architecture](docs/architecture.md) | Layers, components, request flow, scaling, future seams |
| [Tech stack](docs/tech-stack.md) | Every tool and what it is for |
| [Environments](docs/environments.md) | Dev, staging and prod setup; GPU strategy; delivery pipeline |
| [Configuration](docs/configuration.md) | Secrets, environment wiring, product config, swappable models |
| [SSE event contract](docs/contracts/sse-events.md) | The streaming protocol between API and frontend |
| [Windows (WSL2)](docs/windows.md) | Running the project on Windows |
| [Home lab runbook](docs/runbooks/homelab-k3s.md) | k3s, Argo CD and Tailscale setup for staging |
| [kind on Linux](docs/runbooks/linux-kind.md) | Rootless Podman prerequisites for the local cluster |
| [Monitoring runbook](docs/runbooks/monitoring.md) | The stack, the alerts, where to look, fire drills |
| [The desktop profile](docs/desktop-profile.md) | How the engine runs on one computer, what is built, how the shell and engine meet |
| [Desktop window checklist](docs/testing/desktop-window-checklist.md) | What to try by hand in the real window, line by line |
| [Chat on assistant-ui](docs/chat-ui-migration-plan.md) | The new chat: stages CU0 to CU4 as built, what is left |
| [Chat box options](docs/composer-options-plan.md) and [spike report](docs/spikes/composer-co0.md) | Attach, Search, Thinking, Mic: what each does, measurements, what is not built |
| [The action catalogue](docs/actions.md) | Everything the app can do, described once; how to add an action |
| [Design system](design/DESIGN.md) | The look of every screen, in one file |
| [Roadmap](docs/roadmap.md) | Build phases, checklists and planned work |
| [Decisions](docs/decisions/README.md) | Architecture decision records (ADRs) |
| [`wasifyai-image`](products/wasifyai-image/README.md) | Text to image and image to image |
| [`wasifyai-video`](products/wasifyai-video/README.md) | Text to video and image to video |
| [`apps/web`](apps/web/README.md) | The web app: components, side panel, styling, sign-in |
| [`apps/desktop`](apps/desktop/README.md) | The desktop shell and window: commands, packaging, licence |

## Principles

- **Same images everywhere.** Environment differences live in config, never in code.
- **Open source first.** Proprietary components need a clear reason.
- **Capabilities, not models.** Models are swappable through config.
- **Never block on the GPU.** Slow generation is always a background job.
- **Build for multi-tenancy and billing now**, even while there is one user.

## Roadmap

**Where the work is now (2026-10-20).** The desktop app comes first.

| Order | What | State |
|---|---|---|
| Now | Try everything that was built in the real desktop window and fix what breaks ([checklist](docs/testing/desktop-window-checklist.md)) | In progress |
| Next | A simpler way to choose models, for each product and in the Models section, for people who are not technical (the way Unsloth Studio does it) | Next |
| After | The assistant that guides and executes (action cards on the catalogue), the MCP server and client, agents, training, Video Builder, motion graphics, 3D | On hold; [phase 4 plan](docs/phase4-agent-plan.md), [phase 5 plan](docs/phase5-agent-training-video-builder-plan.md) |

Built and waiting to be tried by hand: edit and versions, approval cards, attachments (and the picture reader), web
search, Thinking, Mic, read aloud and the notebook chat on the new chat. Not built: best-passages cutting for long
documents, a live check of DuckDuckGo's reliability, and checks in a signed macOS bundle.

**The hosted v1 plan.** v1 is a working, deployable system, not a production launch. Four stages:

| Stage | Goal | State |
|---|---|---|
| 1 | End to end on local kind, nothing native (all six products) | Done |
| 2 | Monitoring: metrics, dashboards, alerts to Telegram, an outside heartbeat | Done |
| 3 | Staging on the 24 GB NVIDIA box, built with OpenTofu | Next |
| 4 | GCP test, then shut down | Planned |

After v1: real GPU media, long
transcripts in search, SEO, analytics and billing (proposed ADRs 0026 to 0029).

Details and checklists: [docs/roadmap.md](docs/roadmap.md).

## Licence

Apache License 2.0, see [LICENSE](LICENSE), except `apps/desktop` (the desktop shell), which is AGPL-3.0-only because
it contains code imported from Unsloth Studio ([apps/desktop/LICENSE-AGPL](apps/desktop/LICENSE-AGPL)). Third-party software and the AI models you download keep their own
licences, some of which restrict commercial use; they are listed in [NOTICE](NOTICE). Check the current terms of
every model you enable.
