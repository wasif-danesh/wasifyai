# Wasify AI

Wasify AI is an AI app for your own computer, with a web version for teams. A **chat assistant** is the home screen.
Beside it you can make **images**, **video**, **voice and music**, **3D models** and whole **music videos and
promos**. You can also **chat with your documents**, **record and summarise meetings**, **teach models your own style**
and **work on code with an agent**. Everything you make lands in one library, **My creations**, which you can search
by meaning in any language.

The desktop app (macOS first; Windows and Linux are built by CI) runs models on your computer, in the cloud, or both.
The web app runs the same screens on cloud models only.

## Three ways to use a model

You choose where each product runs with the model button at the top of every screen. Each product can be set on its
own: for example, chat on your computer, video in the cloud, and code on your Claude plan.

| | Local, on your computer | Cloud, with your own keys | Cloud, with your subscription |
|---|---|---|---|
| **What it is** | Open models that run on your computer | Cloud models, paid at the provider's own price with keys you add | Your own Claude Code or Codex, signed in with your Claude or ChatGPT plan |
| **What it costs** | Nothing per use; your disk and memory | Pay as you go, prepaid with each provider. No fee of ours | Your existing plan; the program reports its use |
| **Privacy** | Nothing leaves your computer | Each job goes to the provider that runs it | Code sessions go to your plan's provider |
| **Where** | Desktop | Desktop and web (on the web, an admin adds the keys) | Desktop, in Code |
| **Used for** | Every product | Every product | Coding sessions and scheduled runs |

**Local.**
- **Chat:** the app runs the chat model itself (llama.cpp). It can also use the models of Ollama or LM Studio.
  Qwen3.5 9B is the model the assistant is tuned for.
- **Media:** images and video on a ComfyUI it manages itself (FLUX.2 klein, Z-Image, LTX-Video, Wan 2.2 and more).
- **Voice:** speech and music on audio.cpp (Kokoro, Parakeet, Whisper, ACE-Step).
- **Other parts:** lip sync on MuseTalk, 3D on Pixal3D, and meeting speakers on Sortformer.
- **Teaching models:** done on your computer with AI Toolkit and mlx-lm.
- **Finding models:** the app finds models that other tools (Ollama, LM Studio, ComfyUI, the Hugging Face cache)
  already downloaded. It shows the files and their sizes before it downloads anything.

**Your own keys.**
- **Text:** Claude Haiku 5.5 by default, bought directly from Anthropic. You can pick any model from Anthropic, OpenAI,
  Google Gemini, DeepSeek, Z.ai (GLM) or OpenRouter.
- **Media:** pictures, clips, voices, songs, lip sync, 3D and trained looks run on **Runware, WaveSpeed and fal.ai**.
  Each job goes to the **cheapest provider that has a key and can do it**, priced at Make
  ([ADR-0100](docs/decisions/0100-haiku-text-and-cheapest-media-provider.md)).
- **Where keys are kept:** in the system keychain. On the web, they are encrypted per team and only an admin can see
  that a key is set.

**Your subscription.**
- **How it works:** a coding session can run on the person's own Claude Code or Codex. The program signs in through
  the provider's own page, so the app never holds the login.
- **Inside a session:** the session keeps Wasify AI's sandbox, check loop, undo, Changes, Preview and Scheduled runs
  ([ADR-0107](docs/decisions/0107-harnesses-the-persons-own-agent-program.md)).
- **Set-up:** it is an optional part (about 694 MB), installed only when you ask for it.

## What you can make

| Product | What it does |
|---|---|
| [Assistant](products/wasifyai-assistant/) | The chat. It makes things for you (asking first), and has message versions, attachments, web search, Thinking, Mic and read aloud. It can carry out anything the app can do |
| [Images](products/wasifyai-image/README.md) | Create, edit, inpaint and reference images, and add Styles (LoRAs). Several models to choose from |
| [Video](products/wasifyai-video/README.md) | Clips from words or a picture, Extend, and Video Builder for longer pieces |
| [Voice](products/wasifyai-voice/README.md) | Text to speech, voice cloning, speech to text, music, sound effects, stem splitting, dubbing, audiobooks and lip sync |
| [Creative Studio](products/wasifyai-creative/) | From a song or a story to a finished video: a plan, shots, sung close-ups and a cut with captions. Includes Motion graphics, a scene editor for promos |
| [Notebooks](products/wasifyai-notebooks/) | Chat with your own documents, with citations and a Studio of reports, guides and decks |
| [Meetings](products/wasifyai-meetings/) | Record a meeting or add a file. It tells who spoke, names people across meetings, writes reports and lets you ask about it through Notebooks |
| [3D models](products/wasifyai-model3d/) | A 3D model from a picture or from words |
| [Training](products/wasifyai-training/) | Teach a model your own picture style, video look, way of writing, or decisions |
| [Code](products/wasifyai-code/) | A coding agent on OpenHands, in a sandbox. It has Files, Changes, a terminal, a browser, Preview, Extensions and Scheduled runs |

