# Configuration

There are three kinds of configuration. Each has one home.

| Kind | Examples | Local | Kubernetes |
|---|---|---|---|
| **Secrets** | OAuth client secrets, DB passwords, API keys, `AUTH_SECRET`, `LITELLM_SALT_KEY`, `MEDIA_SECRETS_KEY` | `.env` (gitignored); keys listed in `.env.example` | Kubernetes Secret from External Secrets or SOPS |
| **Environment wiring** | `OLLAMA_BASE_URL`, `COMFYUI_BASE_URL`, `LITELLM_BASE_URL`, `DATABASE_URL`, bucket name | `.env` + `compose.yaml` | Helm values → ConfigMap |
| **Product config** | Model bindings, workflow choice, prompts, quotas | `products/<id>/product.yaml` (in Git) | Same file, baked into the image |

Application code reads secrets and wiring only through `pydantic-settings`, and product
config only through the validated product config model. Code never knows where a value
came from.

## Authentication settings

| Variable | Where | Meaning |
|---|---|---|
| `AUTH_MODE` | api, web | `jwt` (default) real sign-in; `stub` dev user only. Staging and production never set `stub` |
| `AUTH_SECRET` | web | Auth.js cookie encryption |
| `API_AUTH_SECRET` | api, web | Shared secret (at least 32 bytes) for the BFF-to-API token; the API refuses to start in `jwt` mode without it |
| `AUTH_<PROVIDER>_ID` / `_SECRET` | web | One OAuth app per provider and environment (see `apps/web/README.md`) |
| `SAFEGUARDS_FORCE_ON` | api | `true` in production (Helm `safeguards.forceOn`): moderation and quotas always apply and Admin > Safeguards is read-only. Unset elsewhere: off by default, an admin switches it (ADR-0047) |
| `ADMIN_EMAILS` | api | Comma-separated; only a verified email becomes admin |
| `WASIFYAI_MCP_LAUNCHER` | api | The path of the `wasify-mcp` launcher (the shell sets it); Settings > Other apps shows it in the commands to paste (ADR-0069) |
| `WASIFYAI_SECRET_<NAME>` | api | A read-only secret for the secret store (ADR-0092): `WASIFYAI_SECRET_WEB_SEARCH_EXA` answers `web.search.exa`. On the web what an admin saves goes to the `secrets` table (Fernet under `MEDIA_SECRETS_KEY`); the environment answers behind it. `HF_TOKEN` is read as `hf.token` |

## Deployment profile (desktop)

`DEPLOYMENT_PROFILE=web` (default) or `desktop` (ADR-0056). The desktop profile is started by the shell, which
sets these; see [desktop-profile.md](desktop-profile.md).

| Variable | Meaning |
|---|---|
| `DESKTOP_DATA_DIR` | database, checkpoints and files (required on desktop) |
| `DESKTOP_PUBLIC_URL` | the engine's own URL for signed file links (set by the launcher) |
| `DESKTOP_ALLOWED_ORIGINS` | window origins allowed by CORS |
| `DESKTOP_IMAGE_ENGINE` | `stub` (default, no GPU) or `comfyui` |
| `PRODUCTS_ENABLED` | comma-separated product ids to serve; empty means all (desktop: `wasifyai-image`) |

## Precedence

Later wins:

1. Defaults in code
2. `products/<id>/product.yaml`
3. `products/<id>/product.<env>.yaml` (optional, e.g. a lighter GGUF workflow in dev)
4. Environment variables with a nested prefix, for emergency overrides, e.g.
   `WASIFYAI_MUSIC__CAPABILITIES__MUSIC_GENERATE__WORKFLOW=ace-step-1.5-base`

The merged result is validated by one Pydantic model **at startup** (`wasifyai_platform_sdk.config`).
It reports every problem at once, rejects unknown keys, and checks that every referenced
workflow and map file exists and every mapped node ID is present in the workflow JSON. A bad
config fails the deploy, not a user's request. The overlay is selected with `PRODUCT_ENV`
(e.g. `dev` loads `product.dev.yaml`). Free-form product values go under `settings:`.

## Capabilities: swappable models

Graphs request capabilities. Config binds them to providers.

