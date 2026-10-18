# Environments

One set of container images and Helm charts; three environments. Code never branches on
environment. Differences live in env vars and Helm values overlays.

## Summary

| | Dev | Staging | Prod |
|---|---|---|---|
| Where | MacBook (Apple Silicon) | Home lab | AWS, GCP or Azure |
| Orchestration | Podman + `compose.yaml`; `kind` for chart testing | k3s + Argo CD | EKS / GKE / AKS + Argo CD |
| LLM | Ollama, native | Ollama pod on GPU node | vLLM, or hosted APIs via LiteLLM |
| Media | ComfyUI native, or home lab ComfyUI via Tailscale, or stub worker | ComfyUI pod, GPU time-sliced | ComfyUI GPU pool, KEDA scale-to-zero |
| Postgres | Container | CloudNativePG | Managed (RDS, Cloud SQL, Azure Flexible Server) |
| Redis | Container | In-cluster | Managed |
| Object storage | SeaweedFS | SeaweedFS | S3, GCS or Azure Blob |
| Secrets | `.env` (gitignored) | SOPS / External Secrets | External Secrets from cloud secret manager |
| Deploys | Manual | Auto-sync from `main` | Promotion only (tag or PR) |

## Dev (MacBook)

- **Engine:** Podman + Podman Desktop. Scripts use `${CONTAINER_ENGINE:-podman}` so Colima or
  Docker also work.
- **Containers:** API, Next.js, LiteLLM, media worker, Postgres, Redis, SeaweedFS.
- **Native on the host:** Ollama and ComfyUI. Containers on macOS cannot use the Metal GPU.
  Containers reach them at `host.containers.internal`, configured through
  `OLLAMA_BASE_URL` / `COMFYUI_BASE_URL`.
- **Media worker modes:** `COMFYUI_MODE=stub` (the default in `.env.example`) returns placeholder
  images and audio, so every machine can run the whole media flow. `COMFYUI_MODE=real` drives
  ComfyUI at `COMFYUI_BASE_URL` (a native ComfyUI on the Mac works at
  `http://host.containers.internal:8188`).
- **Heavy models:** ACE-Step and FLUX.2 klein may be slow or incomplete on Apple Silicon. Set
  `COMFYUI_BASE_URL` to the home lab ComfyUI over Tailscale, or run the worker in stub mode
  (returns sample files) for UI work.
- **Kubernetes testing:** `kind` with Podman (`KIND_EXPERIMENTAL_PROVIDER=podman`). Prefer
  `kind` over `k3d` on Podman.
- **Socket-based tools** (Testcontainers, kind): set `DOCKER_HOST` to the Podman machine
  socket.

## Staging (home lab)

- **Cluster:** k3s on a Linux host with one 24 GB NVIDIA GPU.
- **GPU:** NVIDIA GPU Operator with **time-slicing** so the Ollama and ComfyUI pods can share
  the card. Use Ollama (loads and unloads on demand), not vLLM, which pre-allocates most of
  the VRAM. The media worker unloads the LLM (`keep_alive: 0`) before each generation job.
- **Concurrency:** one generation job at a time on the GPU. Expect queueing.
- **Access:** Tailscale. No ports forwarded from the internet.
- **Deploys:** Argo CD syncs from `main` automatically.

## Prod (cloud)

- **Primary cloud:** GCP (ADR-0015). Keep AWS and Azure deployable but not running.
- **Node pools:** CPU pool (API, Next.js, LiteLLM, workers' control) and GPU pool (ComfyUI,
  vLLM) with taints and tolerations.
- **GPU nodes:** 24 GB L4 / A10-class to match staging. Node autoscaling is per cloud
  (Karpenter, GKE autoscaler, AKS autoscaler) in the OpenTofu layer. Pod autoscaling is KEDA
  on queue depth.
- **Identity:** workload identity per cloud (EKS Pod Identity, GKE Workload Identity, Azure
  Workload Identity) via service-account annotations in the cloud overlay.

## Portability traps

| Trap | Mitigation |
|---|---|
| Azure Blob does not speak the S3 API | Storage interface with S3 and Azure Blob adapters |
| Cloud-specific queues and functions | Not allowed in the core; Redis + Kubernetes jobs instead |
| Load-balancer annotations | Only in Gateway config in the cloud overlay |
| Redis Cluster-only commands | Avoid; plain connection string |
| Postgres extensions | Only pgvector and standard features (available on all three) |
| GPU drivers | GPU Operator, or the cloud-managed driver toggle in the overlay |
| arm64 Mac vs amd64 servers | Multi-arch images for every service |

## Delivery pipeline

```
push / PR ─► GitHub Actions: lint, test, helm and kind ──► (release tag or manual run only) buildah multi-arch build ─► GHCR
main      ─► Argo CD auto-sync ─► staging (home lab)
release   ─► tag or promotion PR ─► Argo CD ─► prod
```

- Helm values: `deploy/helm/wasifyai/values.yaml` (base), then `values/{local,staging,prod}.yaml`,
  then `values/cloud/{homelab,gcp,...}.yaml` (ADR-0016).
- Local Kubernetes: `make kind-up`, `make kind-test`, `make kind-down` (kind on Podman).
- Home lab setup: [runbooks/homelab-k3s.md](runbooks/homelab-k3s.md).
- Notebooks and speech on the web profile (switches, gateway aliases, the worker): [runbooks/web-notebooks-voice.md](runbooks/web-notebooks-voice.md).
- CI also installs charts into a `kind` cluster as a smoke test.
- Occasionally smoke-test a second cloud so portability does not rot.
