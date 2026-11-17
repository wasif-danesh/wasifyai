# Wasify AI

Wasify AI is one app for making things with AI **on your own computer**: you chat with an assistant, and beside
it make pictures, video, speech, music, 3D models and motion graphics, record meetings, ask your own documents,
write code with an agent, and teach models your own style. The models run on your machine, so what you make stays
there. If you want a bigger model, add your own key for a cloud provider and choose it in the same place.

It is a desktop app (a window that starts its own engine; macOS first) and a web app that shows the same screens.
Under both is a reusable **platform core** (the repository is called `wasifyai`): an API with streaming, an agent
runtime, a model gateway, media workers, storage, sign-in and monitoring. Each product is a thin layer on top.

> **Status (2026-11-17): v1 in progress, desktop first.** Everything on this page is built and runs on an Apple
> Silicon Mac. There is no installer to download yet: you [build the app from source](#run-the-desktop-app).
> Windows and Linux builds pass CI but have not been used by hand. See the [roadmap](docs/roadmap.md).

![The home window: the chat box, the model button in the top bar, quick starts for each thing you can make, and the menu on the left](docs/images/screens/desktop/home.png)

## Contents

- [What you can do](#what-you-can-do)
- [Choosing models](#choosing-models)
- [Settings worth knowing](#settings-worth-knowing)
- [What stays on your computer](#what-stays-on-your-computer)
- [More screens](#more-screens)
- [What the chat can do](#what-the-chat-can-do)
- [What you need](#what-you-need)
- [Run the desktop app](#run-the-desktop-app)
- [Run the web app](#run-the-web-app) (including [what to install first](#before-you-start-manual-prerequisites))
- [How it works](#how-it-works)
- [Products](#products)
- [Monitoring](#monitoring)
- [Using the API](#using-the-api)
- [Project layout](#project-layout)
- [Configuration](#configuration)
- [Development](#development) (and [troubleshooting](#troubleshooting))
- [Environments](#environments)
- [Documentation](#documentation)
- [Principles](#principles)
- [Roadmap](#roadmap)

## What you can do

Each line is an item of the menu on the left of the window.

| In the menu | What it does |
|---|---|
| **New chat** | Ask anything, attach pictures and documents, search the web, dictate, hear answers read aloud. Ask it to make a picture, a song or a video and the result appears in the chat. |
| **Notebook** | Add your own documents and ask them questions; answers cite the passage they came from. A Studio turns a notebook into reports, study guides and slide decks. |
| **Meetings** | Record a meeting (your microphone and the computer's sound) or add a recording. It writes down who said what, lets you name the speakers, writes reports from templates and answers questions about the meeting. |
| **Images** | Create from words, edit a picture, paint over a part of it (inpaint), or combine reference pictures. Add styles (LoRAs) to change the look. |
| **Video** | A short clip from words or from a picture, lip sync (a face speaks your audio) and extending a clip. |
| **Voice** | Text to speech, speech to text, your own voices, changing a voice, editing speech, dubbing a recording into another language, audiobooks. |
| **Music** | Songs, instrumentals and sound effects, lyrics, and splitting a song into its parts. |
| **Code** | A coding agent that works in a folder you choose: it reads, plans, changes files and checks its work, and every turn can be undone. Scheduled runs and extensions (skills and plugins). It can also run on your own Claude Code or Codex plan. |
| **Creative Studio** | A song and an idea become a plan of shots, then pictures, clips and a finished video cut on the beat. |
| **Motion graphics** | Promotion and social videos from scenes: animated titles, charts, captions, with an assistant that edits the scenes for you. |
| **3D model** | A 3D model from one picture (experimental). |
| **Library** | Everything you made, in one place, searchable by meaning in any language. |
| **Train models** | Teach an image model your character or style, a language model your answers, a model to decide (yes or no, a category, a score), or a video model a look or motion. |
| **Model hub** | Every model the app can use, per job, with its size and whether it is on this computer. |

## Choosing models

You never edit a config file to choose a model. Every screen has a **model button in the top bar**. It opens a
small list with three tabs:

- **Recommended**: models that suit this computer, with the download size and the memory they need.
- **On this computer**: what is already here, including models found in Ollama or LM Studio.
- **Cloud**: the models of the providers you saved a key for (empty until you add one).

A model is downloaded only after you press Get and have seen its size.

| Recommended | On this computer |
|---|---|
| ![The model list on its Recommended tab: three chat models with their size and what they need](docs/images/screens/desktop/model-picker.png) | ![The model list on its On this computer tab: models already here](docs/images/screens/desktop/model-picker-local.png) |

The **Model hub** shows the same choices for every job at once: Chat, Code, Images, Video, Voice, Listening,
Music, Lip sync, Documents, 3D and Training.

| Model hub: chat models | Model hub: image models |
|---|---|
| ![The Model hub on its Chat tab](docs/images/screens/desktop/model-hub.png) | ![The Model hub on its Images tab, with sizes and memory needs](docs/images/screens/desktop/model-hub-images.png) |

## Settings worth knowing

Settings (the gear at the bottom of the menu) has seven groups: General, Cloud keys, On this computer, Code,
Privacy, Other apps, and Help and repair. Three of them matter on the first day.

**On this computer** says what this machine can do right now, job by job, and lists the optional parts (the
language engine, the image engine, the coding engine and others). A part is added only when you use something
that needs it, and can be repaired or removed here.

![Settings, On this computer: a list of jobs, each marked ready with the model it uses](docs/images/screens/desktop/settings-computer.png)

**Cloud keys** is where you add your own key for a cloud provider. This is optional: without a key, everything
runs on this computer's models. For chat and writing, one key from Anthropic, OpenAI, Google Gemini, DeepSeek, Z.ai
or OpenRouter is enough. For media (images, video, voice, music, lip sync, 3D), add a fal.ai key, or a Runware and
a WaveSpeed key; with more than one, each job goes to the cheapest. Keys are kept in the computer's keychain and
are never shown again, and you pay the provider directly.

![Settings, Cloud keys: text providers, media providers, and a table of what each key covers](docs/images/screens/desktop/settings-keys.png)

**Privacy** lists everything that can leave the computer, and each item is your choice. Web search is here too:
it is off until you allow it, and you choose the search service.

![Settings, Privacy: what leaves this computer, and the web search service](docs/images/screens/desktop/settings-privacy.png)

## What stays on your computer

- What you make, your files and your chats are stored in the app's data folder on your computer (on macOS
  `~/Library/Application Support/ai.wasifyai.desktop`). There is no account and no sign-in on the desktop.
- The engine listens only on `127.0.0.1`, and every call carries a token made for that launch.
- Things leave the computer only when you choose: a cloud model you picked (what you make with it goes to its
  provider, on your key), a web search you allowed, a model download, and other apps you connected.
- Nothing you make is moderated, marked or limited per day
  ([ADR-0094](docs/decisions/0094-no-safeguards-marks-or-licence-data-in-v1.md)).

## More screens

The pictures on this page are of the real desktop window on a Mac with its models installed, so the names and
sizes are that computer's. `WASIFYAI_AUDIT_OUT=$PWD/docs/images/screens/desktop apps/desktop/scripts/ui-audit.sh light readme`
takes them again.

| Images | Video |
|---|---|
| ![Make a picture: a prompt, aspect ratio, styles, and recent pictures](docs/images/screens/desktop/images.png) | ![Make a video: a prompt, length and shape](docs/images/screens/desktop/video.png) |

| Text to speech | Music |
|---|---|
| ![Text to speech: language, words and a list of voices](docs/images/screens/desktop/speech.png) | ![Create music: a description, lyrics and length](docs/images/screens/desktop/music.png) |

| Motion graphics | Train models |
|---|---|
| ![Motion graphics: say what you want to promote, or start from a template](docs/images/screens/desktop/motion.png) | ![Train models: four cards for pictures, language, decisions and video](docs/images/screens/desktop/train.png) |

The chat pictures below come from the web app against its test engine, so they show sample data
(`README_SHOTS=1 pnpm --filter web exec playwright test e2e/readme-screens.spec.ts --project=desktop-light`).

| A chat: a picture and a file attached, sources from the web, two versions of an answer | The assistant asks before it makes something |
|---|---|
| ![A chat with attachments, web sources and a version picker](docs/images/screens/chat.png) | ![A card that asks before making a picture](docs/images/screens/card.png) |

| Files waiting in the box | On a phone (the web app) |
|---|---|
| ![A picture and a PDF waiting to be sent](docs/images/screens/attach.png) | ![A chat on a phone, dark theme](docs/images/screens/phone.png) |

![A notebook with its chat, citation pills and the Studio](docs/images/screens/notebook-chat.png)

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

## What you need

| | Desktop app |
|---|---|
| Computer | A Mac with Apple Silicon is the tested platform. Windows and Linux are built and tested by CI only. |
| Memory | 8 GB runs a small chat model. 16 GB is comfortable for chat and pictures. Larger image and video models say what they need in the Model hub (24 to 40 GB for the biggest). |
| Disk | About 15 GB free to start. Each model shows its size before it downloads: a chat model is 0.4 to 5 GB, an image model 11 to 29 GB. |
| Internet | Only to download models and optional parts, and for cloud models or web search if you turn them on. |
| Accounts | None. A cloud provider key is optional. |

## Run the desktop app

The desktop app is a small Rust shell ([Tauri 2](https://tauri.app)) that starts the engine (`services/api` in its
desktop profile: SQLite, local files, a worker in the same process) and shows the window. Nothing listens on the
network: the engine binds `127.0.0.1` and every call carries a token the shell made for that launch.

**You need** (macOS is the tested platform): Homebrew, Apple's command line tools (`xcode-select --install`), and
the Rust toolchain 1.89 or newer ([rustup](https://rustup.rs)). `make setup` installs the rest (`uv`, Node 22,
`pnpm`) and the Python environment; it does not install Rust. Memory and disk: see [What you need](#what-you-need).
Windows and Linux are built and tested by CI but have not been used by hand.

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

1. The window opens on the assistant. Press the **model button** in the top bar and choose a chat model. On the
   Recommended tab the app suggests one for this computer's memory (Qwen3 8B, 5.0 GB, with 16 GB or more; Qwen3 4B,
   2.5 GB, below that); press Get and it installs the language engine and the model, with the size shown first. If
   you already use Ollama or LM Studio, their models are on the On this computer tab.
2. Ask something. The quick starts under the chat box (Picture, Video, Speech, Song and the rest) say "Ready" or
   "Choose a model"; each opens its screen, where the same model button gets what it needs.
3. Everything else is optional and fetched only when you use it and agree to its size: the image engine, a speech
   model for Mic and Read aloud, the picture reader (the first time you attach a picture), the document reader for
   PDF and Office files, the coding engine, the speaker model for Meetings. **Settings › On this computer** lists
   them. To use cloud models, add a key in **Settings › Cloud keys**.

Your data (database, files, models you fetched, logs) lives in the app data folder: on macOS
`~/Library/Application Support/ai.wasifyai.desktop` (`logs/engine.log` is the first place to look when something
fails). More: [desktop profile](docs/desktop-profile.md), [apps/desktop](apps/desktop/README.md). **Testing it by
hand:** [desktop window checklist](docs/testing/desktop-window-checklist.md).

## Run the web app

The same screens as a web app, with the engine in containers: Postgres, Redis, object storage, the model gateway
(LiteLLM), a small search model, the API, a media worker, the notebooks worker and the web app itself.

**The web app runs cloud models only** ([ADR-0099](docs/decisions/0099-fal-only-v1-web-on-cloud-models.md),
[ADR-0100](docs/decisions/0100-haiku-text-and-cheapest-media-provider.md)). It needs no GPU and downloads no chat,
image or video model. The one model it runs itself is bge-m3, for search, on the CPU.

Do the [one-time prerequisites](#before-you-start-manual-prerequisites) for your platform, then:

```bash
git clone https://github.com/wasif-danesh/wasifyai.git && cd wasifyai
make setup      # installs missing tools, starts Podman, creates .env with random secrets
make dev        # starts the stack, waits for Postgres, runs migrations, follows logs
```

Then open http://localhost:3000. What works depends on the keys you give it:

| You want | Do this |
|---|---|
| **Chat, notebooks, the assistant and every text step** | Put an Anthropic key in `.env` as `ANTHROPIC_API_KEY` and run `make dev` again. Every text job runs on Claude Haiku 5.5 by default. To use another vendor (OpenAI, Google Gemini, DeepSeek, Z.ai, OpenRouter), choose it and save its key in **Admin › Models** (`/admin/models`). Without a key, chat answers with an error. |
| **To look around without paying for media** | Nothing. `COMFYUI_MODE=stub` (the default in `.env`) returns placeholder pictures, clips and audio, so every screen and the whole flow work with no key. |
| **Real pictures, video, voice, music, lip sync and 3D** | Set `COMFYUI_MODE=cloud` in `.env`, run `make dev` again, and save a fal.ai key, or a Runware and a WaveSpeed key, in **Admin › Media** (`/admin/media`). Each job goes to the cheapest provider that can do it. |

Sign-in is off by default (`AUTH_MODE=stub` in `.env.example`: everyone is the dev user, who is an admin). To turn
it on, set `AUTH_MODE=jwt`, the two secrets and a provider's client id and secret: see
[Sign-in in apps/web](apps/web/README.md#sign-in).

**On a Mac that also has the desktop app set up**, `make dev` starts two workers outside the containers
(`scripts/worker.sh`). They use the desktop app's data folder and its models, and take the place of the stack's own
media worker, so the web makes pictures, video, speech, music and lip sync with that Mac's models instead of
placeholders. Quit the desktop app while they run a job; `make down` stops them.
[Runbook](docs/runbooks/web-notebooks-voice.md).

If `make` is not installed yet (common on a fresh Linux box), run the script directly. It
installs `make` for you: `./scripts/setup.sh`, then `make dev`.

### Before you start (manual prerequisites)

`make setup` installs almost everything, but a few things must exist first because they need
administrator rights, a reboot, or are needed to run the setup at all. Do these once.

**Every platform**

- An internet connection, and several GB of free disk for the container images (the notebooks worker's image
  holds a document reader of about 1.5 GB, and the search model is a 635 MB download on the first start).
- 8 GB of RAM or more (16 GB is more comfortable).
- No GPU: the models run at the cloud providers.

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
| Linux: Debian, Ubuntu, Kali (apt), Fedora (dnf), Arch (pacman) | Supported; the tool installation is tested in Ubuntu and Fedora containers and in CI. The container engine steps are tested on macOS only |
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
3. Installs and starts Ollama. No default model uses it any more, so nothing is pulled; it is still installed and
   `make dev` still checks that it answers. It is only used if an admin binds a model to it in Admin › Models. On
   Linux setup also checks that containers can reach it and offers a fix if not.
4. Creates `.env` from `.env.example` and generates random secrets. Nothing is printed.
5. Runs `uv sync --all-packages` and `pnpm install`.

Anything it cannot do for you is listed under
[Before you start](#before-you-start-manual-prerequisites); the script stops with a message if
something is missing.

`make dev` runs `make preflight` first: a fast, read-only check that lists exactly what is
missing and points back to `make setup`.

### Hardware notes

- The stack itself is light: no model runs in it except bge-m3 for search, on the CPU.
- Lip sync on this computer (MuseTalk 1.5) is a desktop component: about 12 GB of memory and 5 seconds of work per
  second of video. The web reaches it through the workers on a Mac that has the desktop app set up, or runs a cloud
  lip sync model.
- Linux and WSL: Ollama listens on `127.0.0.1` by default, which containers may not reach.
  `make setup` tests this and, with your consent, makes Ollama listen on `0.0.0.0`. Ollama has no
  authentication, so restrict port 11434 with a host firewall.

### Services

| Service | URL |
|---|---|
| Web (Next.js) | http://localhost:3000 |
| API (FastAPI) | http://localhost:8000 (`/health`, `/docs`) |
| LiteLLM | http://localhost:4000 |
| Search model (bge-m3) | http://localhost:8090 |
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
make kind-e2e     # makes something with the image and video products
make kind-down    # delete the cluster
```

No model runs in the cluster: it is the same cloud-only web app, and without keys the media worker makes
placeholder files. The default `KIND_MODE=full` installs the chart and the monitoring stack (Prometheus,
Alertmanager, Grafana and Loki); `KIND_MODE=light` is the small cluster CI runs. Home lab setup with k3s and
Argo CD: [runbook](docs/runbooks/homelab-k3s.md).

### Where everything is

`make urls` prints this for the mode that is running and says what answers right now.

<!-- urls:start -->
| Service | What it is | Compose (`make dev`) | kind (`make kind-up`) |
|---|---|---|---|
| Web app | every product, the Library, admin | `http://localhost:3000` | `http://localhost:3000` |
| Admin area | users, models, media backends, audit | `http://localhost:3000/admin` | `http://localhost:3000/admin` |
| API docs | Swagger UI for the API | `http://localhost:8000/docs` | `kubectl -n wasifyai port-forward svc/wasifyai-api 8000:8000`, then `http://localhost:8000/docs` |
| LiteLLM | the model gateway | `http://localhost:4000` | `kubectl -n wasifyai port-forward svc/wasifyai-litellm 4000:4000`, then `http://localhost:4000` |
| Object storage | S3 API (SeaweedFS) | `http://localhost:8333` | `kubectl -n wasifyai port-forward svc/wasifyai-storage 8333:8333`, then `http://localhost:8333` |
| Embedder | bge-m3 for search (llama.cpp, on the CPU) | `http://localhost:8090` | `kubectl -n wasifyai port-forward svc/wasifyai-embedder 8090:8080`, then `http://localhost:8090` |
| Ollama | optional: only for a model an admin binds to it | `http://localhost:11434` | not in the cluster |
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
podman compose up -d postgres redis seaweedfs litellm embedder
DATABASE_URL=postgresql+asyncpg://wasifyai:wasifyai@localhost:5432/wasifyai \
  LITELLM_BASE_URL=http://localhost:4000 \
  uv run uvicorn wasifyai_api.main:app --reload --port 8000
API_BASE_URL=http://localhost:8000 pnpm --filter web dev      # in another terminal
```

## How it works

```
Browser ─► Next.js (UI + BFF) ─► FastAPI + LangGraph ─► LiteLLM ─► Anthropic and other text vendors
                                        │                    └────► bge-m3 for search (own CPU)
                                        ├─► Postgres (pgvector, checkpoints, jobs)
                                        ├─► Redis (job queue, pub/sub) ─► Media worker ───► Runware / WaveSpeed / fal.ai
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
4. Text goes through **LiteLLM**, an OpenAI-compatible gateway that maps aliases to a text vendor (Claude
   Haiku 5.5 by default; an admin can choose another).
5. Slow work (images, video) is never awaited inline. The graph enqueues a job in
   **Redis**, a **media worker** sends it to the cheapest cloud provider that can do it, and the graph resumes
   when the job finishes.
6. Graph state is checkpointed in **Postgres**, so a run can pause for user input and resume.
7. Nothing a person makes is moderated, marked or limited per day
   ([ADR-0094](docs/decisions/0094-no-safeguards-marks-or-licence-data-in-v1.md)).

## Products

| Product | What it does |
|---|---|
| [`wasifyai-assistant`](products/wasifyai-assistant/) | The chat: conversations with a tree of message versions, tools that make things, cards that ask first, attachments, web search, Thinking |
| [`wasifyai-image`](products/wasifyai-image/README.md) | Create, edit, inpaint and reference pictures, with styles |
| [`wasifyai-video`](products/wasifyai-video/README.md) | Text to video, image to video, extending a clip, and Motion graphics; made in the background |
| [`wasifyai-voice`](products/wasifyai-voice/README.md) | Text to speech, speech to text (and Mic dictation), music, audio tools, dubbing, audiobooks, lip sync, read aloud |
| [`wasifyai-notebooks`](products/wasifyai-notebooks/) | Chat with your own documents: sources, citations, a Studio of outputs |
| [`wasifyai-meetings`](products/wasifyai-meetings/) | Record or add a meeting, tell the speakers apart, name them, write reports, ask about it |
| [`wasifyai-code`](products/wasifyai-code/) | The coding agent: projects, sessions, checks, undo, scheduled runs, extensions |
| [`wasifyai-creative`](products/wasifyai-creative/) | Creative Studio: a song and an idea become a plan of shots, then a video |
| [`wasifyai-model3d`](products/wasifyai-model3d/) | A 3D model from a picture (experimental) |
| [`wasifyai-training`](products/wasifyai-training/) | Train models: image, language, decision and video |

A product is a folder under `products/` with its `product.yaml`, graphs, prompts and ComfyUI
workflows. Adding a product adds no API endpoints: the graph registry exposes registered
graphs through the same generic routes.

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
│  ├─ wasifyai-meetings/        # meetings: speakers, reports, questions
│  ├─ wasifyai-code/            # the coding agent
│  ├─ wasifyai-creative/        # Creative Studio
│  ├─ wasifyai-model3d/         # 3D models
│  ├─ wasifyai-training/        # Train models
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
| Web: chat gives no reply, or an error | The text vendor has no key. Set `ANTHROPIC_API_KEY` in `.env` and run `make dev` again, or save a key in Admin › Models; then look at `podman logs wasifyai-litellm-1` |
| LiteLLM exits at start | `podman logs wasifyai-litellm-1`. It needs `LITELLM_API_KEY` set in `.env` |
| Port already in use | `make down`, then try again |
| Every model call fails with "model not found" right after start | The API seeds the model aliases into LiteLLM when it starts; give it a minute and check `podman logs wasifyai-api-1`. `LITELLM_API_KEY` must match between the API and LiteLLM |
| "API keys can't be saved yet" in `/admin/media` | `MEDIA_SECRETS_KEY` is missing: run `make setup`, then restart the API and the worker |
| `make dev` fails with "LITELLM_SALT_KEY" | Run `make setup`; it generates the key. Never change it afterwards: saved provider keys are encrypted with it |
| `podman compose` cannot connect | Run `podman machine start` |
| `make dev` says "Not ready" | Run `make setup`; it fixes every item the preflight lists (Ollama must answer, even though no default model uses it) |
| Web: pictures and clips are placeholders | That is `COMFYUI_MODE=stub`. Set `COMFYUI_MODE=cloud` and save a media key in Admin › Media |
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
| [Desktop, area by area](docs/desktop/) | One page each: assistant, models, images, video, voice, notebooks, meetings, coding, Creative Studio, 3D, connections to other apps |
| [Help pages](docs/help/) | One short page per thing the app can do |
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

**Where the work is now (2026-11-17).** The desktop app comes first. Built: the chat, notebooks, meetings, images,
video, voice, music, the coding agent, Creative Studio, Motion graphics, 3D models, the Library, Train models, the
Model hub, and cloud models on your own keys. Still to come before v1: a signed installer and an update feed, hand
testing on Windows and Linux, and the open items in [docs/backlog.md](docs/backlog.md).

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