Other apps can use Wasify AI as a tool through its MCP server ([docs](docs/desktop/connections.md)). Nothing a person
makes is moderated, marked or limited per day
([ADR-0094](docs/decisions/0094-no-safeguards-marks-or-licence-data-in-v1.md)).

## How it works

One engine (`services/api`: FastAPI and LangGraph) runs every product, in two profiles. Product code never asks which
profile it runs in.

**Desktop:** a Tauri window starts the engine on your computer.

```
Tauri window (packages/ui) ─► engine on 127.0.0.1 (a token per launch)
                                 ├─► SQLite (records, run state, job queue) and a folder of files
                                 ├─► local models, started on demand: llama.cpp, ComfyUI, audio.cpp,
                                 │   MuseTalk, Pixal3D, Sortformer, AI Toolkit / mlx-lm
                                 ├─► cloud models on your keys: text vendors, Runware / WaveSpeed / fal.ai
                                 └─► the coding engine (OpenHands Agent Server) in a sandbox,
                                     on a key, a local model, or your own Claude Code / Codex
```

**Web:** the same screens in a Next.js app, with the engine in containers and no GPU.

```
Browser ─► Next.js (UI + sign-in) ─► FastAPI + LangGraph ─► LiteLLM ─► Anthropic, OpenAI, Gemini, ...
                                          ├─► Postgres (pgvector, run state)  ├─► Embedder (bge-m3, CPU)
                                          ├─► Redis ─► Media worker ─► Runware / WaveSpeed / fal.ai
                                          └─► Object storage (SeaweedFS / S3 / GCS / Azure Blob)
```

- **Capabilities, not models.** Products ask for a capability (`text.chat`, `image.generate`), and configuration
  decides which model and provider answer.
- **Slow work never blocks.** Images, video and long jobs run as background jobs, and progress streams to the screen.
- **Every feature is an action.** Anything a person can do has an action in one catalogue, used by the menu, the
  assistant and the MCP server ([docs/actions.md](docs/actions.md)).
- **Everything is searchable.** Each kind of creation is indexed for My creations
  ([ADR-0041](docs/decisions/0041-semantic-search.md)).
- **Shared screens.** The screens live in `packages/ui` and talk to the engine through `packages/client`, so the
  window and the web app draw the same ones. `design/DESIGN.md` is the only source of the look.

More: [Architecture](docs/architecture.md), [the desktop profile](docs/desktop-profile.md),
[environments](docs/environments.md).

## Run the desktop app

