# Architecture

Status: **Draft**, October 2026. Decisions referenced here are recorded in
[`decisions/`](decisions/README.md).

## Goals

- Launch new AI products quickly by reusing one platform core.
- Run identical container images on a MacBook (dev), a home lab k3s cluster (staging) and
  managed Kubernetes on AWS, GCP or Azure (prod).
- Prefer open-source components; keep every AI model swappable.
- Defer auth, billing and observability without making them expensive to add later.

## Three layers

```mermaid
flowchart TB
  subgraph L3["Platform and products (identical everywhere)"]
    WEB[Next.js apps] --> API[FastAPI + LangGraph]
    API --> GW[LiteLLM gateway]
    API --> PG[(Postgres + pgvector)]
    API --> RD[(Redis)]
    RD --> MW[Media workers] --> CUI[ComfyUI]
    API --> OBJ[(Object storage)]
    MW --> OBJ
  end
  subgraph L2["Cluster add-ons (portable, configured per cloud)"]
    GWAPI[Gateway API] --- CM[cert-manager] --- EDNS[ExternalDNS]
    ESO[External Secrets] --- GPUOP[NVIDIA GPU Operator] --- KEDA[KEDA] --- ARGO[Argo CD]
  end
  subgraph L1["Infrastructure (per environment, OpenTofu)"]
    DEV[Dev: MacBook, Podman, native Metal]
    STG[Staging: home lab k3s, 24 GB GPU]
    PRD[Prod: EKS / GKE / AKS]
  end
  L3 --> L2 --> L1
```

1. **Infrastructure** is the only cloud-aware layer. One OpenTofu module per target, each
   exposing the same outputs: cluster, CPU node pool, GPU node pool, Postgres, Redis, bucket,
   DNS.
2. **Cluster add-ons** are the same tools everywhere, with per-cloud settings.
3. **Platform and products** are identical Helm charts and images. Values overlay as
   `base` → `env` (staging, prod) → `cloud` (homelab, aws, gcp, azure).

## Components

| Component | Responsibility | Scales on |
|---|---|---|
| Next.js app | Product UI; route handlers act as the backend-for-frontend (BFF) and proxy to the API. The browser never calls FastAPI directly. | CPU, stateless |
| FastAPI + LangGraph | Runs product graphs; streams SSE; owns tenant context, identity, usage events, job callbacks | CPU, stateless |
| LiteLLM | One OpenAI-compatible API in front of every LLM backend; model aliases; spend tracking | CPU, stateless |
| Ollama / vLLM | LLM inference: Ollama in dev and staging, vLLM or hosted APIs in prod | GPU |
| Media worker | Consumes Redis jobs, drives ComfyUI, uploads outputs, publishes progress, resumes graphs | Queue depth (KEDA) |
| ComfyUI | Image, music and video generation from versioned JSON workflows | GPU |
| Postgres + pgvector | App data, LangGraph checkpoints, job records, usage events, RAG vectors | Managed in prod |
| Redis | Job queue; pub/sub fan-out of progress events to any API replica | Managed in prod |
| Object storage | Generated media and uploads. SeaweedFS (S3 API) in dev/staging; S3, GCS or Azure Blob in prod | Managed |

## Request flow (generic)

```mermaid
sequenceDiagram
  participant B as Browser
  participant N as Next.js BFF
  participant A as FastAPI + LangGraph
  participant L as LiteLLM
  participant R as Redis
  participant W as Media worker
  participant C as ComfyUI
  participant S as Object storage
  B->>N: POST /api/runs (idea)
  N->>A: POST /runs (identity, tenant)
  A-->>B: SSE: node, token...
  A->>L: chat completion (structured output)
  L-->>A: JSON
  A->>R: enqueue job (job_id saved in graph state)
  A-->>B: SSE: job_progress (queued)
  W->>R: dequeue
  W->>C: POST /prompt (workflow + mapped inputs)
  C-->>W: WebSocket progress
  W->>R: publish progress
  R-->>A: progress
  A-->>B: SSE: job_progress
  W->>S: upload output
  W->>A: job callback (resume graph)
  A-->>B: SSE: done (asset URLs)
```

Key properties:

- **Graph state lives in Postgres**, so any API replica can resume any run. No sticky
  sessions.
- **Progress fans out via Redis pub/sub**, so the replica holding a browser's SSE connection
  receives events produced anywhere.
- **GPU work is never awaited inline.** Nodes enqueue and the graph resumes on callback.
- **Outputs are URLs**, never bytes in the stream.

## Platform core vs products

A product is a folder under `products/` containing:

- `product.yaml`: ID, capability bindings, quotas, feature flags
- `graphs/`: LangGraph graphs, registered with the API at startup
- `prompts/`: versioned prompt templates
- `workflows/`: ComfyUI API-format workflow JSON plus `*.map.yaml` input/output maps

