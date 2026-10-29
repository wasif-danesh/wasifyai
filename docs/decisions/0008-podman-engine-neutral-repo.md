# ADR-0008: Podman for local development, engine-neutral repo

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

Preference for open source. Docker Desktop is proprietary; OrbStack is proprietary.

## Decision

Use Podman + Podman Desktop on the Mac and Buildah for multi-arch builds. The repo stays engine-neutral: `compose.yaml` (standard Compose spec), `Containerfile`, scripts using `${CONTAINER_ENGINE:-podman}`, host services by env var (`host.containers.internal` default). Colima is the fallback. `kind` for local Kubernetes.

## Consequences

- Rootless by default; native pods and `podman kube play` help test manifests.
- Some tooling expects the Docker socket; set `DOCKER_HOST`.
- No effect on staging or prod, which run containerd.