You need macOS (the platform tried by hand), Homebrew, Apple's command line tools (`xcode-select --install`) and Rust
1.89 or newer ([rustup](https://rustup.rs)). `make setup` installs the rest.

```bash
git clone https://github.com/wasif-danesh/wasifyai.git && cd wasifyai
make setup                                  # tools and the Python environment
pnpm --filter @wasifyai/desktop build       # the window's files
cd apps/desktop/src-tauri && cargo run      # the shell; it starts the engine
```

**First steps in the window:**
1. Open the model button. To run chat locally, set up the language engine and choose a model; each download shows
   its size first.
2. For the cloud, add a key under the **Cloud** tab.
3. Optional parts (the image engine, speech models, the coding engine, agent programs) are installed from Settings
   when you want them.

Your data lives in `~/Library/Application Support/ai.wasifyai.desktop`. If something fails, look first at
`logs/engine.log` there.

A packaged app: run `make engine-bundle`, then
`pnpm exec tauri build --config src-tauri/tauri.bundle.conf.json --bundles app` in `apps/desktop`. More:
[apps/desktop](apps/desktop/README.md), [desktop window checklist](docs/testing/desktop-window-checklist.md).

## Run the web app

```bash
make setup      # tools, Podman, .env with generated secrets
make dev        # the stack, migrations, then follows the logs
```

1. Open http://localhost:3000.
2. Put an `ANTHROPIC_API_KEY` in `.env` for text. Media jobs return placeholders (`COMFYUI_MODE=stub`) until an admin
   adds Runware, WaveSpeed or fal.ai keys in **Admin › Media**.
3. Sign-in is off by default (`AUTH_MODE=stub`). To turn it on, see [apps/web](apps/web/README.md#sign-in).

On Windows, use WSL2 ([docs/windows.md](docs/windows.md)).

**On a local Kubernetes cluster:** `make kind-up`, `make kind-test` and `make kind-down` run the Helm chart used for
staging. **Monitoring** (Prometheus, Grafana, Loki, alerts to Telegram) is described in the
[runbook](docs/runbooks/monitoring.md).

`make urls` prints where each service is for the mode that is running:

<!-- urls:start -->
| Service | What it is | Compose (`make dev`) | kind (`make kind-up`) |
|---|---|---|---|
| Web app | every product, My creations, admin | `http://localhost:3000` | `http://localhost:3000` |
| Admin area | users, models, media backends, audit | `http://localhost:3000/admin` | `http://localhost:3000/admin` |
| API docs | Swagger UI for the API | `http://localhost:8000/docs` | `kubectl -n wasifyai port-forward svc/wasifyai-api 8000:8000`, then `http://localhost:8000/docs` |
| LiteLLM | the model gateway | `http://localhost:4000` | `kubectl -n wasifyai port-forward svc/wasifyai-litellm 4000:4000`, then `http://localhost:4000` |
| Object storage | S3 API (SeaweedFS) | `http://localhost:8333` | `kubectl -n wasifyai port-forward svc/wasifyai-storage 8333:8333`, then `http://localhost:8333` |
| Embedder | bge-m3 for search, on the CPU | `http://localhost:8090` | `kubectl -n wasifyai port-forward svc/wasifyai-embedder 8090:8080`, then `http://localhost:8090` |
| Postgres | database, checkpoints, usage events | `localhost:5432` | `kubectl -n wasifyai port-forward svc/wasifyai-postgres 5432:5432`, then `localhost:5432` |
| Redis | job queue and run events | `localhost:6379` | `kubectl -n wasifyai port-forward svc/wasifyai-redis 6379:6379`, then `localhost:6379` |
| Grafana | dashboards and logs | not installed | `kubectl -n monitoring port-forward svc/monitoring-grafana 3001:80`, then `http://localhost:3001` |
| Prometheus | metrics and alert rules | not installed | `kubectl -n monitoring port-forward svc/monitoring-prometheus 9090:9090`, then `http://localhost:9090` |
| Alertmanager | what is firing, where it goes | not installed | `kubectl -n monitoring port-forward svc/monitoring-alertmanager 9093:9093`, then `http://localhost:9093` |
| Healthchecks.io | the outside heartbeat | not installed | `https://healthchecks.io` |
<!-- urls:end -->

## Development

```bash
make test         # Python and TypeScript tests (no GPU or network)
make lint         # ruff, pyright, Biome, tsc
make contracts    # TypeScript types and the action catalogue, from the API
pnpm --filter @wasifyai/ui exec vitest run         # the shared screens; also client, web, desktop
cd apps/desktop/src-tauri && cargo test            # the shell
```

- **Tools:** Python 3.12 with uv; TypeScript with pnpm, Turborepo, Biome and Vitest.
- **Contracts:** Pydantic models are the source of truth. Never edit `packages/contracts-ts/src/schema.gen.ts` by
  hand.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org), scoped by area (`feat(api): ...`).
- **Containers:** scripts use `${CONTAINER_ENGINE:-podman}`.

## Project layout

```
apps/web/          Next.js web app (UI, sign-in, admin)
apps/desktop/      Tauri shell (Rust) and the window
services/api/      the engine: FastAPI + LangGraph, both profiles, keys and providers
services/          media-worker (jobs on cloud providers or ComfyUI), engine-worker, coding-engine, comfyui
packages/ui/       the screens shared by the window and the web app
packages/client/   the typed engine client
packages/          contracts (Pydantic), contracts-ts (generated), platform-sdk
products/          one folder per product: product.yaml, graphs, prompts, workflows
deploy/            Helm chart, Compose config, monitoring, kind, Argo CD
design/            DESIGN.md, the one source of the look
docs/              architecture, decisions (ADRs), plans, spikes, runbooks
```

## Documentation

| Doc | What it covers |
|---|---|
| [Architecture](docs/architecture.md) | The engine, the two profiles, where models run, request flow |
| [Decisions](docs/decisions/README.md) | Every architecture decision record (ADR) |
| [Cloud v1 plan](docs/cloud-v1-plan.md) | Keys, vendors, the cheapest-provider router |
| [The desktop profile](docs/desktop-profile.md) | How the engine runs on one computer, with a page for each product |
| [Environments](docs/environments.md) | Dev, staging and prod; what runs where |
| [Configuration](docs/configuration.md) | Secrets, wiring, product config |
| [The action catalogue](docs/actions.md) | Everything the app can do, and how to add an action |
| [Design system](design/DESIGN.md) | The look of every screen |
| [Roadmap](docs/roadmap.md) and [backlog](docs/backlog.md) | Planned and open work |

## Licence

Apache License 2.0 ([LICENSE](LICENSE)). The exception is `apps/desktop`, which is AGPL-3.0-only because it contains
code from Unsloth Studio ([LICENSE-AGPL](apps/desktop/LICENSE-AGPL)). Third-party software and the models you
download keep their own licences ([NOTICE](NOTICE)).