Adding a product adds no endpoints for running it: the API's graph registry exposes registered
graphs through generic `/products/{product_id}/runs` routes (ADR-0003). A product may add
authenticated read routes for its own data under `/products/{product_id}/` (ADR-0023). Product UIs
live in one shared Next.js app, `apps/web` (ADR-0014). Controls and data grids use shadcn/ui and TanStack Table
(ADR-0045), and inside a product the user navigates with a side panel while the home page keeps its cards (ADR-0046);
the side panel and the shadcn/ui components are built for the product screens; other screens migrate as they are touched.

What a product's routes and graphs may reach is the engine's services: one typed `EngineServices` object
(`wasifyai_platform_sdk.services`), `deps.state` in a route and `caps.extras["app_state"]` in a graph, with a field for each
service and `None` where this deployment has none (stage F1). The engine builds it, with its own services added
(`ApiServices`), in `wasifyai_api/assemble.py`: what both deployments share first, then the web's or the desktop's builder.
`app.state.services` is the only attribute of the app; an engine route reads it with `services_of(request)`.

## Capabilities

Graphs request **capabilities** (`text.<name>`, `image.generate`, `video.generate`), never specific models. `product.yaml` binds each capability to a
provider (`litellm`, `comfyui`, later `http`). Swapping a model is a config change.
Details: [configuration.md](configuration.md), ADR-0010.

## GPU strategy

| | Dev (Mac) | Staging (home lab) | Prod (cloud) |
|---|---|---|---|
| Hardware | Apple Silicon unified memory | One 24 GB NVIDIA card (RTX 4090 preferred, 3090 budget) | 24 GB L4 / A10-class nodes |
| LLM | Ollama, native (Metal) | Ollama in a pod | vLLM per GPU, or hosted APIs via LiteLLM |
| Media | ComfyUI native, or remote home lab ComfyUI over Tailscale | ComfyUI pod | ComfyUI pool scaled on queue depth, to zero when idle |
| Sharing | Unload LLM before generation | GPU Operator time-slicing; worker unloads LLM before generation | One workload per GPU |

Docker/Podman on macOS cannot reach the Metal GPU, so GPU services run natively on the Mac.

## Desktop app and assistant (proposed)

A desktop application (Tauri shell, Mac first) and an assistant home screen are proposed on top of this platform:
the same engine runs under a `desktop` profile (SQLite, in-process queue, local files) next to the `web` profile
described above. Nothing here changes until the ADRs are accepted. Start with
[ADR-0056](decisions/0056-desktop-app-and-web-share-one-engine.md) (the shape) and
[ADR-0062](decisions/0062-reuse-matrix-engines-per-capability.md) (the engine per capability, with measurements in
[`spikes/unsloth-phase0.md`](spikes/unsloth-phase0.md)); then
[0057](decisions/0057-ai-assistant-chat-first-shell.md) (assistant),
[0058](decisions/0058-desktop-link-runner-and-remote-ui.md) (web to desktop link),
[0059](decisions/0059-comfyui-managed-sidecar-image-engine.md) (image engine),
[0060](decisions/0060-documents-local-first-rag.md) (documents) and
[0061](decisions/0061-how-unsloth-code-enters-wasifyai.md) (how Unsloth code is imported). v1 is desktop first,
Mac first, image first, English only.

## Everything a user makes is searchable

My creations (`/creations`, ADR-0040) is one library with one search (ADR-0041): a per-user index of the words
of every song, image and video, with a multilingual embedding (`bge-m3`) and an exact-word check. **A new product
or kind of creation is not finished until it is indexed**: text to index, `caps.index_creation` on save,
`deps.unindex` on delete, a registered `IndexSource`, an `ids=` filter on its list route and a card in the
library. The checklist is in ADR-0041 ("A rule for everything built later").

## Seams for later features

| Feature | Seam built now |
|---|---|
| Multi-tenancy | `tenant_id` and `product_id` on every table, job and object key |
| Auth | Identity resolved on every request (stub in dev); Auth.js in Next.js, the BFF signs a short-lived JWT that FastAPI validates (ADR-0030); optional central OIDC (Keycloak / Authentik) later |
| Billing | `usage_events` table: tokens, GPU seconds, jobs per tenant and user |
| Observability | OpenTelemetry instrumentation, structured JSON logs with trace IDs; Langfuse for LLM traces; Prometheus / Grafana / Loki later |
| Quotas | Usage events + per-product limits in `product.yaml` |

## Security baseline

- Ollama and ComfyUI have no authentication. Bind to localhost or the cluster network only;
  never expose publicly. Remote access via Tailscale.
- Pin and review ComfyUI custom nodes; malicious nodes have appeared in community registries.
- MCP servers and tools run least-privilege (read-only DB users, scoped folders).
- Workload identity per cloud; no static cloud keys in pods.
- Rootless containers locally (Podman default).