```yaml
# products/wasifyai-image/product.yaml
id: wasifyai-image
capabilities:
  text.moderate:
    provider: litellm
    model: moderator              # a LiteLLM alias, not a raw model name
  image.generate:
    provider: comfyui
    workflow: flux2-klein-4b
    defaults: { width: 1024, height: 1024 }
quotas:
  images_per_user_per_day: 20
```

A product that accepts user pictures opts in with `uploads: { image: { max_bytes: 10485760 } }` (ADR-0035) and
binds `image.edit` (image to image) like any other capability; see `products/wasifyai-image/product.yaml`.

A product that offers the Enhance button (ADR-0038) binds `text.enhance` (alias `prompt-enhancer`) and, if a kind
needs the user's picture, `text.describe_image` (alias `multimodal`), and lists its kinds:

```yaml
enhance:
  text_to_video:  { prompt: enhance_text_to_video, max_chars: 500 }       # prompt = file in prompts/
  image_to_video: { prompt: enhance_image_to_video, max_chars: 500, needs_picture: true }
```

The product mounts the route with `build_enhance_router(deps, product_id, load_prompt, guard)` from its own routes
(ADR-0023); `guard` is its guardrail for the user's text and picture.

```python
# graph code: no model names, no node IDs
async for delta in caps.text.stream("lyrics", system, prompt):
    ...
vectors = await caps.text.embed("embed", ["some text"])
cover = await caps.image.generate(prompt=cover_prompt)
key = await caps.storage.put("songs/42/audio.mp3", data, "audio/mpeg")  # tenancy added for you
url = await caps.storage.url("songs/42/audio.mp3")  # presigned, goes in SSE
hits = await caps.rag.search("docs", "how do I ...", k=5)  # if text.embed is bound
```

Image and audio go in as prompt parts, loaded from storage by key (never kept in graph state):

```python
from wasifyai_platform_sdk import part_from_file

image = part_from_file(key, await caps.storage.get(key))  # type chosen from the extension
text = await caps.text.complete("multimodal", system, ["What is in this picture?", image])
```

The binding must declare what its model accepts, or the call fails before it is made:

```yaml
text.multimodal: { provider: litellm, model: multimodal, inputs: [text, image, audio] }
```

Tenant, product, user and run come from the run context, not from arguments. Every LLM call
records token usage in `usage_events`.

Capability calls for media **enqueue a job** and return a job handle. They never wait for
the GPU.

### Providers

| Provider | Used for | Notes |
|---|---|---|
| `litellm` | Text, streaming, embeddings | OpenAI-compatible; model is a LiteLLM alias; records token usage |
| `comfyui` | Image, music, video | Workflow JSON + map file; builds a job and queues it, never calls ComfyUI inline |
| `http` *(later)* | Hosted media APIs | Same interface, for models ComfyUI can't run |
| `fake` | Tests | Deterministic outputs, no GPU or network |

Every provider implements the same small interface, registered by name (dispatcher /
registry pattern).

### Object storage

Selected by environment wiring, not product config (one bucket per environment):

