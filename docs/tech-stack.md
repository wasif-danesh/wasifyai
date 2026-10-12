# Tech stack

Items marked *(later)* have a seam in the design but are not part of the first build.
Items marked *(open)* are undecided between the listed options.

## Frontend

| Tool | Role |
|---|---|
| React | UI library for every product frontend |
| Next.js | Product apps; route handlers act as the BFF proxy to FastAPI |
| TypeScript | All frontend and BFF code, strict mode |
| openapi-typescript | Generates TS types from FastAPI's OpenAPI schema so contracts can't drift |
| Auth.js | OAuth sign-in (Google, GitHub, Microsoft) for the MVP |
| Vercel AI SDK *(open)* | Streaming hooks; alternative is a small custom `EventSource` hook |

## Backend and orchestration

| Tool | Role |
|---|---|
| Python 3.12 | API, graphs, workers, AI tooling |
| FastAPI | Hosts graphs, SSE streams, job callbacks, tenant context |
| Pydantic / pydantic-settings | Contracts, structured LLM output, configuration from env vars |
| LangGraph | Stateful graph runtime: loops, branches, human-in-the-loop interrupts |
| LangChain core | Message types, model wrappers, retrievers, tool adapters used by LangGraph |
| LangGraph Postgres checkpointer | Persists graph state so runs survive restarts and resume anywhere |
| LangGraph Studio | Local visual debugger for graphs (`langgraph dev`) |
| SSE | Server-to-browser stream for tokens, node status, job progress, completion |
| MCP | Standard interface for graphs to reach files, databases and tools |
| Alembic | Schema migrations |
| uv | Python package manager and workspace |

## AI and inference

| Tool | Role |
|---|---|
| LiteLLM | OpenAI-compatible gateway in front of every LLM backend; aliases; spend tracking |
| Ollama | LLM serving in dev (native) and staging (pod) |
| vLLM | High-throughput LLM serving on dedicated GPUs in prod |
| ComfyUI | Image, music and video generation via versioned JSON workflows |
| Gemma 4 E4B | Default text model (multimodal input); Qwen or Llama remain possible behind LiteLLM (ADR-0018) |
| ACE-Step 1.5 | Music generation for `wasifyai-music` (commercial use permitted; see ADR-0012) |
| FLUX.2 [klein] 4B | Cover art generation for `wasifyai-music` (Apache 2.0, ~13 GB VRAM; see ADR-0019) |
| SD 1.5 / SDXL / other Flux | Other image models available through the same capability |

## Data and storage

| Tool | Role |
|---|---|
| PostgreSQL | App data, checkpoints, jobs, usage events |
| pgvector | Vector search for RAG inside Postgres |
| Redis | Job queue and pub/sub |
| SeaweedFS | S3-compatible object storage in dev and staging (MinIO's community image was withdrawn; ADR-0017) |
| S3 / GCS / Azure Blob | Prod object storage, one per cloud |
| obstore | One storage interface across S3, GCS and Azure Blob (ADR-0015) |

## Containers and local development

| Tool | Role |
|---|---|
| Podman + Podman Desktop | Open-source, rootless local container engine and GUI |
| Compose spec (`compose.yaml`) | Engine-neutral local stack definition |
| Containerfile / OCI images | Standard images that run on Podman, containerd and every cloud |
| Buildah | Multi-arch (arm64 + amd64) image builds locally and in CI |
| kind | Local Kubernetes cluster for testing Helm charts |
| Tilt *(open)* | Live-reload inner loop against Kubernetes |
| Colima | Open-source fallback engine if Podman causes trouble |

## Kubernetes and platform add-ons

| Tool | Role |
|---|---|
| k3s | Home lab staging cluster |
| EKS / GKE / AKS | Managed Kubernetes in prod |
| Helm | Charts with base / env / cloud values overlays |
| Argo CD | GitOps: auto-sync staging, promote to prod |
| Gateway API: Traefik or Envoy Gateway *(open)* | Portable ingress and routing |
| cert-manager | TLS certificates |
| ExternalDNS | DNS records from cluster resources |
| External Secrets Operator | Secrets from AWS Secrets Manager, GCP Secret Manager, Azure Key Vault |
| NVIDIA GPU Operator | GPU drivers and device plugin; time-slicing in staging |
| KEDA | Autoscale GPU workers on Redis queue depth, including to zero |
| CloudNativePG | In-cluster Postgres for staging |

## Infrastructure and delivery

| Tool | Role |
|---|---|
| OpenTofu | Infrastructure as code; one module per target with identical outputs |
| GitHub Actions | Lint, test, multi-arch build |
| GHCR | Container registry |
| SOPS | Encrypted secrets in Git |
| pnpm + Turborepo | TypeScript monorepo packages and tasks |

## Observability, security, operations *(later)*

| Tool | Role |
|---|---|
| OpenTelemetry | Traces, metrics, logs (instrumented from day one) |
| Langfuse | LLM traces: prompts, cost, latency |
| Prometheus / Grafana / Loki | Metrics, dashboards, logs |
| Keycloak or Authentik *(open)* | Central OIDC broker once there are several products |
| Tailscale | Private access to the home lab |
| Billing provider *(open)* | Reads the `usage_events` table |

## Hardware

| Item | Role |
|---|---|
| Apple Silicon MacBook | Dev machine; Ollama and ComfyUI run natively on Metal |
| 24 GB NVIDIA GPU (RTX 4090 preferred, 3090 budget) | Staging GPU, matched to 24 GB L4 / A10-class cloud GPUs |
