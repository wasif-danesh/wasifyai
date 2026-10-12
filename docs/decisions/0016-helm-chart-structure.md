# ADR-0016: One umbrella Helm chart, plain Ingress, in-cluster state for non-prod

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

Phase 2 needs a deployable skeleton on kind (local, CI) and k3s (home lab) that later extends to managed Kubernetes. ADR-0009 requires identical charts with `base` / `env` / `cloud` value overlays.

## Decision

- A single chart, `deploy/helm/wasifyai`, deploys the API, web app, LiteLLM, media worker, and (toggleable) Postgres, Redis and Ollama. `values.yaml` is the base. Overlays live in `values/<env>.yaml` (`local`, `staging`, `prod`) and `values/cloud/<cloud>.yaml`, applied in that order.
- Secrets are never in values. The chart reads a pre-existing Secret (`secrets.existingSecret`); `scripts/k8s-secrets.sh` creates it with random values. External Secrets replaces this in prod.
- Postgres and Redis run in-cluster for local and staging (`postgres.enabled`); prod switches to managed services with `DATABASE_URL` from the Secret.
- Ollama runs in-cluster as a Deployment with a PVC. The container pulls every model listed in `ollama.models` and reports ready only afterwards. Locally, `ollama.externalUrl` points at the native Ollama instead, because the model does not fit in the kind node.
- Migrations run as a post-install/upgrade Job (also an Argo CD PostSync hook).
- Ingress is the standard `networking.k8s.io/v1` Ingress (k3s bundles Traefik). Gateway API stays an open item.
- CI installs the chart on kind and runs a smoke test before images are pushed.

## Consequences

- One artifact for every environment; environment differences are values only.
- Staging tracks the `latest` image tag, so Argo CD does not roll out new images on its own. A follow-up (pinned tags committed by CI, or Argo CD Image Updater) is needed.
- GHCR packages must be public (or an image pull secret supplied) for the home lab to pull them.
- In-cluster Postgres is not highly available; acceptable for staging only.