| Variable | Meaning |
|---|---|
| `STORAGE_ENDPOINT` | S3-compatible endpoint the API and worker use (`http://seaweedfs:8333` locally) |
| `STORAGE_PUBLIC_ENDPOINT` | Optional. URL browsers use when it differs from the one above; presigned URLs are signed for it |
| `STORAGE_BUCKET`, `STORAGE_REGION` | Bucket (`wasifyai`) and region (`us-east-1`) |
| `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` | Credentials (secret generated by `make setup`). Storage is off when unset |
| `NOTEBOOKS_SCHEMA` | Web profile: the Postgres schema of the notebooks (default `notebooks`). Notebooks are always on; there is no switch. A worker (`python -m wasifyai_notebooks.worker`, the `notebooks-worker` service in `compose.yaml`) must run, or sources stay pending |
| `NOTEBOOKS_READER_DIR` | Where the document reader is on the machine that runs the worker |
| `NOTEBOOKS_EMBED_MODEL`, `NOTEBOOKS_EMBED_DIMENSION` | The gateway alias that serves the notebooks' search (default `creation-embedder`, 1024); it uses `LITELLM_BASE_URL` and `LITELLM_API_KEY` |
| `NOTEBOOKS_MODELS_DIR` | Only without a gateway: the folder holding `embeddings/` (the local search model) |
| `VOICE_SCHEMA` | Web profile: the Postgres schema of speech (default `voice`). Speech is always on; there is no switch. Until the gateway aliases `voice-speak` and `voice-transcribe` are bound to a provider (admin Models page), the hosted speech models are listed as not available |
| `VOICE_ENGINE` | `worker` (default), `hosted`, `local` or `both`: `worker` runs the desktop's speech capabilities on engine workers (ADR-0087: `make worker`, the `engine-worker` service) and also lists the hosted models; nothing from a worker is offered until one is running. `hosted`, `local` or `both`: what answers speech. `local` is the desktop's runtime (audio.cpp, the lip sync component) over the models in `DESKTOP_DATA_DIR` (and `DESKTOP_MODELS_DIR`, `DESKTOP_EXTRA_MODEL_DIRS`), for a service on a machine that has them, such as a Mac; the web only uses what is ready there, setting up and fetching stay in the desktop app. `both` lists both and prefers a local model when one is ready. `scripts/web-local.sh` runs the whole stack this way |
| `VOICE_MODELS_FILE` | The descriptors of the hosted models (default `products/wasifyai-voice/hosted-models.yaml`). Each names a gateway alias; `voice-speak` and `voice-transcribe` must be bound in the gateway to the provider's speech and transcription models (OpenRouter or similar). The text and recordings are sent to that provider |
| `WORKER_ID`, `WORKER_JOB_TIMEOUT_S` | The engine worker (`services/engine-worker`, ADR-0087): its name in the list of workers (default: the machine's name and process id) and how long one job may run (default 3600 s). It reads `REDIS_URL` and the `STORAGE_*` settings like the media worker, and the engine's own `DESKTOP_DATA_DIR` for the models and runtimes it runs. `scripts/worker.sh` sets them for a Mac running `make dev` |

Keys are always `{tenant_id}/{product_id}/{user_id}/{path}`. For GCS, S3 and Azure Blob the same
interface applies (`obstore`); the adapter for each is a constructor in
`wasifyai_platform_sdk.storage`.

### LiteLLM aliases

An alias (`default-chat`, `lyrics-writer`, `prompt-enhancer`, `creation-embedder`, `moderator`, `moderator-nothink`, `multimodal`,
`embedder`) maps to a real model. Changing the underlying LLM never touches product config
([ADR-0025](decisions/0025-model-access-configuration.md)).

- **Defaults** are in `services/api/src/wasifyai_api/model_defaults.yaml` (Gemma 4 E4B, nomic-embed-text and the
  multilingual bge-m3 on Ollama). The API seeds them into LiteLLM's database at start, once. `make setup` pulls the
  Ollama models named there, and Helm's `ollama.models` must list the same ones (a test checks it).
- **Overrides** are made in the admin area (`/admin/models`): pick a provider (Ollama, Gemini, Groq,
  Cerebras, OpenRouter, any OpenAI-compatible server, or any LiteLLM model string), a model and, for
  hosted providers, an API key. They apply to new requests at once. "Reset" returns to the default.
- **Keys** are write-only: the model gateway stores them encrypted with `LITELLM_SALT_KEY` (set it once
  and never change it, or the saved keys become unreadable). They are never shown, logged or audited.
- **The moderator is protected.** Saving a new model for it first runs the product's guardrail test
  cases on the candidate (about half a minute) and only changes it if every must-refuse case is refused.
- LiteLLM keeps its tables in the `litellm` schema of the platform Postgres; `litellm.yaml` /
  the Helm ConfigMap hold settings only.

### Media backends

By default a product's media capabilities (`image.generate`, `video.generate`) run their ComfyUI
workflow on the local ComfyUI (`COMFYUI_BASE_URL`). An admin can choose another backend per product
capability at `/admin/media` ([ADR-0032](decisions/0032-media-backends.md)):

| Backend | Runs | Settings |
|---|---|---|
| `comfyui-local` | the workflow on a ComfyUI server (the default) | server address (optional) |
| `comfy-api` | the same workflow on Comfy Cloud, a serverless deployment or comfy-api-proxy (API v2) | API address (default `https://cloud.comfy.org`), API key |
| `openai-images` | images only: the prompt sent to `POST /images/generations` | API address, model, size (optional), API key (optional) |

The worker looks the binding up for every job, so a change applies to the next job. API keys are
encrypted with `MEDIA_SECRETS_KEY` (set once by `make setup`; changing it makes saved keys unreadable) and are
never shown, logged or audited. Remote backends take no GPU lock; their time is recorded as
`media.remote_seconds`.

### Speech

The speech servers (Kokoro, Whisper, Indic Parler-TTS, IndicConformer), the lip sync server and the media worker's
speech and lip sync runners were removed with ADR-0067. The voice product reaches speech through the gateway
(`VOICE_ENGINE=hosted`) or the speech runtime of the machine it runs on (`local`), see `VOICE_ENGINE` above and
`docs/runbooks/web-notebooks-voice.md`.

### Search over My creations

`SEARCH_MIN_SIMILARITY` (default 0.57) is the floor under which a match by meaning is not shown; re-tune it on
real data (ADR-0041, known issue 1). `SEARCH_INDEX_MODEL` (default `bge-m3/v2`) names what made the index rows: the embedder and the
text format. If an admin changes the model behind the `creation-embedder` alias, or `search_text` changes, change
this too and the background indexer re-embeds everything (a model with a different number of dimensions needs a
migration).
`SEARCH_RECONCILE_EVERY_S` (300) and `SEARCH_RECONCILE_BATCH` (200) set how often the background indexer checks for
creations that are missing from the index and how many it embeds each time.

### Metrics

The API and the media worker serve Prometheus metrics on `METRICS_PORT` (default 9464, separate from the API's
public port; `0` turns it off). Nothing but the cluster's Prometheus reaches it. See `docs/runbooks/monitoring.md`
and ADR-0048. The alert thresholds are chart values (`metrics.alerts.*`) and the stack is installed with
`make monitoring-up`.

**Only production sends alerts.** `ALERT_NOTIFICATIONS=on` (production values, or `.env` for a drill on kind) makes
Alertmanager send to Telegram and the Watchdog heartbeat go to Healthchecks.io, using `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID` and `HEALTHCHECKS_PING_URL`. Anything else (the default) routes every alert to a null receiver and
stores no token in the cluster: alerts still fire and show in Alertmanager and Grafana. There is no admin switch; to
mute production for a while, use an Alertmanager silence.

### A separate ComfyUI for video

`COMFYUI_VIDEO_BASE_URL` (worker and API; empty by default) is the ComfyUI that `video.*` jobs go to when the
product's capability has no saved address of its own. On Apple silicon LTX-Video needs `--fp32-unet`, a
process-wide flag, so video runs on its own ComfyUI (ADR-0037), started with `scripts/comfyui-video.sh` (port
8189). Both ComfyUIs share one GPU and one `GPU_ID`, so jobs still run one at a time. `JOB_TIMEOUT_S` (default 1200)
is the longest a job may run; a 5 second clip takes about 8 minutes on a Mac.

### ComfyUI workflows and map files

Workflows are exported from ComfyUI in **API format** and committed under
`products/<id>/workflows/`. ComfyUI identifies inputs by node ID, and those IDs change when a
workflow is rebuilt, so each workflow has a map file. Only the map file knows node IDs.

```yaml
# products/wasifyai-voice/workflows/ace-step-1.5-turbo.map.yaml
workflow: ace-step-1.5-turbo.json
licence: "Verify on model card before launch (ADR-0012)"
models:                      # files the ComfyUI host must have
  - checkpoints/ace_step_1.5_turbo.safetensors
inputs:
  lyrics:     { node: "14", field: "lyrics" }
  style:      { node: "14", field: "tags" }
  duration_s: { node: "17", field: "seconds" }
  seed:       { node: "3",  field: "seed" }
outputs:
  audio: { node: "21", type: audio }
```

Node IDs above are placeholders; take real ones from the exported workflow.

**To swap a model:** build and export the new workflow, write its map file, change one line
in `product.yaml`, open a PR. No Python changes.

## Later

If runtime switching is needed (A/B tests, per-tenant models), the same schema can be stored
in Postgres and layered on top of `product.yaml`. Not needed for the MVP.

