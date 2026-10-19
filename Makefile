CONTAINER_ENGINE ?= podman
export CONTAINER_ENGINE

.PHONY: engine-bundle reader-locks test-comfyui test-integration setup setup-k8s preflight dev down logs migrate test lint format contracts helm-lint kind-up kind-test kind-e2e kind-down monitoring-up monitoring-drill monitoring-drill-meta urls
setup:
	./scripts/setup.sh
setup-k8s:
	./scripts/setup.sh --k8s
preflight:
	./scripts/preflight.sh
dev:
	./scripts/dev.sh
logs:
	$(CONTAINER_ENGINE) compose logs -f
down:
	$(CONTAINER_ENGINE) compose down
migrate:
	cd services/api && uv run alembic upgrade head   # needs postgres on localhost:5432
test:
	uv run pytest
	pnpm test
# Needs the stack running (make dev): real Postgres + pgvector, SeaweedFS, LiteLLM + Ollama.
test-integration:
	DATABASE_URL=postgresql+asyncpg://wasifyai:wasifyai@localhost:5432/wasifyai \
	LITELLM_BASE_URL=http://localhost:4000 STORAGE_ENDPOINT=http://localhost:8333 \
	uv run pytest services/api/tests/integration -v
# Real generation on your local ComfyUI: an image, then (if installed) the product's own music and
# cover workflows (ACE-Step 1.5 and FLUX.2 klein). Slow on first use: models load into memory.
test-comfyui:
	COMFYUI_E2E=1 uv run pytest services/api/tests/integration/test_media_e2e.py services/api/tests/integration/test_real_models.py -v
lint:
	uv run ruff check . && uv run ruff format --check . && uv run pyright
	pnpm lint && pnpm typecheck
format:
	uv run ruff format . && uv run ruff check --fix .
engine-bundle:   # the files the desktop app installs the engine from (apps/desktop/engine-bundle)
	./scripts/build-engine-bundle.sh
reader-locks:   # the notebooks' document reader lock files (products/wasifyai-notebooks/reader), commit the result
	./scripts/lock-reader.sh
contracts:
	uv run python scripts/export_openapi.py
	uv run python -m wasifyai_api.actions_engine --write
	pnpm --filter @wasifyai/contracts generate
helm-lint:
	@for f in "" "-f deploy/helm/wasifyai/values/local.yaml" "-f deploy/helm/wasifyai/values/staging.yaml -f deploy/helm/wasifyai/values/cloud/homelab.yaml" "-f deploy/helm/wasifyai/values/prod.yaml"; do \
		helm lint deploy/helm/wasifyai $$f >/dev/null && helm template t deploy/helm/wasifyai $$f >/dev/null && echo "ok: helm $$f" || exit 1; done
kind-up:
	./scripts/kind-up.sh
urls:
	@uv run python scripts/urls.py   # every URL of the running system, for the mode it is in
monitoring-up:
	./scripts/monitoring-up.sh   # Prometheus, Alertmanager, Grafana, Loki; alerts to Telegram (ADR-0048)
monitoring-drill-meta:
	@scripts/monitoring-drill-meta.sh

monitoring-drill:
	./scripts/monitoring-drill.sh   # stop the worker, expect a Telegram alert, start it again
kind-e2e:
	uv run python scripts/kind-e2e.py   # makes something with each of the six products
kind-test:
	./scripts/kind-smoke.sh
kind-down:
	./scripts/kind-down.sh
