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
# products/wasifyai-music/product.yaml
id: wasifyai-music
capabilities:
  text.lyrics:
    provider: litellm
    model: lyrics-writer          # a LiteLLM alias, not a raw model name
  music.generate:
    provider: comfyui
    workflow: ace-step-1.5-turbo
    defaults: { duration_s: 60 }
  image.generate:
    provider: comfyui
    workflow: flux2-klein-4b
    defaults: { width: 1024, height: 1024 }
quotas:
  songs_per_user_per_day: 10
settings:
  audio_format: mp3
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
track = await caps.music.generate(lyrics=lyrics, style=style, duration_s=60, seed=seed)
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

By default a product's media capabilities (`image.generate`, `music.generate`) run their ComfyUI
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

Text to speech (ADR-0042) calls an OpenAI-compatible speech server. `SPEECH_SERVERS` on the media worker maps
an engine name to its address (`kokoro=http://speech:8000`). `compose.yaml` runs the `speech` service
(Speaches, CPU image) with `WHISPER__COMPUTE_TYPE=int8`, which keeps Whisper inside a 6 GB machine. In Helm,
`speech.enabled=true` adds the same service and sets the variable. The models are installed on request: `make dev` runs `scripts/speech-models.sh` (Kokoro, Whisper large-v3-turbo
and large-v3, about 5 GB, once, into the `speechmodels` volume), and in Helm a Job per release does the same from
`speech.models`. Without them every speech job answers 404.
Speech to text uses the same server under the engine name `whisper` (`whisper=http://speech:8000`): Whisper
large-v3-turbo transcribes and large-v3 finds the language, both downloaded into the volume on first use. The 22 Indian
languages go to `stt-indic` instead (`indic-stt=http://stt-indic:8000`: IndicConformer, our adapter; needs `HF_TOKEN`
for its gated model, about 2.7 GB of memory; in Helm `sttIndic.enabled=true`).
Bengali uses a second server, `speech-indic` (our adapter for Indic Parler-TTS, `indic-parler=http://speech-indic:8000`).
Its model is gated: accept the terms on Hugging Face and put a read token in `.env` as `HF_TOKEN`. It needs about
4.5 GB of memory, more than the default 6 GB Podman VM can give next to the other services. In Helm,
`speechIndic.enabled=true` with a Secret named in `speechIndic.hfTokenSecret`.
The voices a user can choose are listed in `products/wasifyai-tts/voices.yaml`.

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

In Helm the lip sync server can be a pod (`lipsync.enabled=true`, image `lipsync-musetalk`, built from
`services/lipsync-musetalk/Containerfile`: CPU by default, `--build-arg BASE=... --build-arg TORCH_INDEX=` for CUDA;
its models are fetched on first start into a volume) and the worker's `LIPSYNC_SERVER_URL` is then set for you.
`LIPSYNC_SERVER_URL` (worker; empty by default) is the lip sync server, `services/lipsync-musetalk`, that
`video.lipsync` jobs go to (ADR-0044): MuseTalk, run natively on a Mac with `scripts/lipsync-server.sh`. With it empty a
lip sync is a placeholder in stub mode and fails in real mode.

### ComfyUI workflows and map files

Workflows are exported from ComfyUI in **API format** and committed under
`products/<id>/workflows/`. ComfyUI identifies inputs by node ID, and those IDs change when a
workflow is rebuilt, so each workflow has a map file. Only the map file knows node IDs.

```yaml
# products/wasifyai-music/workflows/ace-step-1.5-turbo.map.yaml
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
